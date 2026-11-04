# Isolated regression tests: no scheduled tasks, QQ operations or host restart.
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/watchdog_dsh.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$names = @('Get-BridgeOnline', 'Test-PortListening', 'Get-HostVerdict', 'Confirm-HostFault', 'Test-NapCatNeedsStart')
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
    $checkLog = Join-Path $DataDir 'check-logs'
    $out = & $source -Check -LogDir $checkLog -DataDir $DataDir -Trace (Join-Path $DataDir 'absent') -BridgePort $port
    if (Test-Path -LiteralPath $checkLog) { throw '-Check wrote logs/state' }
    if (($out | Out-String) -notmatch 'onebotOnline=') { throw 'Missing check result' }
    'PASS: watchdog health/recovery regressions; check mode wrote no files'
} finally {
    if ($null -ne $listener) { $listener.Stop() }
    $resolved = [IO.Path]::GetFullPath($DataDir)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected test directory' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
