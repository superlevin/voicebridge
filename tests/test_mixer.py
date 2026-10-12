"""Verify non-silent overlapping PCM, not merely that two streams can open."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import audio_engine as engine


class MixerTests(unittest.TestCase):
    def test_overlap_single_stream_and_independent_stop(self):
        self.check_overlap(cancel_speech=True)

    def test_music_continues_after_speech_naturally_finishes(self):
        self.check_overlap(cancel_speech=False)

    def check_overlap(self, cancel_speech):
        mixer = engine.AudioMixer()
        music_cancel, speech_cancel = threading.Event(), threading.Event()
        first_block = threading.Event()
        recorded = []
        # Integer cycles within each 20 ms block give exact, separable spectra.
        t = np.arange(engine.MIX_FRAMES) / engine.MIX_RATE
        music = np.repeat((0.2 * np.sin(2 * np.pi * 400 * t))[:, None], 2, axis=1).astype('float32')
        speech = np.repeat((0.3 * np.sin(2 * np.pi * 1000 * t))[:, None], 2, axis=1).astype('float32')
        stream = MagicMock()
        stream.__enter__.return_value = stream
        def write(block):
            recorded.append(block.copy())
            first_block.set()
            # Cancel speech only after it has entered the sum.
            spectrum = np.abs(np.fft.rfft(block[:, 0]))
            if cancel_speech and spectrum[20] > 100:
                speech_cancel.set()
            time.sleep(0.002)
        stream.write.side_effect = write
        device = {'default_samplerate': 48000, 'max_output_channels': 2}
        with patch.object(engine.sd, 'query_devices', return_value=device), patch.object(engine.sd, 'OutputStream', return_value=stream) as factory:
            with ThreadPoolExecutor(max_workers=2) as pool:
                music_job = pool.submit(mixer.play, iter([music] * 40), 17, None, music_cancel)
                self.assertTrue(first_block.wait(2))
                speech_job = pool.submit(mixer.play, iter([speech] * 5), 17, None, speech_cancel)
                if cancel_speech:
                    with self.assertRaises(engine.Cancelled):
                        speech_job.result(timeout=5)
                else:
                    speech_job.result(timeout=5)
                music_job.result(timeout=5)
        self.assertEqual(factory.call_count, 1, 'Only one stream may own the device')
        powers = [np.abs(np.fft.rfft(block[:, 0])) for block in recorded]
        overlap = [i for i, power in enumerate(powers) if power[8] > 80 and power[20] > 100]
        self.assertTrue(overlap, 'Output must contain both music and speech frequencies')
        self.assertTrue(all(p[8] > 80 for p in powers), 'Music must never disappear')
        self.assertTrue(any(p[20] < 0.01 for p in powers[overlap[-1] + 1:]), 'Music must continue after speech stops')
        stream.abort.assert_not_called()

    def test_peak_limit_and_stereo_sum(self):
        result = engine.mix_blocks([np.full((960, 2), 0.8, dtype='float32'),
                                    np.full((400, 2), 0.7, dtype='float32')])
        np.testing.assert_allclose(result[:400], 1)
        np.testing.assert_allclose(result[400:], 0.8)

    def test_monitor_gets_same_mix(self):
        block = np.column_stack([np.full(960, 0.2), np.full(960, -0.1)]).astype('float32')
        streams = [MagicMock(), MagicMock()]
        for stream in streams:
            stream.__enter__.return_value = stream
        with patch.object(engine.sd, 'query_devices', return_value={'default_samplerate': 48000, 'max_output_channels': 2}), patch.object(engine.sd, 'OutputStream', side_effect=streams):
            engine.AudioMixer().play(iter([block]), 17, 22, threading.Event())
        np.testing.assert_array_equal(streams[0].write.call_args.args[0], streams[1].write.call_args.args[0])
