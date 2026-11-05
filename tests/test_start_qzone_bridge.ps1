# Isolated starter tests: fake credentials, HTTP responses and launchers only.
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/start_qzone_bridge.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-Port' }, $true)
. ([scriptblock]::Create($fn.Extent.Text))
$stopMatch = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-BridgeProcess' }, $true)
. ([scriptblock]::Create($stopMatch.Extent.Text))
if (-not (Test-BridgeProcess 'node "D:\Code\custom bridge\node_modules\tsx\cli.mjs" src/main.ts' 'D:/Code/custom bridge')) { throw 'Configured bridge path did not match' }
if (-not (Test-BridgeProcess 'node "D:/Code/custom bridge/src/main.ts"' 'D:/Code/custom bridge')) { throw 'Absolute entry did not match' }
foreach ($cmd in @('', 'node D:/Code/other/node_modules/tsx/cli.mjs src/main.ts', 'node D:/Code/custom-bridge-other/src/main.ts', 'node "D:/Code/custom bridge/src/other.ts"')) {
    if (Test-BridgeProcess $cmd 'D:/Code/custom bridge') { throw 'Unrelated or unreadable process matched stop scope' }
}
$baseUrl = 'http://127.0.0.1:5700'
$accessToken = 'test-only-token'
$script:case = 'online'
$script:actions = @()
function Invoke-WebRequest {
    param($Uri, $Method, $Body, $ContentType, $Headers, $TimeoutSec, [switch]$UseBasicParsing)
    if ($Headers.Authorization -cne 'Bearer test-only-token') { throw 'fake bearer missing' }
    $script:actions += $Uri
    if ($script:case -eq 'offline') { throw 'offline' }
    if ($script:case -eq 'bad-business') { return [pscustomobject]@{ StatusCode = 200; Content = '{"status":"failed","retcode":1,"data":{"user_id":1}}' } }
    if ($script:case -eq 'non-json') { return [pscustomobject]@{ StatusCode = 200; Content = '<html>other server</html>' } }
    if ($Uri -like '*/check_cookie') {
        $valid = if ($script:case -eq 'expired') { 'false' } else { 'true' }
        return [pscustomobject]@{ StatusCode = 200; Content = ('{"status":"ok","retcode":0,"data":{"valid":' + $valid + '}}') }
    }
    if ($script:case -eq 'expired') { throw 'expired cookie blocks identity endpoint' }
    if ($script:case -eq 'bad-identity') { return [pscustomobject]@{ StatusCode = 200; Content = '{"status":"failed","retcode":1}' } }
    return [pscustomobject]@{ StatusCode = 200; Content = '{"status":"ok","retcode":0,"data":{"user_id":1}}' }
}
if (-not (Test-Port 5700) -or -not $script:loginValid) { throw 'Valid authenticated bridge failed health' }
if ($script:actions.Count -ne 2 -or $script:actions[0] -notlike '*/check_cookie' -or $script:actions[-1] -notlike '*/get_login_info') { throw 'Cookie and identity checks are out of order' }
$script:case = 'expired'
$script:actions = @()
if (-not (Test-Port 5700) -or $script:loginValid) { throw 'Expired cookie must be distinguished from missing bridge' }
if ($script:actions.Count -ne 1 -or $script:actions[0] -notlike '*/check_cookie') { throw 'Expired cookie incorrectly required identity endpoint' }
foreach ($case in @('bad-business', 'non-json', 'offline', 'bad-identity')) {
    $script:case = $case
    if (Test-Port 5700) { throw ('Unexpected healthy result: ' + $case) }
}
'PASS: starter authenticated health/business response/invalid JSON/expired login regressions (fake credentials only)'
