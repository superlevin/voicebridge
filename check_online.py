"""Check actual audio from every offered online voice; never plays audio."""
import json
from pathlib import Path
import tempfile
import threading
import time
import numpy as np
from app import ONLINE
from audio_engine import synthesize


def run():
    results = []
    for label, voice in ONLINE.items():
        with tempfile.TemporaryDirectory(prefix='VoiceBridge-check-') as folder:
            try:
                audio, rate = synthesize('你好，這是語音測試。Hello.', voice, 0,
                                         Path(folder) / 'test.mp3', threading.Event())
                assert len(audio) > rate / 2 and np.max(np.abs(audio)) > 0.001
                result = {'voice': voice, 'ok': True, 'seconds': round(len(audio) / rate, 2)}
            except Exception as error:
                result = {'voice': voice, 'ok': False, 'error': str(error)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            time.sleep(2)
    Path('online-verification.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return all(item['ok'] for item in results)


if __name__ == '__main__':
    raise SystemExit(0 if run() else 1)
