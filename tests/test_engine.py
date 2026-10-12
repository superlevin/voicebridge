import tempfile
import asyncio
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import numpy as np
import audio_engine as engine


class EngineTests(unittest.TestCase):
    def test_music_mp3_stereo_resampling_and_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '音樂.mp3'
            time = np.arange(36000) / 24000
            audio = np.column_stack([0.2 * np.sin(2 * np.pi * 440 * time),
                                     0.1 * np.sin(2 * np.pi * 880 * time)])
            engine.sf.write(path, audio, 24000, format='MP3')
            progress = []
            with patch.object(engine.sd, 'query_devices', return_value={'default_samplerate': 48000, 'max_output_channels': 2}), patch.object(engine.sd, 'OutputStream') as stream:
                engine.play_file(path, 17, 0.5, threading.Event(), lambda e, d: progress.append((e, d)))
                output = np.concatenate([c.args[0] for c in stream.return_value.__enter__.return_value.write.call_args_list])
                self.assertEqual(output.shape, (72000, 2))
                self.assertGreater(np.max(np.abs(output[:, 0] - output[:, 1])), 0.01)
                self.assertEqual(progress[-1], (1.5, 1.5))
                self.assertEqual(stream.call_args.kwargs['device'], 17)

    def test_music_stop_during_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.wav'
            engine.sf.write(path, np.zeros((48000, 2)), 24000)
            cancel = threading.Event()
            with patch.object(engine.sd, 'query_devices', return_value={'default_samplerate': 48000, 'max_output_channels': 2}), patch.object(engine.sd, 'OutputStream') as stream:
                output = stream.return_value.__enter__.return_value
                output.write.side_effect = lambda _: cancel.set()
                with self.assertRaises(engine.Cancelled):
                    engine.play_file(path, 17, 1, cancel)
                output.abort.assert_called_once()
                self.assertEqual(output.write.call_count, 1)

    def test_throttling_retry_then_success(self):
        error = engine.aiohttp.ClientResponseError(None, (), status=429, headers={'Retry-After': '2'})
        with patch.object(engine.edge_tts, 'Communicate') as communicate, patch.object(engine.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            communicate.return_value.save = AsyncMock(side_effect=[error, None])
            asyncio.run(engine.save_online('test', 'voice', 0, 'test.mp3'))
            self.assertEqual(communicate.return_value.save.await_count, 2)
            sleep.assert_awaited_once_with(2)

    def test_forbidden_is_not_retried(self):
        error = engine.aiohttp.ClientResponseError(None, (), status=403)
        with patch.object(engine.edge_tts, 'Communicate') as communicate:
            communicate.return_value.save = AsyncMock(side_effect=error)
            with self.assertRaises(engine.aiohttp.ClientResponseError):
                asyncio.run(engine.save_online('test', 'voice', 0, 'test.mp3'))
            self.assertEqual(communicate.return_value.save.await_count, 1)

    def test_resample_duration_channels_and_volume(self):
        source = np.full((24000, 1), 0.5, dtype='float32')
        result = engine.convert_audio(source, 24000, 48000, 2, 0.4)
        self.assertEqual(result.shape, (48000, 2))
        np.testing.assert_allclose(result, 0.2)
        self.assertEqual(result.dtype, np.float32)

    def test_cancel_before_synthesis_and_playback(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(engine.Cancelled):
            engine.synthesize('test', 'unused', 0, 'unused.wav', cancel)
        with self.assertRaises(engine.Cancelled):
            engine.play(np.zeros((1, 1)), 24000, -1, 1, cancel)

    def test_explicit_routing_and_stop_during_playback(self):
        cancel = threading.Event()
        with patch.object(engine.sd, 'query_devices', return_value={'default_samplerate': 48000, 'max_output_channels': 2}), patch.object(engine.sd, 'OutputStream') as stream:
            output = stream.return_value.__enter__.return_value
            output.write.side_effect = lambda _: cancel.set()
            with self.assertRaises(engine.Cancelled):
                engine.play(np.ones((48000, 1), dtype='float32'), 48000, 17, 0.5, cancel)
            self.assertEqual(stream.call_args.kwargs['device'], 17)
            output.abort.assert_called_once()
            self.assertEqual(output.write.call_count, 1)

    def test_offline_unicode_and_literal_text(self):
        voices = engine.offline_voices()
        self.assertTrue(voices)
        with tempfile.TemporaryDirectory() as folder:
            audio, rate = engine.synthesize('你好。測試文字 $() 與引號。', voices[0], 0,
                                            Path(folder) / '測試.wav', threading.Event(), True)
            self.assertGreater(len(audio), rate)
            self.assertGreater(float(np.max(np.abs(audio))), 0.001)


if __name__ == '__main__':
    unittest.main()
