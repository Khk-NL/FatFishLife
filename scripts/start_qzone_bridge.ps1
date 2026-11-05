param(
  [switch]$Check,
  [switch]$Stop,
  [string]$QQPauseMarker = 'D:/Code/Projects/FatFishLife/data/.qq-account-paused',
  [uri]$Base = 'http://127.0.0.1:5700',
  [string]$BridgeDir = 'D:/Code/tmp-qzone',
  [string]$EnvFile = 'D:/Code/Projects/FatFishLife/outputs/secrets/qzone.env',
  [string]$LogFile = 'D:/Code/Projects/FatFishLife/outputs/agent/qzone-bridge.log'
)

$ErrorActionPreference = 'Stop'
# Stop remains available; paused starts/checks do not load secrets or probe QQ.
if (-not $Stop -and (Test-Path -LiteralPath $QQPauseMarker)) {
  Write-Output 'qqPaused=True; qzone start and probe skipped'
  exit 3
}
if ($Base.Scheme -ne 'http' -or -not $Base.IsLoopback -or $Base.AbsolutePath -ne '/' -or $Base.Query -or $Base.Fragment -or $Base.UserInfo) {
  Write-Output 'expected a loopback HTTP base with no path or credentials'
  exit 1
}
$port = $Base.Port
$bindHost = if ($Base.DnsSafeHost -eq 'localhost') { '127.0.0.1' } else { $Base.DnsSafeHost.Trim('[', ']') }
$baseUrl = $Base.GetLeftPart([UriPartial]::Authority)
function Test-Port {
  param([int]$Port)
  if (Test-Path -LiteralPath $QQPauseMarker) { return $false }
  # 实测：这个桥监听后 Get-NetTCPConnection 不一定列出 Listen（只看到 Closed/TimeWait），
  # 所以用一次真实的 HTTP 请求判断它活着没有。
  $script:loginValid = $false
  try {
    $body = '{}'
    $cookieResp = Invoke-WebRequest -Uri ($baseUrl + '/check_cookie') -Method Post -Body $body -ContentType 'application/json' -Headers @{ Authorization = ('Bearer ' + $accessToken) } -TimeoutSec 6 -UseBasicParsing
    $cookieData = $cookieResp.Content | ConvertFrom-Json -ErrorAction Stop
    $online = ($cookieResp.StatusCode -eq 200 -and $cookieData.status -eq 'ok' -and
      ($null -eq $cookieData.retcode -or $cookieData.retcode -eq 0) -and $cookieData.data.valid -is [bool])
    if (-not $online) { return $false }
    $script:loginValid = $cookieData.data.valid
    # Expired cookies can make get_login_info fail while the authenticated bridge
    # is alive. Preserve that distinction instead of trying to start another copy.
    if (-not $script:loginValid) { return $true }
    $resp = Invoke-WebRequest -Uri ($baseUrl + '/get_login_info') -Method Post -Body $body -ContentType 'application/json' -Headers @{ Authorization = ('Bearer ' + $accessToken) } -TimeoutSec 6 -UseBasicParsing
    $data = $resp.Content | ConvertFrom-Json -ErrorAction Stop
    return ($resp.StatusCode -eq 200 -and $data.status -eq 'ok' -and
      ($null -eq $data.retcode -or $data.retcode -eq 0) -and $data.data.user_id)
  } catch {
    return $false
  }
}

function Test-BridgeProcess([string]$CommandLine, [string]$Directory) {
  if (-not $CommandLine) { return $false }
  $root = [IO.Path]::GetFullPath($Directory).Replace('\', '/').TrimEnd('/')
  $command = $CommandLine.Replace('\', '/')
  $boundary = '(?:^|[\s"''])'
  $end = '(?:$|[\s"''])'
  $ownsPath = $command -match ($boundary + [regex]::Escape($root) + '/')
  $entry = $command -match ($boundary + '(?:' + [regex]::Escape($root) + '/)?src/main[.]ts' + $end)
  return ($ownsPath -and $entry)
}

if ($Stop) {
  # Port ownership alone is insufficient: it may belong to an unrelated service.
  # Unreadable command lines are deliberately left alone.
  Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*node.exe' } | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if (Test-BridgeProcess $cmd $BridgeDir) {
      Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
      Write-Output "stopped bridge pid $($_.Id)"
    }
  }
  exit 0
}

$accessToken = ''
if (Test-Path -LiteralPath $envFile) {
  $tokenLine = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -like 'FATFISH_QZONE_ACCESS_TOKEN=*' } | Select-Object -First 1
  if ($tokenLine) { $accessToken = $tokenLine.Substring('FATFISH_QZONE_ACCESS_TOKEN='.Length).Trim() }
}

if (-not (Test-Path $envFile)) {
  Write-Output "missing $envFile"
  exit 1
}

if (-not $accessToken) { Write-Output 'missing FATFISH_QZONE_ACCESS_TOKEN in local secrets file'; exit 1 }

$ready = Test-Port -Port $port
if ($Check) {
  Write-Output "env file: $envFile"
  Write-Output "bridge dir: $bridgeDir"
  Write-Output "listening: $ready"
  if ($ready -and -not $script:loginValid) { Write-Output 'bridge online; login is invalid'; exit 2 }
  if ($ready) { exit 0 }
  exit 1
}

if ($ready) {
  Write-Output "qzone bridge already listening on $port"
  if (-not $script:loginValid) { Write-Output 'bridge online; login is invalid'; exit 2 }
  exit 0
}

# A bad HTTP response may be a hung bridge or a different server. Never launch
# another process on the same address/port or kill the existing listener.
$tcp = New-Object System.Net.Sockets.TcpClient
try {
  $pending = $tcp.BeginConnect($bindHost, $port, $null, $null)
  if ($pending.AsyncWaitHandle.WaitOne(1500, $false) -and $tcp.Connected) {
    Write-Output "port $port is occupied but bridge health failed; duplicate start refused"
    exit 1
  }
} catch { } finally { $tcp.Close() }

if (-not (Test-Path -LiteralPath $bridgeDir)) {
  Write-Output "missing bridge directory: $bridgeDir"
  exit 1
}

$cookieLine = (Get-Content -Path $envFile -Encoding UTF8 | Where-Object { $_ -like 'QZONE_COOKIE_STRING=*' } | Select-Object -First 1)
if (-not $cookieLine) {
  Write-Output "no QZONE_COOKIE_STRING in $envFile"
  exit 1
}
$cookie = $cookieLine.Substring('QZONE_COOKIE_STRING='.Length)

$env:QZONE_COOKIE_STRING = $cookie
$env:ONEBOT_HOST = $bindHost
$env:ONEBOT_PORT = "$port"
$env:ONEBOT_ACCESS_TOKEN = $accessToken
$env:QZONE_CACHE_PATH = './test_cache'
$env:QZONE_ENABLE_QR = '0'

$tsx = Join-Path $bridgeDir 'node_modules/.bin/tsx.cmd'
if (-not (Test-Path $tsx)) {
  Write-Output "missing tsx: $tsx"
  exit 1
}

$logParent = Split-Path -Parent $logFile
if (-not (Test-Path -LiteralPath $logParent)) { New-Item -ItemType Directory -Path $logParent -Force | Out-Null }
$proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d', '/s', '/c', ('""' + $tsx + '" src/main.ts"')) -WorkingDirectory $bridgeDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
Write-Output "started qzone bridge pid $($proc.Id)"
Start-Sleep -Seconds 8
$ready = Test-Port -Port $port
Write-Output "listening: $ready"
if (-not $ready) {
  Write-Output "bridge did not become ready; inspect $logFile and its error log"
  exit 1
}

if (-not $script:loginValid) { Write-Output 'bridge online; login is invalid'; exit 2 }
