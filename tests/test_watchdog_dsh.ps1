# Isolated regression tests: no scheduled tasks, QQ operations or host restart.
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/watchdog_dsh.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$names = @('Test-QQAccountPaused', 'Test-QQRecoveryAllowed', 'Start-NapCat', 'Get-BridgeOnline', 'Test-PortListening', 'Get-HostVerdict', 'Confirm-HostFault', 'Test-NapCatNeedsStart', 'Get-QzoneStarterArguments', 'Invoke-QzoneBridge')
foreach ($fn in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($fn.Name -in $names) { . ([scriptblock]::Create($fn.Extent.Text)) }
}
function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -cne $Expected) { throw "$Label : expected '$Expected', got '$Actual'" }
}
$StartupGraceMinutes = 3; $HeartbeatStaleMinutes = 10; $StuckTurnMinutes = 12; $BridgePort = 8646; $FaultConfirmMinutes = 4
$AllowHostRestart = $false
$DataDir = Join-Path ([IO.Path]::GetTempPath()) ('fatfish-watchdog-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $DataDir | Out-Null
$heartbeat = Join-Path $DataDir 'scheduler-heartbeat.json'
$QQPauseMarker = Join-Path $DataDir '.qq-account-paused'
$AllowQQRecovery = $false
$listener = $null
try {
    Assert-Equal (Get-BridgeOnline) $null 'Missing heartbeat is unknown'
    '{"at":"now"}' | Set-Content -LiteralPath $heartbeat
    Assert-Equal (Get-BridgeOnline) $null 'Old schema is unknown'
    '{"transport":{"present":true,"online":true}}' | Set-Content -LiteralPath $heartbeat
    Assert-Equal (Get-BridgeOnline) $true 'Connected transport'
    '{"transport":{"present":true,"online":false}}' | Set-Content -LiteralPath $heartbeat
    Assert-Equal (Get-BridgeOnline) $false 'Disconnected transport'
    (Get-Item -LiteralPath $heartbeat).LastWriteTime = (Get-Date).AddMinutes(-3)
    Assert-Equal (Get-BridgeOnline) $null 'Stale transport is unknown'
    '{"transport":{"present":true,"online":true}}' | Set-Content -LiteralPath $heartbeat
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $result = Test-PortListening $port
    Assert-Equal $result.listen 1 'Listening port'
    Assert-Equal $result.online $true 'TCP probe does not invent offline status'
    $listener.Stop(); $listener = $null
    Assert-Equal (Test-PortListening $port).listen 0 'Closed port'
    Assert-Equal (Get-HostVerdict $true 1 9999 0 99).verdict 'wait' 'Startup grace'
    Assert-Equal (Get-HostVerdict $false $null -1 0 0).why 'process missing' 'Missing host'
    Assert-Equal (Get-HostVerdict $true 30 0 1 0).verdict 'ok' 'Healthy host'
    Assert-Equal (Get-HostVerdict $true 30 0 1 0 $false).verdict 'warn' 'Offline QQ is not reported healthy'
    Assert-Equal (Test-NapCatNeedsStart $true 1 4 10 1) $false 'Connected bot is preserved'
    Assert-Equal (Test-NapCatNeedsStart $false 0 0 $null 0) $true 'Missing bot starts'
    Assert-Equal (Test-NapCatNeedsStart $false 1 2 10 0) $true 'Hung pre-JS QQ recovers despite leftover processes'
    Assert-Equal (Test-NapCatNeedsStart $false 1 2 1 0) $false 'Startup grace preserves booting QQ'
    Assert-Equal (Test-NapCatNeedsStart $false 1 2 10 1) $false 'QR/login wait is preserved'
    Assert-Equal (Test-NapCatNeedsStart $null 1 2 10 0) $false 'Unknown connection does not terminate live QQ'
    Assert-Equal (Get-HostVerdict $true 30 11 1 0).verdict 'warn' 'Stale scheduler preserves live host by default'
    Assert-Equal (Get-HostVerdict $true 30 0 0 0).verdict 'warn' 'Missing bridge preserves live host by default'
    Assert-Equal (Get-HostVerdict $true 30 0 1 99).verdict 'warn' 'Long tool calls never trigger host restart'
    $AllowHostRestart = $true
    Assert-Equal (Get-HostVerdict $true 30 11 1 0).verdict 'restart' 'Explicit host recovery opt-in'
    Assert-Equal (Get-HostVerdict $true 30 0 1 99).verdict 'warn' 'Even opt-in cannot kill a healthy host for one long turn'
    $AllowHostRestart = $false
    $state = [pscustomobject]@{ restarts = @() }
    Assert-Equal (Confirm-HostFault $state 'model turn stuck 13.5 min') $false 'First observation waits'
    $state.faultSince = (Get-Date).AddMinutes(-5).ToString('o')
    Assert-Equal (Confirm-HostFault $state 'model turn stuck 18.5 min') $true 'Changing duration still confirms same fault'
    Assert-Equal (Confirm-HostFault $state 'qq bridge not listening on 8646') $false 'Different fault starts new observation'

    Assert-Equal (Test-QQRecoveryAllowed) $false 'Default watchdog never recovers QQ'
    $AllowQQRecovery = $true
    Assert-Equal (Test-QQRecoveryAllowed) $true 'QQ recovery requires explicit opt-in'
    New-Item -ItemType File -Path $QQPauseMarker | Out-Null
    Assert-Equal (Test-QQRecoveryAllowed) $false 'Pause overrides opt-in'
    Remove-Item -LiteralPath $QQPauseMarker

    # A fake starter lets the recovery path run without reading private config.
    $LogDir = $DataDir
    $QzoneDir = $DataDir
    $QzoneStarter = Join-Path $DataDir 'fake-starter.ps1'
    '# fake starter' | Set-Content -LiteralPath $QzoneStarter -Encoding ASCII
    $QzoneEveryMinutes = 10
    $QzoneBase = 'http://127.0.0.1:5700'
    $command = Get-QzoneStarterArguments ([uri]$QzoneBase) -ProbeOnly
    if (($command -join ' ') -notmatch '-Check' -or ($command -join ' ') -notmatch '127.0.0.1:5700') { throw 'Probe lost configured starter/base' }

    # Stub just the recovery dependencies after the real TCP tests above.
    $script:qzoneHttp = $null
    $script:qzoneListening = 0
    $script:qzoneStarts = @()
    $script:qzoneMessages = @()
    $script:qzoneSaved = $null
    $script:qzoneStartFails = $false
    function powershell.exe {
        $script:qzoneProbeCalls++
        $script:qzoneProbeArgs = $args
        $global:LASTEXITCODE = $script:qzoneProbeCode
    }
    $script:qzoneProbeCode = 1
    $script:qzoneProbeCalls = 0
    function Test-PortListening { param($Port, $Address); $script:qzoneProbeAddress = $Address; return [pscustomobject]@{ listen = $script:qzoneListening; online = $null } }
    function Start-Process {
        param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, $ErrorAction)
        if ($script:qzoneStartFails) { throw 'start failed' }
        $script:qzoneStarts += [pscustomobject]@{ exe = $FilePath; args = $ArgumentList; cwd = $WorkingDirectory; window = $WindowStyle }
    }
    function Write-Log { param($Message); $script:qzoneMessages += $Message }
    function Save-State { param($State); $script:qzoneSaved = $State }
    $qzoneState = [pscustomobject]@{ restarts = @() }
    $AllowQQRecovery = $false
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneProbeCalls 0 'Default mode does not probe Qzone'
    Assert-Equal $script:qzoneStarts.Count 0 'Default mode does not start Qzone'
    $AllowQQRecovery = $true
    New-Item -ItemType File -Path $QQPauseMarker | Out-Null
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneProbeCalls 0 'Paused mode does not probe Qzone'
    Assert-Equal $script:qzoneStarts.Count 0 'Paused mode does not start Qzone'
    Remove-Item -LiteralPath $QQPauseMarker
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneStarts.Count 1 'Missing bridge starts once'
    Assert-Equal $script:qzoneStarts[0].window 'Hidden' 'Recovery is hidden'
    Assert-Equal $script:qzoneStarts[0].cwd $QzoneDir 'Recovery retains bridge working directory'
    if (($script:qzoneStarts[0].args -join ' ') -notmatch '127.0.0.1:5700') { throw 'Recovery lost configured port' }
    if (-not $qzoneState.qzoneAt -or -not [object]::ReferenceEquals($script:qzoneSaved, $qzoneState)) { throw 'Recovery did not update its explicit state argument' }
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneStarts.Count 1 'Cooldown prevents another launch'

    $script:qzoneProbeCode = 2
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneStarts.Count 1 'Expired login does not start duplicate bridge'
    Assert-Equal $qzoneState.qzoneAt $null 'Running bridge clears launch cooldown'
    if (($script:qzoneMessages -join ' ') -notmatch 'login is invalid') { throw 'Expired login needs an explicit warning' }

    $script:qzoneProbeCode = 1
    $script:qzoneListening = 1
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneStarts.Count 1 'Occupied unhealthy port is not duplicated'
    if (($script:qzoneMessages -join ' ') -notmatch 'port is occupied') { throw 'HTTP200 alone was treated as bridge health' }

    $script:qzoneHttp = $null
    $script:qzoneListening = 0
    $QzoneBase = 'http://localhost:5719'
    Invoke-QzoneBridge $qzoneState
    Assert-Equal $script:qzoneStarts.Count 2 'Custom local endpoint can start'
    Assert-Equal $script:qzoneProbeAddress 'localhost' 'Occupied-port probe uses the configured loopback address'
    if (($script:qzoneStarts[-1].args -join ' ') -notmatch 'http://localhost:5719') { throw 'Custom base did not reach the starter' }
    $QzoneBase = 'http://example.com:5700'
    Invoke-QzoneBridge ([pscustomobject]@{})
    Assert-Equal $script:qzoneStarts.Count 2 'Remote endpoint cannot launch a local bridge'

    $QzoneBase = 'http://127.0.0.1:5700'
    $script:qzoneStartFails = $true
    $failedState = [pscustomobject]@{}
    Invoke-QzoneBridge $failedState
    Assert-Equal $failedState.qzoneAt $null 'Failed launcher does not report start or apply cooldown'
    # Recovery is a top-level action, independent of optional version checks.
    $recoveryCalls = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Invoke-QzoneBridge' }, $true))
    Assert-Equal $recoveryCalls.Count 1 'Exactly one recovery action per watchdog run'
    $ancestor = $recoveryCalls[0].Parent
    while ($null -ne $ancestor) {
        if ($ancestor -is [System.Management.Automation.Language.FunctionDefinitionAst]) { throw 'Qzone recovery is still nested inside version checks' }
        $ancestor = $ancestor.Parent
    }
    # Only the real entry-point statements run; all process/probe dependencies are fake.
    $entry = (Get-Content -LiteralPath $source -Raw -Encoding UTF8)
    $entry = $entry.Substring($entry.IndexOf('$procs = Get-HostProcesses' + [Environment]::NewLine + '$alive ='))
    function Get-HostProcesses { return @() }
    function Get-NapCatProcesses { return @() }
    function Read-State { return [pscustomobject]@{ restarts = @() } }
    function Get-Process { throw 'QQ process inspection is forbidden in default/paused mode' }
    function Restart-App { param($Why); $script:hostStarts++ }
    function Count-RecentRestarts { param($State); return 0 }
    $MaxRestartsPerHour = 3
    $script:hostStarts = 0
    $script:taskRequests = 0
    $script:taskExit = 0
    function schtasks.exe { $script:taskRequests++; $global:LASTEXITCODE = $script:taskExit }
    $AllowQQRecovery = $false
    Assert-Equal (Start-NapCat) $false 'Default mode blocks direct NapCat helper'
    Assert-Equal $script:taskRequests 0 'Default helper does not request a task'
    $Check = $false
    . ([scriptblock]::Create($entry))
    Assert-Equal $script:hostStarts 1 'Default watchdog still recovers missing DSH'
    Assert-Equal $script:taskRequests 0 'Default watchdog does not request QQ task'
    $AllowQQRecovery = $true
    New-Item -ItemType File -Path $QQPauseMarker | Out-Null
    Assert-Equal (Start-NapCat) $false 'Paused helper blocks explicit QQ opt-in'
    . ([scriptblock]::Create($entry))
    Assert-Equal $script:hostStarts 2 'Paused watchdog still recovers missing DSH'
    Assert-Equal $script:taskRequests 0 'Paused watchdog does not request QQ task'
    $Check = $true
    $script:qzoneMessages = @()
    $script:qzoneSaved = $null
    $out = . ([scriptblock]::Create($entry))
    if (($out | Out-String) -notmatch 'qqPaused=True') { throw 'Check does not report pause marker' }
    Assert-Equal $script:qzoneMessages.Count 0 'Check does not write logs'
    Assert-Equal $script:qzoneSaved $null 'Check does not write state'
    Assert-Equal $script:taskRequests 0 'Check does not request QQ task'
    Remove-Item -LiteralPath $QQPauseMarker
    Assert-Equal (Start-NapCat) $true 'Explicit QQ opt-in requests existing task'
    Assert-Equal $script:taskRequests 1 'One helper call requests task once'
    $script:taskExit = 5
    Assert-Equal (Start-NapCat) $false 'Rejected task request is not reported accepted'
    Assert-Equal $script:taskRequests 2 'Task failure has no retry'
    'PASS: watchdog health/recovery and qzone port/state/health regressions; check mode wrote no files'
} finally {
    if ($null -ne $listener) { $listener.Stop() }
    $resolved = [IO.Path]::GetFullPath($DataDir)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected test directory' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
