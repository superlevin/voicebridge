"""Integration check: real network synthesis, silent device output, UI geometry."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import numpy as np
import audio_engine as engine
from app import App, ONLINE


def run():
    report = {}
    with tempfile.TemporaryDirectory() as folder:
        try:
            audio, rate = engine.synthesize('你好，這是語音功能測試。', next(iter(ONLINE.values())), 0,
                                            Path(folder) / 'online.mp3', threading.Event())
            assert len(audio) > rate and np.max(np.abs(audio)) > 0.001
            report['online_synthesis_seconds'] = round(len(audio) / rate, 2)
        except RuntimeError as error:
            report['online_service_unavailable'] = str(error)
        audio, rate = engine.synthesize('你好，這是離線測試。', engine.offline_voices()[0], 0,
                                        Path(folder) / 'offline.wav', threading.Event(), True)
        assert len(audio) > rate and np.max(np.abs(audio)) > 0.001
        report['offline_synthesis_seconds'] = round(len(audio) / rate, 2)
    available = engine.devices()
    assert available
    # Open a real output stream, but write only silence.
    engine.play(np.zeros((2400, 1), dtype='float32'), 24000, available[0]['index'], 0, threading.Event())
    report['silent_output_device'] = available[0]['label']
    with tempfile.TemporaryDirectory() as folder:
        music = Path(folder) / 'music.mp3'
        signal = np.sin(2 * np.pi * 440 * np.arange(12000) / 24000).astype('float32') * 0.1
        engine.sf.write(music, np.column_stack([signal, signal * 0.5]), 24000, format='MP3')
        engine.play_file(music, available[0]['index'], 0, threading.Event())
        report['mp3_playback'] = 'real MP3 decoded and streamed at zero volume'
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    for _ in range(50):
        root.update()
        time.sleep(0.1)
    assert len(app.voice_map) > len(ONLINE)
    root.deiconify()
    root.update()
    assert app.text.winfo_height() >= 80
    for widget in app.status, app.export, app.send, app.play_music_button, app.choose_music_button, app.repeat_check, app.monitor_output:
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    app.playlist = ['first.mp3', 'second.mp3']
    app.refresh_playlist()
    app.set_busy(True)
    assert str(app.play_music_button['state']) == 'normal'
    assert str(app.send['state']) == 'disabled'
    app.set_busy(False)
    assert str(app.play_music_button['state']) == 'normal'
    app.music_busy = True
    app.update_controls()
    assert str(app.monitor_output['state']) == 'disabled'
    assert str(app.send['state']) == 'normal'
    assert str(app.output['state']) == 'disabled'
    app.set_busy(True)
    app.events.put(('done', 'Speech finished'))
    app.poll()
    assert app.music_busy and not app.busy
    assert str(app.output['state']) == 'disabled'
    app.events.put(('music_done', 'Music finished'))
    app.poll()
    assert not app.music_busy
    report['playlist_ui'] = 'two tracks; speech/music independent; output locked while either plays'
    # Confirm Windows shared-mode opens two simultaneous streams on the route.
    mix_route = next((d for d in available if 'cable input' in d['name'].lower()), available[0])
    device = engine.sd.query_devices(mix_route['index'], 'output')
    settings = dict(device=mix_route['index'], samplerate=int(device['default_samplerate']),
                    channels=min(2, device['max_output_channels']), dtype='float32')
    with engine.sd.OutputStream(**settings) as music_stream, engine.sd.OutputStream(**settings) as speech_stream:
        silence = np.zeros((1024, settings['channels']), dtype='float32')
        assert music_stream.active and speech_stream.active
        music_stream.write(silence)
        speech_stream.write(silence)
    report['simultaneous_output'] = 'two active shared-device streams verified with silence'
    report['simultaneous_device'] = mix_route['label']
    monitor_route = next((d for d in available if 'cable' not in d['name'].lower()
                          and d['index'] != mix_route['index']), None)
    if monitor_route:
        with tempfile.TemporaryDirectory() as folder:
            music = Path(folder) / 'monitor.mp3'
            engine.sf.write(music, np.zeros((12000, 2)), 24000, format='MP3')
            with ThreadPoolExecutor(max_workers=2) as pool:
                speech = pool.submit(engine.play, np.zeros((12000, 1)), 24000,
                                     mix_route['index'], 0, threading.Event(), monitor_route['index'])
                music_job = pool.submit(engine.play_file, music, mix_route['index'], 0,
                                        threading.Event(), None, monitor_route['index'])
                speech.result(timeout=15)
                music_job.result(timeout=15)
        report['monitoring'] = 'speech and MP3 sent concurrently to primary + monitor at zero volume'
        report['monitor_device'] = monitor_route['label']
    report['ui'] = 'loaded; controls fit; Windows voices discovered'
    report['virtual_cable_detected'] = any('cable input' in d['name'].lower() for d in available)
    root.destroy()
    return report


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
