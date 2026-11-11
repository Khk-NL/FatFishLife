@echo off
rem Enable Windows Error Reporting LocalDumps for the DSH host process.
rem Crashpad in this build terminates with 0xFFFF7003 ("not connected to handler")
rem and writes no dump, so WER LocalDumps is the only way to capture one.
rem Needs elevation: this script re-launches itself through UAC once.
setlocal
set KEY=HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\DeepSeek Harness.exe
set FOLDER=D:\DSHData\crashdumps

if not "%~1"=="--elevated" (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--elevated' -Verb RunAs"
  exit /b
)

if not exist "%FOLDER%" mkdir "%FOLDER%"
reg add "%KEY%" /v DumpFolder /t REG_EXPAND_SZ /d "%FOLDER%" /f
reg add "%KEY%" /v DumpType /t REG_DWORD /d 1 /f
reg add "%KEY%" /v DumpCount /t REG_DWORD /d 5 /f
echo.
echo Current values:
reg query "%KEY%"
echo.
echo Dump type 1 = mini dump (faulting module + stack, small).
echo To capture full memory later: reg add "%KEY%" /v DumpType /t REG_DWORD /d 2 /f
pause
