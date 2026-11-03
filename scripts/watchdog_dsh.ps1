# DSH watchdog v2: keep the app (and its QQ bridge) alive.
# Checks, cheapest first:
#   1. process missing            -> start it
#   2. scheduler/bridge unhealthy -> warn (restart only with explicit opt-in)
#   3. a long model/tool turn     -> warn; never infer a dead host from one turn
# Cooldown keeps it from looping (max restarts per rolling hour).
# ASCII only: PowerShell 5.1 misreads UTF-8 Chinese comments without BOM.
param(
    [switch]$Check,
    [switch]$AllowHostRestart,
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
    [int]$StartupGraceMinutes = 3,
    [int]$FaultConfirmMinutes = 4,
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
        if ($LASTEXITCODE -ne 0) { throw "scheduled task failed with exit code $LASTEXITCODE" }
        Start-Sleep -Seconds 10
        $after = Get-NapCatProcesses
        $qq = @(Get-Process -Name 'QQ' -ErrorAction SilentlyContinue)
        Write-Log ("napcat start requested: bootstrap={0} qq={1}; login/OneBot readiness is checked separately" -f $after.Count, $qq.Count)
        return ($after.Count -gt 0 -and $qq.Count -gt 0)
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
    return [pscustomobject]@{ listen = $listen; online = (Get-BridgeOnline) }
}

function Get-BridgeOnline {
    # The control plugin observes the existing authenticated OneBot transport.
    # Old/missing heartbeat schemas mean unknown, never disconnected.
    $heartbeat = Join-Path $DataDir 'scheduler-heartbeat.json'
    try {
        if (((Get-Date) - (Get-Item -LiteralPath $heartbeat -ErrorAction Stop).LastWriteTime).TotalMinutes -gt 2) { return $null }
        $row = Get-Content -LiteralPath $heartbeat -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($row.transport.present -is [bool] -and $row.transport.online -is [bool]) {
            return ($row.transport.present -and $row.transport.online)
        }
    } catch { }
    return $null
}

function Get-HostAgeMinutes($Processes) {
    try {
        $first = $Processes | Sort-Object StartTime | Select-Object -First 1
        if ($null -ne $first) { return ((Get-Date) - $first.StartTime).TotalMinutes }
    } catch { }
    return $null
}

function Get-HostVerdict([bool]$Alive, $Age, [double]$HeartbeatAge, [int]$Listening, [double]$Stuck) {
    if (-not $Alive) { return [pscustomobject]@{ verdict = 'restart'; why = 'process missing' } }
    if ($null -ne $Age -and $Age -lt $StartupGraceMinutes) {
        return [pscustomobject]@{ verdict = 'wait'; why = 'host startup grace period' }
    }
    if ($HeartbeatAge -gt $HeartbeatStaleMinutes) {
        $action = if ($AllowHostRestart) { 'restart' } else { 'warn' }
        return [pscustomobject]@{ verdict = $action; why = "scheduler heartbeat stale $HeartbeatAge min" }
    }
    if ($Listening -eq 0) {
        $action = if ($AllowHostRestart) { 'restart' } else { 'warn' }
        return [pscustomobject]@{ verdict = $action; why = 'qq bridge not listening on ' + $BridgePort }
    }
    if ($Stuck -gt $StuckTurnMinutes) {
        return [pscustomobject]@{ verdict = 'warn'; why = "model/tool turn running $Stuck min; live host preserved" }
    }
    return [pscustomobject]@{ verdict = 'ok'; why = '' }
}

function Confirm-HostFault($State, [string]$Why) {
    $faultKey = $Why -replace '\d+(?:\.\d+)? min', 'timeout'
    if ($State.faultReason -eq $faultKey -and $State.faultSince) {
        try { return (((Get-Date) - [datetime]$State.faultSince).TotalMinutes -ge $FaultConfirmMinutes) } catch { }
    }
    $State | Add-Member -NotePropertyName faultReason -NotePropertyValue $faultKey -Force
    $State | Add-Member -NotePropertyName faultSince -NotePropertyValue (Get-Date).ToString('o') -Force
    return $false
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
    # Monitoring must not replace a live injection runtime. Upgrades are a
    # separate maintenance action; --check never downloads or stops QQ.
    if (-not (Test-Path -LiteralPath $GuardScript)) { return }
    $state = Read-State
    $last = 0
    if ($state.PSObject.Properties['guardAt']) { $last = [int64]$state.guardAt }
    $age = ([DateTimeOffset]::Now.ToUnixTimeSeconds()) - $last
    if ($age -lt ($GuardEveryMinutes * 60)) { return }
    $out = & $Python $GuardScript --check 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Log ('version guard: ' + ($out.Trim() -replace "`r?`n", ' | '))
    if ($code -ne 0) { Write-Log ("warn: version check exit={0}; no automatic install performed" -f $code) }
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
    Write-Log ("restart triggered: {0} (closing {1} processes)" -f $Why, $procs.Count)
    foreach ($p in $procs) { try { $null = $p.CloseMainWindow() } catch { } }
    if ($procs.Count -gt 0) { Start-Sleep -Seconds 8 }
    $left = Get-HostProcesses
    foreach ($p in $left) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    if ($left.Count -gt 0) { Write-Log ("forced {0} processes after graceful close timeout" -f $left.Count) }
    Start-Sleep -Seconds 6
    if ((Get-HostProcesses).Count -gt 0) { Write-Log 'error: host still running; relaunch cancelled'; return }
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
$hostAge = if ($alive) { Get-HostAgeMinutes $procs } else { $null }
$port = if ($alive) { Test-PortListening $BridgePort } else { [pscustomobject]@{ listen = 0; online = $null } }
if ($alive -and -not $Check) { Invoke-VersionGuard }
$stuck = if ($alive) { Get-StuckTurnMinutes } else { 0 }
$napcat = Get-NapCatProcesses

$decision = Get-HostVerdict $alive $hostAge $heartbeatAge $port.listen $stuck
$verdict = $decision.verdict
$why = $decision.why
if ($Check) {
    $online = if ($null -eq $port.online) { 'unknown' } else { [string]$port.online }
    Write-Output ("check: processes={0} heartbeatAge={1}m listen={2} onebotOnline={3} stuck={4}m napcat={5} => {6} {7}" -f `
        $procs.Count, $heartbeatAge, $port.listen, $online, $stuck, $napcat.Count, $verdict, $why)
    return
}

$state = Read-State

# NapCat is a separate program; if it died we only restart DSH when the bridge is dead.
$qqCount = @(Get-Process -Name 'QQ' -ErrorAction SilentlyContinue).Count
if ($verdict -ne 'wait' -and $port.online -ne $true -and ($napcat.Count -eq 0 -or $qqCount -eq 0)) {
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
    $state | Add-Member -NotePropertyName faultReason -NotePropertyValue $null -Force
    $state | Add-Member -NotePropertyName faultSince -NotePropertyValue $null -Force
    if ($port.listen -gt 0 -and $port.online -eq $false) {
        Write-Log 'warn: authenticated OneBot transport is offline'
    } elseif ($port.listen -gt 0 -and $null -eq $port.online) {
        Write-Log 'bridge listening; OneBot status unknown (no fresh transport heartbeat)'
    } elseif ($verdict -eq 'wait') {
        Write-Log $why
    }
    if ($verdict -eq 'warn') { Write-Log ('warn: ' + $why + '; automatic host restart disabled') }
    Save-State $state
    return
}

# A transient bridge/heartbeat failure must survive two scheduled checks before
# it can close the desktop. Missing processes can still be started immediately.
if ($alive) {
    if (-not (Confirm-HostFault $state $why)) {
        Write-Log ("waiting to confirm host fault: {0}" -f $why)
        Save-State $state
        return
    }
}

$recent = Count-RecentRestarts $state
if ($recent -ge $MaxRestartsPerHour) {
    Write-Log ("blocked: {0} but already restarted {1} times this hour - manual check needed ({2})" -f $verdict, $recent, $why)
    return
}

Restart-App $why
$state.restarts = @(@($state.restarts) + (Get-Date).ToString('o') | Select-Object -Last 20)
Save-State $state
