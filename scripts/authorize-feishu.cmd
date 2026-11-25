@echo off
setlocal DisableDelayedExpansion
set "LARKSUITE_CLI_CONFIG_DIR=D:\DSHData\private\feishu-cli"
set "FATFISH_FEISHU_CLI=%~dp0..\.tools\feishu-1.0.100\lark-cli.exe"
set "FATFISH_FEISHU_SCOPES=docx:document:readonly wiki:wiki:readonly base:record:read"

if not exist "%FATFISH_FEISHU_CLI%" (
    echo Feishu CLI 1.0.100 is missing from the FatFishLife .tools directory.
    goto failed
)

if not exist "%LARKSUITE_CLI_CONFIG_DIR%\config.json" (
    "%FATFISH_FEISHU_CLI%" config init
    if errorlevel 1 goto failed
)

"%FATFISH_FEISHU_CLI%" auth check --scope "%FATFISH_FEISHU_SCOPES%" >nul 2>&1
if not errorlevel 1 goto ready

"%FATFISH_FEISHU_CLI%" auth login --scope "%FATFISH_FEISHU_SCOPES%"
if errorlevel 1 goto failed
"%FATFISH_FEISHU_CLI%" auth check --scope "%FATFISH_FEISHU_SCOPES%"
if errorlevel 1 goto failed

:ready
echo Feishu document, wiki and Base record read-only scopes verified.
pause
exit /b 0

:failed
echo Feishu authorization did not finish. Keep credentials on this computer.
pause
exit /b 1
