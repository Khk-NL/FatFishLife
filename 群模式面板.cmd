@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8788
echo 群模式面板: http://127.0.0.1:%PORT%/
start "" http://127.0.0.1:%PORT%/
python tools\mode-page\server.py --port %PORT%
