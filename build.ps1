# Build a portable Windows folder from this checkout.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required to build.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name VoiceBridge --collect-all edge_tts app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath 'PORTABLE.txt' -Destination 'dist\VoiceBridge\README.txt'
Write-Output 'Portable app: dist\VoiceBridge\VoiceBridge.exe'
