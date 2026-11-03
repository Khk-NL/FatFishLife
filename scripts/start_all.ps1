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
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    # A surviving bootstrap without any QQ process is not a healthy instance.
    # This task already runs elevated; only stop our own orphaned launcher.
    if ($elevated -and @(Get-Process -Name QQ -ErrorAction SilentlyContinue).Count -eq 0) {
        $bootExe = Join-Path $NapCatHome 'NapCatWinBootMain.exe'
        $orphans = @(Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe'" |
            Where-Object { $_.ExecutablePath -eq $bootExe })
        foreach ($orphan in $orphans) {
            try { Stop-Process -Id $orphan.ProcessId -Force -ErrorAction Stop } catch {
                if (Get-Process -Id $orphan.ProcessId -ErrorAction SilentlyContinue) { throw }
            }
        }
    }
    Write-Step "启动 NapCat（快速登录 $QQNumber）"
    $startArgs = @{ FilePath = 'cmd.exe'; WindowStyle = 'Hidden'; PassThru = $true
        ArgumentList = "/c cd /d `"$NapCatHome`" && launcher.bat $QQNumber" }
    if ($elevated) {
        $runLog = Join-Path $logDir ('napcat-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $startArgs.RedirectStandardOutput = $runLog + '.out.log'
        $startArgs.RedirectStandardError = $runLog + '.err.log'
        Write-Step "NapCat 日志：$runLog"
    } else {
        $startArgs.Verb = 'RunAs'
    }
    $boot = Start-Process @startArgs
    if (-not $elevated) {
        Write-Step 'NapCat 管理员启动已请求；通过桥状态确认登录结果'
    } elseif ($boot.WaitForExit(5000)) {
        Write-Step "NapCat 启动器已退出，退出码：$($boot.ExitCode)"
        if ($boot.ExitCode -ne 0) { throw "NapCat launcher failed: $($boot.ExitCode)" }
    } else {
        Write-Step "NapCat 启动器运行中，PID：$($boot.Id)；登录结果由桥状态确认"
    }
} else {
    Write-Step "找不到 NapCat launcher：$launcher"
}

Write-Step "启动流程结束"
