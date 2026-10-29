@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title FatFishLife - NapCat

set "check_only=0"
if /i "%~1"=="--check" set "check_only=1"
if not "%~1"=="" if /i not "%~1"=="--check" goto :usage
if not defined NAPCAT_HOME set "NAPCAT_HOME=D:\Code\Apps\NapCat"

for %%F in (launcher.bat launcher-elevate.ps1 NapCatWinBootMain.exe NapCatWinBootHook.dll loadNapCat.js napcat.mjs qqnt.json) do (
    if not exist "%NAPCAT_HOME%\%%F" (
        set "missing_file=%%F"
        goto :missing
    )
)

echo NapCat directory: "%NAPCAT_HOME%"
echo Bot QQ: 1670515707

rem Inspect only the native launcher; do not terminate QQ or expose its arguments.
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; try { $target=Join-Path $env:NAPCAT_HOME 'NapCatWinBootMain.exe'; $items=@(Get-CimInstance Win32_Process -Filter 'Name=''NapCatWinBootMain.exe'''); if ($items | Where-Object { $_.ExecutablePath -eq $target }) { exit 10 }; if ($items.Count -gt 0) { exit 20 }; exit 0 } catch { exit 20 }"
set "process_check=%ERRORLEVEL%"
if "%process_check%"=="10" goto :running
if not "%process_check%"=="0" goto :unknown
if "%check_only%"=="1" (
    echo [OK] Startup files exist. NapCat is not running. Nothing was launched.
    exit /b 0
)

echo Starting the existing official launcher. Allow Windows elevation if prompted.
echo Keep the NapCat console open after login.
echo This starts NapCat only. Existing OneBot settings and bot services are preserved.
call "%NAPCAT_HOME%\launcher.bat" 1670515707
set "launcher_exit=%ERRORLEVEL%"
if not "%launcher_exit%"=="0" (
    echo [ERROR] Official launcher exited with code %launcher_exit%.
    pause
)
exit /b %launcher_exit%

:running
echo [OK] This NapCat installation is already running. A second copy was not started.
if "%check_only%"=="1" exit /b 0
echo Use its existing console. If replies are missing, check the bot backend connection.
pause
exit /b 0

:unknown
echo [ERROR] Cannot identify the existing NapCat process safely.
echo Right-click this script and select Run as administrator, then retry.
if "%check_only%"=="0" pause
exit /b 2

:missing
echo [ERROR] Missing file: "%NAPCAT_HOME%\%missing_file%"
echo Check NAPCAT_HOME or restore the original NapCat installation.
if "%check_only%"=="0" pause
exit /b 1

:usage
echo Usage: start-napcat.cmd [--check]
echo --check validates startup files and process status without launching anything.
exit /b 2
