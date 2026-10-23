param(
    [string]$AstrBotHome = $env:ASTRBOT_HOME,
    [string]$NapCatHome = $env:NAPCAT_HOME,
    [string]$QQNumber = $env:FATFISH_QQ
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $AstrBotHome) { $AstrBotHome = "D:\Code\Apps\AstrBot" }
if (-not $NapCatHome) { $NapCatHome = "D:\Code\Apps\NapCat" }
if (-not $QQNumber) { $QQNumber = "1670515707" }

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Step([string]$text) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$stamp] $text" | Tee-Object -FilePath (Join-Path $logDir "start_all.log") -Append
}

# 1. Local model server. It stays idle (no VRAM) until the offline window.
Write-Step "启动 Ollama"
try {
    & (Join-Path $PSScriptRoot "start_local_model.ps1")
} catch {
    Write-Step "Ollama 启动失败（离线模型不可用，台词库仍可工作）：$_"
}

# 2. AstrBot.
$python = Join-Path $AstrBotHome ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Step "启动 AstrBot"
    Start-Process -FilePath $python -ArgumentList "main.py" -WorkingDirectory $AstrBotHome `
        -RedirectStandardOutput (Join-Path $logDir "astrbot.out.log") `
        -RedirectStandardError (Join-Path $logDir "astrbot.err.log")
} else {
    Write-Step "找不到 AstrBot venv：$python"
}

# 3. Wait for the WebUI port so NapCat does not connect too early.
for ($i = 0; $i -lt 60; $i++) {
    if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 6185 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
        Write-Step "AstrBot 端口已就绪"
        break
    }
    Start-Sleep -Seconds 2
}

# 4. NapCat needs administrator rights for the QQ injection.
$launcher = Join-Path $NapCatHome "launcher.bat"
if (Test-Path $launcher) {
    Write-Step "启动 NapCat（快速登录 $QQNumber）"
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d `"$NapCatHome`" && launcher.bat $QQNumber" `
        -Verb RunAs
} else {
    Write-Step "找不到 NapCat launcher：$launcher"
}

Write-Step "启动流程结束"
