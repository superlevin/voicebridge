"""Windows desktop UI for speech synthesis and virtual-microphone music output."""
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser

import soundfile as sf
from audio_engine import Cancelled, devices, offline_voices, play, play_file, synthesize

ONLINE = {
    '台灣中文 · 曉臻（女）': 'zh-TW-HsiaoChenNeural',
    '台灣中文 · 曉雨（女）': 'zh-TW-HsiaoYuNeural',
    '台灣中文 · 雲哲（男）': 'zh-TW-YunJheNeural',
    '普通話 · 曉曉（女）': 'zh-CN-XiaoxiaoNeural',
    '普通話 · 雲希（男）': 'zh-CN-YunxiNeural',
    '廣東話 · 曉佳（女）': 'zh-HK-HiuGaaiNeural',
    'English · Jenny（女）': 'en-US-JennyNeural',
    'English · Guy（男）': 'en-US-GuyNeural',
    '日本語 · Nanami（女）': 'ja-JP-NanamiNeural',
}
CONFIG = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VoiceBridge' / 'settings.json'
DEFAULT_TEXT = '''觀自在菩薩。行深般若波羅蜜多時。
照見五蘊皆空。度一切苦厄。
舍利子。色不異空。空不異色。
色即是空。空即是色。
受想行識。亦復如是。
舍利子。是諸法空相。
不生不滅。不垢不淨。不增不減。
是故空中無色。無受想行識。
無眼耳鼻舌身意。無色聲香味觸法。
無眼界。乃至無意識界。
無無明。亦無無明盡。
乃至無老死。亦無老死盡。
無苦集滅道。無智亦無得。以無所得故。
菩提薩埵。依般若波羅蜜多故。
心無罣礙。無罣礙故。無有恐怖。
遠離顛倒夢想。究竟涅槃。
三世諸佛。依般若波羅蜜多故。
得阿耨多羅三藐三菩提。
故知般若波羅蜜多。
是大神咒。是大明咒。
是無上咒。是無等等咒。
能除一切苦。真實不虛。
故說般若波羅蜜多咒。即說咒曰。
揭諦揭諦　波羅揭諦　波羅僧揭諦
菩提薩婆訶。'''


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.music_busy = False
        self.music_cancel = threading.Event()
        self.track_cancel = threading.Event()
        self.playlist = []
        self.last_audio = None
        self.voice_map = {name: (code, False) for name, code in ONLINE.items()}
        self.device_map = {}
        self.settings = self.load_settings()
        self.repeat_event = threading.Event()
        root.title('VoiceBridge｜文字語音麥克風')
        root.geometry('850x760')
        root.minsize(760, 700)
        root.configure(bg='#eef2f7')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Microsoft JhengHei UI', 11))
        style.configure('TFrame', background='#eef2f7')
        style.configure('TLabel', background='#eef2f7', foreground='#203048')
        style.configure('TButton', padding=(12, 9))
        style.configure('Accent.TButton', background='#275be8', foreground='white')
        body = ttk.Frame(root, padding=24)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='VoiceBridge', font=('Segoe UI', 25, 'bold')).pack(anchor='w')
        ttk.Label(body, text='把文字變成聲音，傳進你的通話。').pack(anchor='w', pady=(0, 14))
        ttk.Label(body, text='1  選音色與輸出裝置     →     2  輸入文字     →     3  送出語音').pack(anchor='w')
        ttk.Label(body, text='音色（線上音色需網路；文字會傳送至 Microsoft 語音服務）').pack(anchor='w', pady=(14, 5))
        self.voice = ttk.Combobox(body, state='readonly', values=list(self.voice_map))
        self.voice.pack(fill='x')
        self.voice.set(next(iter(ONLINE)))
        self.voice.bind('<<ComboboxSelected>>', lambda _: self.save_settings())
        ttk.Label(body, text='音訊輸出裝置｜要傳給對方，請選 CABLE Input 或你的虛擬音訊輸入端').pack(anchor='w', pady=(12, 5))
        row = ttk.Frame(body)
        row.pack(fill='x')
        self.output = ttk.Combobox(row, state='readonly')
        self.output.pack(side='left', fill='x', expand=True)
        self.output.bind('<<ComboboxSelected>>', lambda _: self.save_settings())
        self.refresh_button = ttk.Button(row, text='重新整理', command=self.refresh)
        self.refresh_button.pack(side='right', padx=(8, 0))
        self.route = ttk.Label(body, text='', wraplength=770)
        self.route.pack(anchor='w', pady=(6, 10))
        monitor_row = ttk.Frame(body)
        monitor_row.pack(fill='x', pady=(0, 8))
        self.monitor_enabled = tk.BooleanVar(value=self.settings.get('monitor_enabled', False) is True)
        self.monitor_check = ttk.Checkbutton(monitor_row, text='監聽（選耳機／喇叭）',
                                            variable=self.monitor_enabled, command=self.save_settings)
        self.monitor_check.pack(side='left')
        self.monitor_output = ttk.Combobox(monitor_row, state='readonly')
        self.monitor_output.pack(side='left', fill='x', expand=True, padx=(8, 0))
        self.monitor_output.bind('<<ComboboxSelected>>', lambda _: self.save_settings())
        controls = ttk.Frame(body)
        controls.pack(fill='x')
        ttk.Label(controls, text='語速 %').pack(side='left')
        self.rate = tk.IntVar(value=self.setting_number('rate', 0, -50, 100))
        ttk.Spinbox(controls, from_=-50, to=100, textvariable=self.rate, width=6).pack(side='left', padx=(8, 22))
        ttk.Label(controls, text='語音音量 %').pack(side='left')
        self.volume = tk.IntVar(value=self.setting_number('volume', 80, 0, 100))
        ttk.Spinbox(controls, from_=0, to=100, textvariable=self.volume, width=6).pack(side='left', padx=8)
        ttk.Label(controls, text='音樂音量 %').pack(side='left', padx=(16, 0))
        self.music_volume = tk.IntVar(value=self.setting_number('music_volume', 30, 0, 100))
        ttk.Spinbox(controls, from_=0, to=100, textvariable=self.music_volume, width=6).pack(side='left', padx=8)
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True, pady=(12, 0))
        text_frame = ttk.Frame(self.tabs)
        self.tabs.add(text_frame, text='文字語音（最多 2,000 字）')
        music_frame = ttk.Frame(self.tabs)
        self.tabs.add(music_frame, text='音樂播放清單')
        self.playlist_box = tk.Listbox(music_frame, selectmode='extended', exportselection=False,
                                      font=('Microsoft JhengHei UI', 12), height=7)
        self.playlist_box.pack(side='left', fill='both', expand=True)
        playlist_scroll = ttk.Scrollbar(music_frame, command=self.playlist_box.yview)
        playlist_scroll.pack(side='right', fill='y')
        self.playlist_box.configure(yscrollcommand=playlist_scroll.set)
        self.text = tk.Text(text_frame, wrap='word', font=('Microsoft JhengHei UI', 14),
                            height=7, relief='flat', padx=14, pady=12, undo=True)
        self.text.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(text_frame, command=self.text.yview)
        scrollbar.pack(side='right', fill='y')
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.insert('1.0', DEFAULT_TEXT)
        root.bind('<Control-Return>', lambda _: self.start())
        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=12)
        self.send = ttk.Button(buttons, text='▶  送出語音  Ctrl+Enter', style='Accent.TButton', command=self.start)
        self.send.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='■ 停止語音', command=self.stop_speech, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.export = ttk.Button(buttons, text='儲存上一段 WAV', command=self.save_audio, state='disabled')
        self.export.pack(side='right')
        music = ttk.Frame(body)
        music.pack(fill='x', pady=(0, 10))
        self.choose_music_button = ttk.Button(music, text='加入多首 MP3', command=self.choose_music)
        self.choose_music_button.pack(side='left')
        self.play_music_button = ttk.Button(music, text='▶ 播放音樂', command=self.start_music, state='disabled')
        self.play_music_button.pack(side='left', padx=8)
        self.music_stop_button = ttk.Button(music, text='■ 停止音樂', command=self.stop_music, state='disabled')
        self.music_stop_button.pack(side='left')
        self.next_button = ttk.Button(music, text='下一首', command=self.next_track, state='disabled')
        self.next_button.pack(side='left', padx=8)
        self.remove_button = ttk.Button(music, text='移除選取', command=self.remove_music)
        self.remove_button.pack(side='left')
        self.repeat = tk.BooleanVar(value=self.settings.get('repeat', False) is True)
        if self.repeat.get():
            self.repeat_event.set()
        self.repeat_check = ttk.Checkbutton(music, text='清單循環', variable=self.repeat,
                                           command=self.change_repeat)
        self.repeat_check.pack(side='left', padx=(8, 0))
        self.music_status = ttk.Label(body, text='可一次加入多首音樂，依序播放；播放中仍可送出語音。Esc 停止全部。', wraplength=760)
        self.music_status.pack(anchor='w', pady=(0, 6))
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.progress.pack(fill='x')
        self.status = ttk.Label(body, text='正在載入音訊裝置與離線音色…', wraplength=760)
        self.status.pack(anchor='w', pady=(8, 10))
        ttk.Label(body, text='通話軟體設定：麥克風選 CABLE Output，喇叭選原本的耳機。\n第一次使用請先在通話軟體的麥克風測試中確認有聲音。', wraplength=760).pack(anchor='w')
        ttk.Button(body, text='開啟 VB-CABLE 官方下載頁', command=lambda: webbrowser.open('https://vb-audio.com/Cable/')).pack(anchor='w', pady=(8, 0))
        root.bind('<Escape>', lambda _: self.stop())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        threading.Thread(target=self.load_voices, daemon=True).start()
        root.after(80, self.poll)

    def load_settings(self):
        try:
            value = json.loads(CONFIG.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def setting_number(self, name, default, low, high):
        try:
            return max(low, min(high, int(self.settings.get(name, default))))
        except (TypeError, ValueError):
            return default

    def save_settings(self):
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps({'voice': self.voice.get(), 'device': self.output.get(),
                                           'rate': self.rate.get(), 'volume': self.volume.get(),
                                           'music_volume': self.music_volume.get(),
                                           'repeat': self.repeat.get(),
                                           'monitor_enabled': self.monitor_enabled.get(),
                                           'monitor_device': self.monitor_output.get()}, ensure_ascii=False), encoding='utf-8')
        except (OSError, tk.TclError):
            pass

    def refresh(self):
        try:
            current = self.output.get() or self.settings.get('device')
            available = devices()
            self.device_map = {d['label']: d['index'] for d in available}
            self.output.configure(values=list(self.device_map))
            current_monitor = self.monitor_output.get() or self.settings.get('monitor_device')
            monitor_labels = [d['label'] for d in available if 'cable' not in d['name'].lower()]
            self.monitor_output.configure(values=monitor_labels)
            self.monitor_output.set(current_monitor if current_monitor in monitor_labels else '')
            cables = [d['label'] for d in available if 'cable input' in d['name'].lower()]
            # Never choose a physical speaker implicitly.
            self.output.set(current if current in self.device_map else (cables[0] if cables else ''))
            self.route.configure(text='已偵測到 CABLE。請確認下拉選單選的是你要使用的裝置。' if cables else '未偵測到 CABLE Input。可先選耳機試聽；傳入通話需安裝虛擬音訊驅動。')
        except Exception as error:
            self.status.configure(text=f'無法列出音訊裝置：{error}')

    def load_voices(self):
        try:
            self.events.put(('voices', offline_voices()))
        except Exception as error:
            self.events.put(('voice_error', str(error)))

    def change_repeat(self):
        if self.repeat.get():
            self.repeat_event.set()
        else:
            self.repeat_event.clear()
        self.save_settings()

    def get_monitor_index(self):
        if not self.monitor_enabled.get():
            return None
        label = self.monitor_output.get()
        if label not in self.device_map:
            raise ValueError('請先選擇監聽耳機／喇叭，或取消勾選監聽。')
        if label.split('  [')[0] == self.output.get().split('  [')[0]:
            raise ValueError('監聽裝置請選不同於主要輸出的耳機／喇叭。')
        return self.device_map[label]

    def start(self):
        if self.busy:
            return
        text = self.text.get('1.0', 'end-1c').strip()
        if not text or len(text) > 2000:
            messagebox.showinfo('文字長度', '請輸入 1～2,000 字。')
            return
        if self.output.get() not in self.device_map:
            messagebox.showinfo('選擇輸出', '請先選擇語音輸出裝置。選耳機可試聽；選 CABLE Input 可傳入虛擬麥克風。')
            return
        try:
            rate, volume = self.rate.get(), self.volume.get()
            if not -50 <= rate <= 100 or not 0 <= volume <= 100:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showinfo('數值範圍', '語速須為 -50～100，音量須為 0～100 的整數。')
            return
        voice, offline = self.voice_map[self.voice.get()]
        device = self.device_map[self.output.get()]
        try:
            monitor = self.get_monitor_index()
        except ValueError as error:
            messagebox.showinfo('監聽設定', str(error))
            return
        self.save_settings()
        self.cancel = threading.Event()
        self.set_busy(True)
        self.status.configure(text='正在產生語音…')
        threading.Thread(target=self.worker, args=(text, voice, offline, rate, volume / 100, device, self.cancel, monitor), daemon=True).start()

    def worker(self, text, voice, offline, rate, volume, device, cancel, monitor=None):
        try:
            with tempfile.TemporaryDirectory(prefix='VoiceBridge-') as folder:
                path = Path(folder) / ('speech.wav' if offline else 'speech.mp3')
                audio, sample_rate = synthesize(text, voice, rate, path, cancel, offline)
            self.events.put(('audio', (audio, sample_rate)))
            self.events.put(('status', '正在輸出語音…'))
            play(audio, sample_rate, device, volume, cancel, monitor_index=monitor)
            self.events.put(('done', '語音已輸出完成。'))
        except Cancelled:
            self.events.put(('done', '已停止。'))
        except Exception as error:
            self.events.put(('error', f'{error}\n\n線上音色失敗時可改用 Windows 離線音色。裝置錯誤時請重新整理並重選輸出。'))

    def choose_music(self):
        if self.music_busy:
            return
        paths = filedialog.askopenfilenames(title='加入音樂（可用 Ctrl / Shift 多選）',
                                           filetypes=[('音樂檔', '*.mp3 *.wav')])
        if paths:
            self.playlist.extend(paths)
            self.refresh_playlist()
            self.tabs.select(1)

    def refresh_playlist(self):
        self.playlist_box.delete(0, 'end')
        for index, path in enumerate(self.playlist):
            self.playlist_box.insert('end', f'{index + 1}. {Path(path).name}')
        self.update_controls()

    def remove_music(self):
        if self.music_busy:
            return
        for index in reversed(self.playlist_box.curselection()):
            del self.playlist[index]
        self.refresh_playlist()

    def start_music(self):
        if self.music_busy or not self.playlist:
            return
        if self.output.get() not in self.device_map:
            messagebox.showinfo('選擇輸出', '請先選擇音訊輸出裝置。')
            return
        try:
            volume = self.music_volume.get()
            if not 0 <= volume <= 100:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showinfo('音量範圍', '音量須為 0～100 的整數。')
            return
        try:
            monitor = self.get_monitor_index()
        except ValueError as error:
            messagebox.showinfo('監聽設定', str(error))
            return
        self.save_settings()
        self.music_cancel = threading.Event()
        self.track_cancel = threading.Event()
        self.music_busy = True
        self.update_controls()
        self.music_status.configure(text='正在開啟播放清單…')
        threading.Thread(target=self.music_worker,
                         args=(list(self.playlist), self.device_map[self.output.get()], volume / 100,
                               self.music_cancel, self.repeat_event, monitor),
                         daemon=True).start()

    def music_worker(self, playlist, device, volume, cancel, repeat=None, monitor=None):
        failures = {}
        index = 0
        playable = False
        while playlist:
            if cancel.is_set():
                break
            path = playlist[index]
            track_cancel = self.track_cancel
            title = f'{index + 1}/{len(playlist)} {Path(path).name}'
            self.events.put(('music_track', index))
            self.events.put(('music_status', f'正在播放 {title}'))
            def progress(elapsed, duration, title=title):
                def timestamp(seconds):
                    return f'{int(seconds) // 60:02d}:{int(seconds) % 60:02d}'
                self.events.put(('music_status', f'{title}  {timestamp(elapsed)} / {timestamp(duration)}'))
            try:
                play_file(path, device, volume, track_cancel, progress, monitor_index=monitor)
                playable = True
                failures.pop(index, None)
            except Cancelled:
                playable = True
            except Exception as error:
                failures[index] = f'{Path(path).name}: {error}'
            finally:
                self.track_cancel = threading.Event()
            index += 1
            if index == len(playlist):
                # Stop if every file failed; avoid endlessly retrying a bad list.
                if repeat is None or not repeat.is_set() or not playable:
                    break
                index = 0
                playable = False
        result = '音樂已停止。' if cancel.is_set() else '播放清單已播放完成。'
        if failures:
            result += f' {len(failures)} 首失敗。'
            self.events.put(('music_errors', '\n'.join(failures.values())[:1500]))
        self.events.put(('music_done', result))

    def stop_music(self):
        if self.music_busy:
            self.music_cancel.set()
            self.track_cancel.set()
            self.music_status.configure(text='正在停止音樂…')

    def next_track(self):
        if self.music_busy:
            self.track_cancel.set()

    def set_busy(self, busy):
        self.busy = busy
        self.update_controls()

    def update_controls(self):
        active = self.busy or self.music_busy
        self.send.configure(state='disabled' if self.busy else 'normal')
        self.choose_music_button.configure(state='disabled' if self.music_busy else 'normal')
        self.remove_button.configure(state='disabled' if self.music_busy else 'normal')
        self.play_music_button.configure(state='normal' if not self.music_busy and self.playlist else 'disabled')
        self.music_stop_button.configure(state='normal' if self.music_busy else 'disabled')
        self.next_button.configure(state='normal' if self.music_busy else 'disabled')
        self.refresh_button.configure(state='disabled' if active else 'normal')
        self.output.configure(state='disabled' if active else 'readonly')
        self.monitor_check.configure(state='disabled' if active else 'normal')
        self.monitor_output.configure(state='disabled' if active else 'readonly')
        self.voice.configure(state='disabled' if self.busy else 'readonly')
        self.stop_button.configure(state='normal' if self.busy else 'disabled')
        if self.busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'voices':
                    for name in value:
                        self.voice_map[f'Windows 離線 · {name}'] = (name, True)
                    self.voice.configure(values=list(self.voice_map))
                    if not self.busy and self.settings.get('voice') in self.voice_map:
                        self.voice.set(self.settings['voice'])
                    elif not self.busy and value and not self.settings.get('voice'):
                        self.voice.set(f'Windows 離線 · {value[0]}')
                    if not self.busy:
                        self.status.configure(text='就緒。選擇輸出裝置後即可送出。')
                elif kind == 'voice_error':
                    if not self.busy:
                        self.status.configure(text='離線音色無法載入，仍可使用線上音色。')
                elif kind == 'audio':
                    self.last_audio = value
                    self.export.configure(state='normal')
                elif kind == 'status':
                    self.status.configure(text=value)
                elif kind == 'music_status':
                    self.music_status.configure(text=value)
                elif kind == 'music_track':
                    self.playlist_box.selection_clear(0, 'end')
                    self.playlist_box.selection_set(value)
                    self.playlist_box.see(value)
                elif kind == 'music_done':
                    self.music_busy = False
                    self.update_controls()
                    self.music_status.configure(text=value)
                elif kind == 'music_errors':
                    messagebox.showerror('部分音樂無法播放', value)
                elif kind in ('done', 'error'):
                    self.set_busy(False)
                    self.status.configure(text=value if kind == 'done' else '輸出失敗，請查看錯誤訊息。')
                    if kind == 'error':
                        messagebox.showerror('音訊輸出失敗', value)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def stop_speech(self):
        if self.busy:
            self.cancel.set()
            self.status.configure(text='正在停止…')

    def stop(self):
        self.stop_speech()
        self.stop_music()

    def save_audio(self):
        if self.last_audio is None:
            return
        path = filedialog.asksaveasfilename(defaultextension='.wav', filetypes=[('WAV 音訊', '*.wav')], initialfile='VoiceBridge.wav')
        if path:
            try:
                sf.write(path, *self.last_audio, subtype='PCM_16')
            except Exception as error:
                messagebox.showerror('儲存失敗', str(error))

    def close(self):
        self.stop()
        self.save_settings()
        self.root.withdraw()
        self.wait_close()

    def wait_close(self):
        if self.busy or self.music_busy:
            self.root.after(100, self.wait_close)
        else:
            self.root.destroy()


if __name__ == '__main__':
    import sys
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        import traceback
        try:
            from smoke_test import run
            report = run()
            Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            Path(sys.argv[2]).write_text(traceback.format_exc(), encoding='utf-8')
            sys.exit(1)
        sys.exit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
