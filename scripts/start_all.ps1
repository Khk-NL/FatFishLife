param(
    [string]$AstrBotHome = $env:ASTRBOT_HOME,
    [string]$NapCatHome = $env:NAPCAT_HOME,
    [string]$QQNumber = $env:FATFISH_QQ,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ffmpegBin = Join-Path $root ".tools\ffmpeg\bin"
if (Test-Path (Join-Path $ffmpegBin "ffmpeg.exe")) {
    $env:PATH = "$ffmpegBin;$env:PATH"
}
if (-not $AstrBotHome) { $AstrBotHome = "D:\Code\Apps\AstrBot" }
if (-not $NapCatHome) { $NapCatHome = "D:\Code\Apps\NapCat" }
if (-not $QQNumber) { $QQNumber = "1670515707" }

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Step([string]$text) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$stamp] $text" | Tee-Object -FilePath (Join-Path $logDir "start_all.log") -Append
}

# 0. AstrBot 退役开关（2026-10-29）。
# 迁移到 DSH 期间明确不允许「AstrBot 作为备选」：标记文件存在时，本脚本
# 不再启动 AstrBot、也不再等它的端口。删掉标记文件即恢复旧行为。
# 计划任务 FatFishLife-Start 需要管理员才能停用，这道开关让它在管理员之外也失效。
$retired = Test-Path (Join-Path $root "data\.astrbot-retired")
if ($retired) {
    Write-Step "AstrBot 已退役（data\.astrbot-retired 存在）：跳过启动与端口等待"
}

# 1. Local model server. It stays idle (no VRAM) until the offline window.
if ($DryRun) {
    Write-Step "[dry] would start Ollama"
} else {
    Write-Step "启动 Ollama"
    try {
        & (Join-Path $PSScriptRoot "start_local_model.ps1")
    } catch {
        Write-Step "Ollama 启动失败（离线模型不可用，台词库仍可工作）：$_"
    }
}

# 2. AstrBot. Skip when retired, or when a previous instance already owns the port.
if (-not $retired) {
    $python = Join-Path $AstrBotHome ".venv\Scripts\python.exe"
    $running = Test-NetConnection -ComputerName 127.0.0.1 -Port 6185 -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($running) {
        Write-Step "AstrBot 已在运行，跳过启动"
    } elseif ($DryRun) {
        Write-Step "[dry] would start AstrBot: $python main.py"
    } elseif (Test-Path $python) {
        Write-Step "启动 AstrBot"
        Start-Process -FilePath $python -ArgumentList "main.py" -WorkingDirectory $AstrBotHome `
            -RedirectStandardOutput (Join-Path $logDir "astrbot.out.log") `
            -RedirectStandardError (Join-Path $logDir "astrbot.err.log")
    } else {
        Write-Step "找不到 AstrBot venv：$python"
    }

    # 3. Wait for the WebUI port so NapCat does not connect too early.
    if (-not $DryRun) {
        for ($i = 0; $i -lt 60; $i++) {
            if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 6185 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
                Write-Step "AstrBot 端口已就绪"
                break
            }
            Start-Sleep -Seconds 2
        }
    }
}

# 4. NapCat needs administrator rights for the QQ injection.
$launcher = Join-Path $NapCatHome "launcher.bat"
if ($DryRun) {
    Write-Step "[dry] would start NapCat via $launcher ($QQNumber)"
} elseif (Test-Path $launcher) {
    Write-Step "启动 NapCat（快速登录 $QQNumber）"
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d `"$NapCatHome`" && launcher.bat $QQNumber" `
        -Verb RunAs
} else {
    Write-Step "找不到 NapCat launcher：$launcher"
}

Write-Step "启动流程结束"