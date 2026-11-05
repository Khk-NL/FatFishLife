# Isolated NapCat bootstrap gate tests: no tasks, elevation, native processes or QQ.
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/start_all.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$gate = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.IfStatementAst] -and
    $n.Clauses[0].Item1.Extent.Text -eq 'Test-Path -LiteralPath $QQPauseMarker'
}, $true)
if ($null -eq $gate) { throw 'Missing NapCat pause gate' }
$top = @($ast.EndBlock.Statements)
$index = [array]::IndexOf($top, $gate)
if ($index -lt 0 -or $index -ge ($top.Count - 2) -or $top[$index + 1].Extent.Text -notmatch 'start_local_model.ps1') { throw 'Ollama step must follow NapCat gate independently' }
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('fatfish-bootstrap-pause-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $QQPauseMarker = Join-Path $tempDir '.qq-account-paused'
    New-Item -ItemType File -Path $QQPauseMarker | Out-Null
    $launcher = Join-Path $tempDir 'fake-launcher.bat'
    $script:steps = @()
    function Write-Step { param($text); $script:steps += $text }
    function schtasks.exe { throw 'Paused bootstrap must not request elevation' }
    function Start-Process { throw 'Paused bootstrap must not launch NapCat' }
    function Get-CimInstance { throw 'Paused bootstrap must not inspect QQ processes' }
    function Stop-Process { throw 'Paused bootstrap must not terminate QQ processes' }
    function icacls.exe { throw 'Paused bootstrap must not alter launcher integrity' }
    foreach ($DryRun in @($false, $true)) {
        $script:continued = $false
        . ([scriptblock]::Create($gate.Extent.Text + "`n" + '$script:continued = $true'))
        if (-not $script:continued) { throw 'Paused bootstrap returned before subsequent steps' }
    }
    if ($script:steps.Count -ne 2 -or ($script:steps -join ' ') -notmatch 'QQ 账号已暂停') { throw 'Paused bootstrap status missing' }
    Remove-Item -LiteralPath $QQPauseMarker
    $DryRun = $true
    . ([scriptblock]::Create($gate.Extent.Text))
    if ($script:steps[-1] -notlike '[[]dry[]] would start NapCat*') { throw 'Unpaused dry-run changed' }
    'PASS: paused bootstrap skips NapCat and elevation, preserves subsequent Ollama step; no real operations'
} finally {
    Remove-Item -LiteralPath $QQPauseMarker -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tempDir
}
