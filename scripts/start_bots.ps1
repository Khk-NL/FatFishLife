# Start AstrBot and NapCat for the FatFishLife bots.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_bots.ps1

$ErrorActionPreference = "Stop"
$AstrBot = "D:\Code\Apps\AstrBot"
$NapCat = "D:\Code\Apps\NapCat"
$QQ = "D:\Q\QQ.exe"

if (-not (Test-Path "$AstrBot\.venv\Scripts\python.exe")) {
    throw "AstrBot venv not found: $AstrBot\.venv"
}
if (-not (Test-Path "$NapCat\NapCatWinBootMain.exe")) {
    throw "NapCat not found: $NapCat"
}
if (-not (Test-Path $QQ)) {
    throw "QQ.exe not found: $QQ"
}

$env:NAPCAT_PATCH_PACKAGE = Join-Path $NapCat "qqnt.json"
$env:NAPCAT_LOAD_PATH = Join-Path $NapCat "loadNapCat.js"
$env:NAPCAT_INJECT_PATH = Join-Path $NapCat "NapCatWinBootHook.dll"
$env:NAPCAT_LAUNCHER_PATH = Join-Path $NapCat "NapCatWinBootMain.exe"
$env:NAPCAT_MAIN_PATH = Join-Path $NapCat "napcat.mjs"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Starting AstrBot on http://127.0.0.1:6185 ..."
Start-Process -FilePath "$AstrBot\.venv\Scripts\python.exe" `
    -ArgumentList "main.py" `
    -WorkingDirectory $AstrBot `
    -WindowStyle Hidden

Start-Sleep -Seconds 8

Write-Host "Starting NapCat (QQ) ..."
Start-Process -FilePath "$NapCat\NapCatWinBootMain.exe" `
    -ArgumentList "`"$QQ`" `"$NapCat\NapCatWinBootHook.dll`"" `
    -WorkingDirectory $NapCat

Write-Host "Done. AstrBot WebUI: http://127.0.0.1:6185"
Write-Host "NapCat WebUI: see its console log or http://127.0.0.1:6099"
