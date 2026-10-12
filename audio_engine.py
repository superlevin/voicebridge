"""Speech synthesis and explicit-device audio playback. No UI dependencies."""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import time

import edge_tts
import aiohttp
import numpy as np
import sounddevice as sd
import soundfile as sf
from edge_compat import configure_endpoint


class Cancelled(Exception):
    pass


def powershell(script, env=None, cancel=None, timeout=60):
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    process = subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW, env=env,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel is not None and cancel.is_set():
            process.kill()
            process.communicate()
            raise Cancelled()
        if time.monotonic() > deadline:
            process.kill()
            process.communicate()
            raise TimeoutError('Windows 語音引擎逾時')
        try:
            out, err = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            pass
    if process.returncode:
        raise RuntimeError(err.decode('utf-8', errors='replace').strip())
    return out.decode('utf-8-sig').strip()


def offline_voices():
    raw = powershell("""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try { @($s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name }) | ConvertTo-Json -Compress } finally { $s.Dispose() }
""")
    result = json.loads(raw or '[]')
    return [result] if isinstance(result, str) else result


def devices():
    hosts = sd.query_hostapis()
    result = []
    for index, device in enumerate(sd.query_devices()):
        host = hosts[device['hostapi']]['name']
        if device['max_output_channels'] > 0 and host in ('Windows WASAPI', 'MME'):
            result.append({'index': index, 'name': device['name'], 'host': host,
                           'label': f"{device['name']}  [{host}]"})
    return sorted(result, key=lambda d: (d['host'] != 'Windows WASAPI', d['index']))


async def save_online(text, voice, rate, path):
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, voice, rate=f'{rate:+d}%').save(str(path))
            return
        except aiohttp.ClientResponseError as error:
            if error.status != 429 or attempt == 2:
                raise
            try:
                delay = float((error.headers or {}).get('Retry-After', 3 * (attempt + 1)))
            except (TypeError, ValueError):
                raise error
            if not 0 <= delay <= 15:
                raise
            await asyncio.sleep(max(1, delay))


async def online_speech(text, voice, rate, path, cancel):
    configure_endpoint()
    job = asyncio.create_task(save_online(text, voice, rate, path))
    try:
        deadline = time.monotonic() + 120
        while not job.done():
            if cancel.is_set():
                raise Cancelled()
            if time.monotonic() > deadline:
                raise TimeoutError('線上語音服務逾時，請檢查網路或改用 Windows 離線音色。')
            await asyncio.sleep(0.1)
        await job
    finally:
        if not job.done():
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                pass


def synthesize(text, voice, rate, path, cancel, offline=False):
    if cancel.is_set():
        raise Cancelled()
    if offline:
        env = os.environ.copy()
        env.update(VB_TEXT=text, VB_VOICE=voice, VB_PATH=str(Path(path).resolve()),
                   VB_RATE=str(max(-10, min(10, round(rate / 10)))))
        powershell("""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
  $s.SelectVoice($env:VB_VOICE)
  $s.Rate=[int]$env:VB_RATE
  $s.SetOutputToWaveFile($env:VB_PATH)
  $s.Speak($env:VB_TEXT)
} finally { $s.Dispose() }
""", env=env, cancel=cancel, timeout=180)
    else:
        try:
            asyncio.run(online_speech(text, voice, rate, path, cancel))
        except (Cancelled, TimeoutError):
            raise
        except Exception as error:
            status = getattr(error, 'status', None)
            if status == 429:
                raise RuntimeError('線上語音服務暫時限制請求次數（HTTP 429）。請稍候再試。') from error
            detail = f'HTTP {status}' if status else type(error).__name__
            raise RuntimeError(f'線上語音服務無法使用（{detail}）。請改選 Windows 離線音色。') from error
    if cancel.is_set():
        raise Cancelled()
    audio, sample_rate = sf.read(path, dtype='float32', always_2d=True)
    if not len(audio):
        raise RuntimeError('語音服務回傳空白音訊。')
    return audio, sample_rate


def convert_audio(audio, source_rate, target_rate, channels, volume):
    if channels == 1:
        audio = audio.mean(axis=1, keepdims=True)
    elif audio.shape[1] == 1:
        audio = np.repeat(audio, channels, axis=1)
    else:
        audio = audio[:, :channels]
    if source_rate != target_rate:
        count = max(1, round(len(audio) * target_rate / source_rate))
        positions = np.arange(count) * source_rate / target_rate
        audio = np.column_stack([np.interp(positions, np.arange(len(audio)), audio[:, c])
                                 for c in range(audio.shape[1])])
    return np.ascontiguousarray(audio * volume, dtype='float32')


def play_file(path, device_index, volume, cancel, progress=None):
    """Decode in bounded chunks; keep stereo and use only the selected output."""
    if cancel.is_set():
        raise Cancelled()
    with sf.SoundFile(path) as source:
        if source.frames == 0:
            raise ValueError('音樂檔沒有可播放的音訊。')
        device = sd.query_devices(device_index, 'output')
        rate = int(device['default_samplerate'])
        channels = min(2, int(device['max_output_channels']))
        with sd.OutputStream(device=device_index, samplerate=rate, channels=channels,
                             dtype='float32', latency='low') as stream:
            while True:
                if cancel.is_set():
                    stream.abort()
                    raise Cancelled()
                audio = source.read(source.samplerate, dtype='float32', always_2d=True)
                if not len(audio):
                    break
                converted = convert_audio(audio, source.samplerate, rate, channels, volume)
                for start in range(0, len(converted), 1024):
                    if cancel.is_set():
                        stream.abort()
                        raise Cancelled()
                    stream.write(converted[start:start + 1024])
                if progress:
                    progress(source.tell() / source.samplerate, source.frames / source.samplerate)


def play(audio, sample_rate, device_index, volume, cancel):
    if cancel.is_set():
        raise Cancelled()
    device = sd.query_devices(device_index, 'output')
    rate = int(device['default_samplerate'])
    channels = min(2, int(device['max_output_channels']))
    converted = convert_audio(audio, sample_rate, rate, channels, volume)
    with sd.OutputStream(device=device_index, samplerate=rate, channels=channels,
                         dtype='float32', latency='low') as stream:
        for start in range(0, len(converted), 1024):
            if cancel.is_set():
                stream.abort()
                raise Cancelled()
            stream.write(converted[start:start + 1024])
