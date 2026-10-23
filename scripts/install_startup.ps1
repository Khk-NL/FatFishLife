# Register the FatFishLife boot task with highest privileges (no UAC prompt afterwards).
# Run this file once from an elevated PowerShell.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "start_all.ps1"
$taskName = "FatFishLife-Start"
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""

schtasks.exe /create /tn $taskName /tr $action /sc onlogon /rl highest /f | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "创建计划任务失败，退出码 $LASTEXITCODE"
    exit 1
}

$startupBat = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\start_fatfish.bat"
if (Test-Path $startupBat) {
    Remove-Item $startupBat -Force
    Write-Output "已移除启动文件夹里的重复启动项"
}

Write-Output "已创建开机任务：$taskName（最高权限，登录时自动运行）"
