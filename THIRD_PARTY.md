# 第三方元件

本 repo 僅放置應用程式原始碼與依賴清單，不重新散布第三方驅動安裝包。安裝或打包依賴時，請保留它們各自的授權資訊。

| 元件 | 用途 | 上游 |
| --- | --- | --- |
| Python / Tkinter | Windows 桌面介面 | https://www.python.org/ |
| edge-tts | Microsoft Edge 線上語音用戶端 | https://github.com/rany2/edge-tts |
| aiohttp | 非同步網路連線與錯誤處理 | https://github.com/aio-libs/aiohttp |
| python-sounddevice / PortAudio | 指定裝置音訊播放 | https://github.com/spatialaudio/python-sounddevice |
| SoundFile / libsndfile | 音訊解碼、讀寫 MP3 / WAV | https://github.com/bastibe/python-soundfile |
| NumPy | 音訊數值運算 | https://numpy.org/ |
| PyInstaller | Windows 執行檔打包 | https://pyinstaller.org/ |

線上服務相容處理參考 [Readest 的端點遷移修正](https://github.com/readest/readest/commit/6ad1e2c6963b8e587aa96401b455e817fc672f8c) 與 [edge-tts #490](https://github.com/rany2/edge-tts/issues/490)。

VB-CABLE 是 Vincent Burel 的獨立 Donationware 驅動，需由使用者依[官方說明](https://vb-audio.com/Cable/)安裝，其授權不隨本 repo 變更。
