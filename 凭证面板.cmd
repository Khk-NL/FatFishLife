@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8787
echo Starting credential panel on http://127.0.0.1:%PORT%/
python tools\credential-page\server.py --port %PORT%
