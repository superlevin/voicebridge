# VoiceBridge

Windows 桌面文字轉語音與 MP3 播放器。選擇音訊輸出裝置後，可以透過 VB-CABLE 等虛擬音訊裝置，把語音或音樂送入通話軟體。

## 功能

- 台灣中文、普通話、廣東話、英文、日文等九種線上音色，以及 Windows 已安裝的離線音色。
- 文字轉語音、語速與音量調整、WAV 匯出，預設文字為心經。
- MP3 / WAV 音樂播放、立體聲、播放時間顯示、分段讀取。
- 指定 WASAPI / MME 輸出裝置；`Ctrl+Enter` 送出語音，`Esc` 停止。
- 可打包為不需安裝 Python 的 Windows 可攜資料夾。

文字語音與音樂一次播放一項，不混音。音量在每次開始播放時套用；語速只影響合成語音。停止音樂後再次播放會從頭開始。

## 執行原始碼

環境：Windows 10 / 11 x64、Python 3.12（包含 Tkinter）。在專案目錄執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe app.py
```

`requirements.txt` 列出直接依賴；`requirements.lock.txt` 固定完整開發與打包環境的版本。更新依賴後請重新驗證音訊解碼、合成與 EXE 打包。

## 建置可攜版

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

產物位於 `dist\VoiceBridge\`。複製**整個資料夾**到另一台 Windows 電腦，雙擊 `VoiceBridge.exe` 即可；必須保留 `_internal`。建置完成後也可使用根目錄的 `Launch.cmd` 開啟。

repo 不包含 EXE、虛擬環境、測試產物、音樂檔或第三方驅動安裝包。

## 虛擬麥克風設定

1. 在每台電腦依 [VB-CABLE 官方說明](https://vb-audio.com/Cable/) 安裝驅動，再重新開機。
2. VoiceBridge 輸出裝置選 **CABLE Input**。
3. Discord、LINE、Teams 或其他通話軟體的麥克風選 **CABLE Output**。
4. 通話軟體的喇叭保持實體耳機，先使用麥克風測試確認收音。

訊號方向：文字或音樂 → VoiceBridge → CABLE Input → CABLE Output → 通話軟體。

尚未安裝虛擬驅動時，可以選實體耳機試聽。安裝驅動或重新插拔裝置後，若清單未更新，請重新開啟程式。降噪、輸入靈敏度或按鍵發話設定可能影響合成聲音的接收。

## 檔案結構

```text
app.py                  Tkinter 介面、背景工作與播放狀態
audio_engine.py         語音合成、分段音樂播放、音訊轉換與裝置列舉
edge_compat.py          Edge 線上服務端點相容層
tests/test_engine.py    音訊／取消／重試／離線合成測試
smoke_test.py           網路、音訊裝置與介面的本機整合檢查
check_online.py         九種線上音色的實際合成驗證
build.ps1               建立 Windows 可攜資料夾
PORTABLE.txt            隨可攜版附上的使用說明
```

## 驗證

```powershell
# 不連線；包括真實的 Windows 離線語音測試，其餘輸出以模擬裝置驗證
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 需要網路、Windows 桌面、音訊輸出裝置與至少一個離線音色
# 實際開啟輸出串流，但音量為零；不錄音、不傳送至通話
.\.venv\Scripts\python.exe smoke_test.py

# 以固定測試文字驗證所有線上音色，不播放聲音
.\.venv\Scripts\python.exe check_online.py

# 驗證打包後的程式；報告路径請提供完整路徑
.\dist\VoiceBridge\VoiceBridge.exe --self-test C:\Temp\voicebridge-verification.json
```

整合檢查會在報告中記錄線上服務不可用的情況；只有出現 `online_synthesis_seconds` 才表示線上合成成功。通話對方端的接收情況需另外實測。

## 資料與外部服務

- 線上音色使用 [edge-tts](https://github.com/rany2/edge-tts)，文字會傳至 Microsoft 語音服務；不需要使用者 API Key。
- Windows 離線音色與 MP3 解碼在本機處理；音樂不會上傳。
- 偏好存在 `%LOCALAPPDATA%\VoiceBridge\settings.json`，不保存輸入文字，也不隨資料夾搬移。
- 合成暫存檔在正常完成或停止後清除；異常中斷可能留下系統暫存檔。只有按下匯出才另外保存 WAV。
- 文字上限 2,000 字；完整合成後才開始播放。

## 線上服務相容性

固定版本 `edge-tts 7.2.8` 的舊端點可能回傳 HTTP 403。`edge_compat.py` 將合成連線改到 `api.msedgeservices.com`，保留 TLS 驗證及套件既有的 token 處理。依據：[edge-tts #490](https://github.com/rany2/edge-tts/issues/490)、[Readest 端點修正](https://github.com/readest/readest/commit/6ad1e2c6963b8e587aa96401b455e817fc672f8c)。升級套件後應重新評估是否仍需要相容層。

HTTP 429 會有限次等待重試；其他服務錯誤會顯示給使用者，不會擅自切換音色。

第三方套件、服務與驅動依各自的授權及使用條款提供，詳見 [THIRD_PARTY.md](THIRD_PARTY.md)。
