@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
"%~dp0..\.tools\dsh-python\Scripts\python.exe" "%~dp0install_dsh_wechat.py" %*
set "FATFISH_INSTALL_RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %FATFISH_INSTALL_RESULT%
