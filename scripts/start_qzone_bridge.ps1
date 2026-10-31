param(
  [switch]$Check,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$bridgeDir = 'D:/Code/tmp-qzone'
$envFile = 'D:/Code/Projects/FatFishLife/outputs/secrets/qzone.env'
$logFile = 'D:/Code/Projects/FatFishLife/outputs/agent/qzone-bridge.log'
$port = 5700

function Test-Port {
  param([int]$Port)
  # 实测：这个桥监听后 Get-NetTCPConnection 不一定列出 Listen（只看到 Closed/TimeWait），
  # 所以用一次真实的 HTTP 请求判断它活着没有。
  try {
    $body = '{}'
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/get_login_info" -Method Post -Body $body -ContentType 'application/json' -Headers @{ Authorization = 'Bearer fatfishqzone20261031' } -TimeoutSec 6 -UseBasicParsing
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
}

if ($Stop) {
  $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($owner in $owners) {
    Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    Write-Output "stopped pid $owner"
  }
  Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*node.exe' } | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -and $cmd -like '*tmp-qzone*src/main.ts*') {
      Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
      Write-Output "stopped bridge pid $($_.Id)"
    }
  }
  exit 0
}

if (Test-Port -Port $port) {
  Write-Output "qzone bridge already listening on $port"
  exit 0
}

if (-not (Test-Path $envFile)) {
  Write-Output "missing $envFile"
  exit 1
}

if ($Check) {
  Write-Output "env file: $envFile"
  Write-Output "bridge dir: $bridgeDir"
  Write-Output "listening: $(Test-Port -Port $port)"
  exit 0
}

$cookieLine = (Get-Content -Path $envFile -Encoding UTF8 | Where-Object { $_ -like 'QZONE_COOKIE_STRING=*' } | Select-Object -First 1)
if (-not $cookieLine) {
  Write-Output "no QZONE_COOKIE_STRING in $envFile"
  exit 1
}
$cookie = $cookieLine.Substring('QZONE_COOKIE_STRING='.Length)

$env:QZONE_COOKIE_STRING = $cookie
$env:ONEBOT_HOST = '127.0.0.1'
$env:ONEBOT_PORT = "$port"
$env:ONEBOT_ACCESS_TOKEN = 'fatfishqzone20261031'
$env:QZONE_CACHE_PATH = './test_cache'
$env:QZONE_ENABLE_QR = '0'

$tsx = Join-Path $bridgeDir 'node_modules/.bin/tsx.cmd'
if (-not (Test-Path $tsx)) {
  Write-Output "missing tsx: $tsx"
  exit 1
}

$proc = Start-Process -FilePath $tsx -ArgumentList 'src/main.ts' -WorkingDirectory $bridgeDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
Write-Output "started qzone bridge pid $($proc.Id)"
Start-Sleep -Seconds 8
Write-Output "listening: $(Test-Port -Port $port)"
