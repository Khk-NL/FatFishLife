# AstrBot 守护脚本：6185 不通就拉起来
$ErrorActionPreference = "SilentlyContinue"
$AstrBot = "D:\Code\Apps\AstrBot"
$Python = Join-Path $AstrBot ".venv\Scripts\python.exe"
$Log = Join-Path $AstrBot "astrbot.log"

$listening = Get-NetTCPConnection -LocalPort 6185 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    exit 0
}

# 端口不通，先清掉可能残留的进程，再启动
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $Python } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Start-Process -FilePath $Python `
    -ArgumentList "main.py" `
    -WorkingDirectory $AstrBot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Log `
    -RedirectStandardError "$Log.err"

Add-Content -Path "$AstrBot\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') restarted AstrBot"
