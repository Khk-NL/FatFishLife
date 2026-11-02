# DSH watchdog v2: keep the app (and its QQ bridge) alive.
# Checks, cheapest first:
#   1. process missing            -> start it
#   2. scheduler heartbeat stale  -> hung main loop -> restart
#   3. port 8643 not listening    -> bridge dead     -> restart
#   4. a model turn stuck > N min -> restart
# Cooldown keeps it from looping (max restarts per rolling hour).
# ASCII only: PowerShell 5.1 misreads UTF-8 Chinese comments without BOM.
param(
    [switch]$Check,
    [string]$Exe = 'D:/dsh/DeepSeek Harness.exe',
    [string]$LogDir = 'D:/Code/Projects/FatFishLife/outputs/agent',
    [string]$DataDir = 'D:/Code/Projects/FatFishLife/data/dsh',
    [string]$Trace = 'C:/Users/kongb/.dsh/media/onebot/fatfish-qq-2d989f916ec56ecd7d3628063d100fa55449765969f5bfbf3e30bbe446531814/qq-trace.jsonl',
    [string]$Python = 'D:/Code/Projects/FatFishLife/.tools/dsh-python/Scripts/python.exe',
    [string]$PruneScript = 'D:/Code/Projects/FatFishLife/scripts/prune_dsh_cookies.py',
    [int]$BridgePort = 8646,
    [string]$GuardScript = 'D:/Code/Projects/FatFishLife/scripts/version_guard.py',
    [int]$GuardEveryMinutes = 60,
    [int]$HeartbeatStaleMinutes = 10,
    [int]$StuckTurnMinutes = 12,
    [int]$MaxRestartsPerHour = 3
)

$ErrorActionPreference = 'Continue'
$logPath = Join-Path $LogDir 'watchdog.log'
$statePath = Join-Path $LogDir 'watchdog-state.json'

function Write-Log([string]$Message) {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Read-State {
    if (Test-Path -LiteralPath $statePath) {
        try { return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    }
    return [pscustomobject]@{ restarts = @() }
}

function Save-State($state) {
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Count-RecentRestarts($state) {
    $cutoff = (Get-Date).AddHours(-1)
    @($state.restarts | Where-Object { $null -ne $_ -and ([datetime]$_).ToLocalTime() -gt $cutoff }).Count
}

function Get-HostProcesses {
    @(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue)
}

function Get-NapCatProcesses {
    @(Get-Process -Name 'NapCatWinBootMain' -ErrorAction SilentlyContinue)
}

# NapCat needs admin rights for the QQ injection. We cannot create an elevated task
# from a limited shell, but FatFishLife-Start already runs with RunLevel=Highest and
# start_all.ps1 launches NapCat (AstrBot is retired via data\.astrbot-retired).
function Start-NapCat {
    try {
        schtasks /Run /TN 'FatFishLife-Start' | Out-Null
        Start-Sleep -Seconds 10
        $after = Get-NapCatProcesses
        Write-Log ("napcat start requested via FatFishLife-Start, now {0} processes" -f $after.Count)
        return $after.Count -gt 0
    } catch {
        Write-Log ("error: napcat start failed - {0}" -f $_.Exception.Message)
        return $false
    }
}

function Test-PortListening([int]$Port) {
    # Get-NetTCPConnection reports nothing for listeners owned by higher-integrity
    # processes (the DSH host lives one level up), so the old check said "down"
    # forever and restarted the app every run. Probe with a real TCP connect.
    $listen = 0
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(1500, $false) -and $client.Connected) { $listen = 1 }
    } catch {
        $listen = 0
    } finally {
        try { $client.Close() } catch { }
    }
    return [pscustomobject]@{ listen = $listen; established = 0 }
}

function Get-HeartbeatAgeMinutes {
    $heartbeat = Join-Path $DataDir 'scheduler-heartbeat.json'
    if (-not (Test-Path -LiteralPath $heartbeat)) { return 9999 }
    return [math]::Round(((Get-Date) - (Get-Item -LiteralPath $heartbeat).LastWriteTime).TotalMinutes, 1)
}

function Get-StuckTurnMinutes {
    if (-not (Test-Path -LiteralPath $Trace)) { return 0 }
    $lines = @(Get-Content -LiteralPath $Trace -Tail 60 -Encoding UTF8 -ErrorAction SilentlyContinue)
    $open = $null
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        try { $row = $lines[$i] | ConvertFrom-Json } catch { continue }
        if ($row.stage -eq 'agent' -and $row.reason -like '*开始*') { $open = $row; break }
        if ($row.stage -eq 'agent' -and $row.reason -like '*结束*') { return 0 }
        if ($row.stage -eq 'outbound') { return 0 }
    }
    if ($null -eq $open) { return 0 }
    $started = [datetimeoffset]::FromUnixTimeMilliseconds([int64]$open.ts).LocalDateTime
    # A turn whose start timestamp is older than the current host process is a leftover from a
    # killed run (the trace file is append-only), not a live hang - restarting cannot clear it.
    $hostProc = @(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue) | Sort-Object StartTime | Select-Object -First 1
    if ($null -ne $hostProc -and $started -lt $hostProc.StartTime.AddMinutes(-1)) { return 0 }
    return [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
}

function Invoke-VersionGuard {
    # QQ 会自动更新，而 NapCat 的支持表是按 QQ 构建号写死的；更新跑在前面就会 0x80000003 崩。
    # 这里每小时对一次版本，不在表里就让 version_guard.py 自己换 NapCat。
    if (-not (Test-Path -LiteralPath $GuardScript)) { return }
    $state = Read-State
    $last = 0
    if ($state.PSObject.Properties['guardAt']) { $last = [int64]$state.guardAt }
    $age = ([DateTimeOffset]::Now.ToUnixTimeSeconds()) - $last
    if ($age -lt ($GuardEveryMinutes * 60)) { return }
    $out = & $Python $GuardScript 2>&1 | Out-String
    Write-Log ('version guard: ' + ($out.Trim() -replace "`r?`n", ' | '))
    $state | Add-Member -NotePropertyName guardAt -NotePropertyValue ([DateTimeOffset]::Now.ToUnixTimeSeconds()) -Force
    Save-State $state
}

function Invoke-CookiePrune {
    # DSH stores one dsh-auth-<random> cookie per random local port it ever started on.
    # Chromium sends cookies by host and ignores the port, so the history goes into every
    # request header until it overflows and the app fails with "Web authentication failed".
    # Only safe while the app is closed: Chromium rewrites its in-memory copy on exit.
    if (-not (Test-Path -LiteralPath $PruneScript)) { Write-Log 'cookie prune: script missing, skipped'; return }
    if (-not (Test-Path -LiteralPath $Python)) { Write-Log 'cookie prune: python missing, skipped'; return }
    try {
        $out = & $Python $PruneScript 2>&1 | Out-String
        $summary = ($out -split "`r?`n" | Where-Object { $_ -match 'PRUNE_RESULT' } | Select-Object -Last 1)
        if (-not $summary) { $summary = 'PRUNE_RESULT unknown' }
        Write-Log ('cookie prune: ' + $summary.Trim())
    } catch {
        Write-Log ('cookie prune failed: ' + $_.Exception.Message)
    }
}

function Restart-App([string]$Why) {
    $procs = Get-HostProcesses
    Write-Log ("restart triggered: {0} (killing {1} processes)" -f $Why, $procs.Count)
    foreach ($p in $procs) { try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { } }
    Start-Sleep -Seconds 6
    Invoke-CookiePrune
    try {
        Start-Process -FilePath $Exe -WorkingDirectory (Split-Path -Parent $Exe) | Out-Null
        Start-Sleep -Seconds 8
        $after = Get-HostProcesses
        Write-Log ("relaunched, now {0} processes" -f $after.Count)
    } catch {
        Write-Log ("error: relaunch failed - {0}" -f $_.Exception.Message)
    }
}

$procs = Get-HostProcesses
$alive = $procs.Count -gt 0
$heartbeatAge = if ($alive) { Get-HeartbeatAgeMinutes } else { -1 }
$port = if ($alive) { Test-PortListening $BridgePort } else { [pscustomobject]@{ listen = 0; established = 0 } }
if ($alive -and -not $Check) { Invoke-VersionGuard }
$stuck = if ($alive) { Get-StuckTurnMinutes } else { 0 }
$napcat = Get-NapCatProcesses

$verdict = 'ok'
$why = ''
if (-not $alive -and -not $Check) {
    # App is closed right now: this is the safe moment to trim the auth cookie pile.
    Invoke-CookiePrune
}
if (-not $alive) {
    $verdict = 'restart'; $why = 'process missing'
} elseif ($heartbeatAge -gt $HeartbeatStaleMinutes) {
    $verdict = 'restart'; $why = "scheduler heartbeat stale $heartbeatAge min"
} elseif ($port.listen -eq 0) {
    $verdict = 'restart'; $why = 'qq bridge not listening on ' + $BridgePort
} elseif ($stuck -gt $StuckTurnMinutes) {
    $verdict = 'restart'; $why = "model turn stuck $stuck min"
}

if ($Check) {
    Write-Log ("check: processes={0} heartbeatAge={1}m listen={2} established={3} stuck={4}m napcat={5} => {6} {7}" -f `
        $procs.Count, $heartbeatAge, $port.listen, $port.established, $stuck, $napcat.Count, $verdict, $why)
    return
}

$state = Read-State

# NapCat is a separate program; if it died we only restart DSH when the bridge is dead.
if ($napcat.Count -eq 0) {
    $lastNapCat = $null
    if ($state.napcatAt) { try { $lastNapCat = [datetime]$state.napcatAt } catch { } }
    $cooled = ($null -eq $lastNapCat) -or (((Get-Date) - $lastNapCat).TotalMinutes -gt 10)
    if ($cooled) {
        Start-NapCat | Out-Null
        $state | Add-Member -NotePropertyName napcatAt -NotePropertyValue (Get-Date).ToString('o') -Force
        Save-State $state
    } else {
        Write-Log 'napcat is not running but restarted less than 10 min ago - waiting'
    }
} else {
    $state | Add-Member -NotePropertyName napcatAt -NotePropertyValue $null -Force
}

if ($verdict -ne 'restart') {
    if ($port.established -eq 0 -and $port.listen -gt 0) {
        Write-Log 'warn: bridge listening but NapCat not connected yet'
    }
    Save-State $state
    return
}

$recent = Count-RecentRestarts $state
if ($recent -ge $MaxRestartsPerHour) {
    Write-Log ("blocked: {0} but already restarted {1} times this hour - manual check needed ({2})" -f $verdict, $recent, $why)
    return
}

Restart-App $why
$state.restarts = @(@($state.restarts) + (Get-Date).ToString('o') | Select-Object -Last 20)
Save-State $state
