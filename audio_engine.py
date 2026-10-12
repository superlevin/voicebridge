"""Speech synthesis and explicit-device audio playback. No UI dependencies."""
import asyncio
from contextlib import contextmanager, ExitStack
import base64
import json
import os
from pathlib import Path
import subprocess
import threading
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


@contextmanager
def output_routes(device_index, monitor_index=None):
    """Open primary and optional local-monitor outputs; never use default audio."""
    indices = [device_index]
    if monitor_index is not None and monitor_index != device_index:
        indices.append(monitor_index)
    with ExitStack() as stack:
        routes = []
        for index in indices:
            device = sd.query_devices(index, 'output')
            rate = int(device['default_samplerate'])
            channels = min(2, int(device['max_output_channels']))
            stream = stack.enter_context(sd.OutputStream(device=index, samplerate=rate,
                                         channels=channels, dtype='float32', latency='low'))
            routes.append((stream, rate, channels))
        yield routes


def write_routes(audio, sample_rate, volume, cancel, routes):
    # Process at most a second at a time. Slice both device rates at the same
    # 20 ms time boundaries so monitoring does not lag a whole audio block.
    converted = [(stream, rate, convert_audio(audio, sample_rate, rate, channels, volume))
                 for stream, rate, channels in routes]
    steps = int(np.ceil(len(audio) * 50 / sample_rate))
    for step in range(steps):
        if cancel.is_set():
            for stream, _, _ in routes:
                stream.abort()
            raise Cancelled()
        for stream, rate, data in converted:
            block = data[round(step * rate / 50):round((step + 1) * rate / 50)]
            if len(block):
                stream.write(block)


MIX_RATE = 48000
MIX_FRAMES = 960  # 20 ms; one shared timeline for speech and music.


def audio_blocks(chunks, sample_rate, volume):
    """Convert bounded, one-second source chunks into stereo mixer blocks."""
    for chunk in chunks:
        converted = convert_audio(chunk, sample_rate, MIX_RATE, 2, volume)
        for start in range(0, len(converted), MIX_FRAMES):
            yield converted[start:start + MIX_FRAMES]


def mix_blocks(blocks):
    mixed = np.zeros((max(len(block) for block in blocks), 2), dtype='float32')
    for block in blocks:
        mixed[:len(block)] += block
    return np.clip(mixed, -1, 1)


class MixerJob:
    def __init__(self, blocks, cancel, progress, duration):
        self.blocks = iter(blocks)
        self.cancel = cancel
        self.progress = progress
        self.duration = duration
        self.frames = 0
        self.done = threading.Event()
        self.error = None


class AudioMixer:
    """Single owner of output streams. Adding/stopping a lane never replaces another."""
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = []
        self.running = False
        self.route_key = None

    def play(self, blocks, device_index, monitor_index, cancel, progress=None, duration=0):
        if cancel.is_set():
            raise Cancelled()
        job = MixerJob(blocks, cancel, progress, duration)
        key = (device_index, monitor_index)
        with self.lock:
            if self.running and self.route_key != key:
                raise RuntimeError('播放中不可切換音訊輸出或監聽裝置。')
            self.jobs.append(job)
            if not self.running:
                self.route_key = key
                self.running = True
                threading.Thread(target=self._run, args=key, daemon=True).start()
        job.done.wait()
        if job.error is not None:
            raise job.error

    def _finish(self, job, error=None):
        self.jobs.remove(job)
        job.error = error

    def _run(self, device_index, monitor_index):
        stack = ExitStack()
        finished = []
        try:
            routes = stack.enter_context(output_routes(device_index, monitor_index))
            while True:
                # Serialize stream lifecycle with submissions so a newly submitted
                # voice cannot get stranded during the last music block's cleanup.
                with self.lock:
                    blocks = []
                    active = []
                    finished = []
                    for job in list(self.jobs):
                        if job.cancel.is_set():
                            self._finish(job, Cancelled())
                            finished.append(job)
                            continue
                        try:
                            block = next(job.blocks)
                        except StopIteration:
                            self._finish(job)
                            finished.append(job)
                            continue
                        except Exception as error:
                            self._finish(job, error)
                            finished.append(job)
                            continue
                        blocks.append(block)
                        active.append((job, len(block)))
                    if not self.jobs:
                        if any(isinstance(job.error, Cancelled) for job in finished):
                            for stream, _, _ in routes:
                                stream.abort()
                        stack.close()
                        self.running = False
                        for job in finished:
                            job.done.set()
                        return
                    for job in finished:
                        job.done.set()
                if blocks:
                    # Never hold the submission lock during blocking device writes:
                    # a newly synthesized voice must join the very next music block.
                    write_routes(mix_blocks(blocks), MIX_RATE, 1, threading.Event(), routes)
                    for job, count in active:
                        previous = job.frames
                        job.frames += count
                        if job.progress and (previous // 9600 != job.frames // 9600
                                             or job.frames / MIX_RATE >= job.duration):
                            job.progress(min(job.frames / MIX_RATE, job.duration), job.duration)
                time.sleep(0)  # Let new lane submissions acquire the lock.
        except Exception as error:
            with self.lock:
                try:
                    stack.close()
                except Exception:
                    pass
                for job in list(self.jobs):
                    self._finish(job, error)
                    job.done.set()
                for job in finished:
                    job.done.set()
                self.running = False


_mixer = AudioMixer()


def play_file(path, device_index, volume, cancel, progress=None, monitor_index=None):
    if cancel.is_set():
        raise Cancelled()
    with sf.SoundFile(path) as source:
        if source.frames == 0:
            raise ValueError('音樂檔沒有可播放的音訊。')
        def chunks():
            while True:
                chunk = source.read(source.samplerate, dtype='float32', always_2d=True)
                if not len(chunk):
                    break
                yield chunk
        _mixer.play(audio_blocks(chunks(), source.samplerate, volume), device_index,
                    monitor_index, cancel, progress, source.frames / source.samplerate)


def play(audio, sample_rate, device_index, volume, cancel, monitor_index=None):
    chunks = (audio[start:start + sample_rate] for start in range(0, len(audio), sample_rate))
    _mixer.play(audio_blocks(chunks, sample_rate, volume), device_index, monitor_index, cancel)
