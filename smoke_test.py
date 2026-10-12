"""Integration check: real network synthesis, silent device output, UI geometry."""
import json
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
    for widget in app.status, app.export, app.send, app.play_music_button, app.choose_music_button:
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    app.music_path = 'selected.mp3'
    app.set_busy(True)
    assert str(app.play_music_button['state']) == 'disabled'
    assert str(app.send['state']) == 'disabled'
    app.set_busy(False)
    assert str(app.play_music_button['state']) == 'normal'
    report['ui'] = 'loaded; controls fit; Windows voices discovered'
    report['virtual_cable_detected'] = any('cable input' in d['name'].lower() for d in available)
    root.destroy()
    return report


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
