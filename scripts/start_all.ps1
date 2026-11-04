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
    if (-not $elevated) {
        Write-Step '请求已有的高权限启动任务，以完成 NapCat 启动前检查'
        schtasks.exe /Run /TN 'FatFishLife-Start' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "FatFishLife-Start failed: $LASTEXITCODE" }
        return
    }
    $bootExe = Join-Path $NapCatHome 'NapCatWinBootMain.exe'
    # Low-labelled executable files create Low processes even in an elevated task.
    # Restore only this production launcher to normal integrity; keep its DACL/data.
    & icacls.exe $bootExe /setintegritylevel M | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "NapCat integrity label repair failed: $LASTEXITCODE" }
    Write-Step 'NapCat 启动器完整性标记已确认为 Medium'
    $bridgeOnline = $null
    $heartbeatPath = Join-Path $root 'data\dsh\scheduler-heartbeat.json'
    try {
        if (((Get-Date) - (Get-Item -LiteralPath $heartbeatPath -ErrorAction Stop).LastWriteTime).TotalMinutes -lt 2) {
            $heartbeat = Get-Content -LiteralPath $heartbeatPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($heartbeat.transport.online -is [bool]) { $bridgeOnline = $heartbeat.transport.online }
        }
    } catch { Write-Step ('OneBot 状态暂不可读，按未知处理：' + $_.Exception.GetType().Name) }
    $native = @(Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe' OR Name='QQ.exe'")
    $bootstraps = @($native | Where-Object { $_.ExecutablePath -eq $bootExe })
    $ownedIds = @($bootstraps | ForEach-Object { [int]$_.ProcessId })
    do {
        $children = @($native | Where-Object { $_.Name -eq 'QQ.exe' -and $_.ParentProcessId -in $ownedIds -and $_.ProcessId -notin $ownedIds } | ForEach-Object { [int]$_.ProcessId })
        $ownedIds += $children
    } while ($children.Count -gt 0)
    $launch = $bridgeOnline -ne $true
    $recover = $false
    if ($launch -and $bootstraps.Count -gt 0) {
        $oldest = $bootstraps | Sort-Object CreationDate | Select-Object -First 1
        $age = ((Get-Date) - $oldest.CreationDate).TotalMinutes
        if ($age -lt 3) {
            $launch = $false
            Write-Step 'NapCat 仍处于启动宽限期，等待现有实例'
        } elseif ($ownedIds.Count -eq $bootstraps.Count) {
            $recover = $true
        } else {
            $webListening = $null
            try {
                $webConfig = Get-Content -LiteralPath (Join-Path $NapCatHome 'config\webui.json') -Raw | ConvertFrom-Json
                $webPort = [int]$webConfig.port
                if ($webPort -lt 1 -or $webPort -gt 65535) { throw 'Invalid WebUI port' }
                $client = New-Object Net.Sockets.TcpClient
                try { $webListening = $client.ConnectAsync('127.0.0.1', $webPort).Wait(1000) -and $client.Connected }
                catch { $webListening = $false }
                finally { $client.Close() }
            } catch { Write-Step ('NapCat WebUI 配置暂不可读，保留现有实例：' + $_.Exception.GetType().Name) }
            $recover = $bridgeOnline -eq $false -and $webListening -eq $false
            if (-not $recover) {
                $launch = $false
                Write-Step 'NapCat 实例已存在，保留登录/网络状态；未重复启动'
            }
        }
    }
    if ($recover) {
        Write-Step '恢复未完成初始化的 NapCat：仅结束本启动器及其 QQ 子进程'
        [array]::Reverse($ownedIds)
        foreach ($nativeId in $ownedIds) {
            try { Stop-Process -Id $nativeId -Force -ErrorAction Stop } catch {
                if (Get-Process -Id $nativeId -ErrorAction SilentlyContinue) { throw }
            }
        }
        Start-Sleep -Seconds 2
        if (@(Get-Process -Id $ownedIds -ErrorAction SilentlyContinue).Count) { throw 'Old NapCat tree did not exit; duplicate launch cancelled' }
    }
    if ($launch) {
        Write-Step "启动 NapCat（快速登录 $QQNumber）"
        $startArgs = @{ FilePath = 'cmd.exe'; WindowStyle = 'Hidden'; PassThru = $true
            ArgumentList = "/c cd /d `"$NapCatHome`" && launcher.bat $QQNumber" }
        $runLog = Join-Path $logDir ('napcat-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $startArgs.RedirectStandardOutput = $runLog + '.out.log'
        $startArgs.RedirectStandardError = $runLog + '.err.log'
        Write-Step "NapCat 日志：$runLog"
        $boot = Start-Process @startArgs
        if ($boot.WaitForExit(5000)) {
            Write-Step "NapCat 启动器已退出，退出码：$($boot.ExitCode)"
            if ($boot.ExitCode -ne 0) { throw "NapCat launcher failed: $($boot.ExitCode)" }
        } else {
            Write-Step "NapCat 启动器运行中，PID：$($boot.Id)；登录结果由桥状态确认"
        }
    } else {
        if ($bridgeOnline -eq $true) { Write-Step 'NapCat 桥已连接，跳过重复启动' }
    }
} else {
    Write-Step "找不到 NapCat launcher：$launcher"
}

Write-Step "启动流程结束"
