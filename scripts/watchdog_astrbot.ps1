# Watch only AstrBot main processes, preserving verification and indexing helpers.
param([string]$AstrBot='D:\Code\Apps\AstrBot',[int]$Port=6185,[int]$StartupGraceSeconds=300,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$taskPython=Join-Path $AstrBot '.venv\Scripts\python.exe'
$taskLogDir=Join-Path $AstrBot 'data\runtime_logs'
$taskProcesses=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
$taskRootPattern=[regex]::Escape([IO.Path]::GetFullPath($AstrBot))
$taskMain=@($taskProcesses | Where-Object {
    $_.CommandLine -match '(?i)(^|[\\/\s"])main\.py([\s"]|$)' -and
    ($_.ExecutablePath -eq $taskPython -or $_.CommandLine -match $taskRootPattern)
})
$taskListener=@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
$taskAge=if($taskMain.Count){[int]((Get-Date)-($taskMain | Sort-Object CreationDate | Select-Object -First 1).CreationDate).TotalSeconds}else{0}
$taskHealthy=$false
if($taskListener.Count){
    try{$taskResponse=Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5;$taskHealthy=$taskResponse.StatusCode -eq 200}catch{$taskHealthy=$false}
}
$taskStatus=if($taskHealthy){'healthy'}elseif($taskMain.Count -and $taskAge -lt $StartupGraceSeconds){'starting'}elseif($taskListener.Count -and -not $taskMain.Count){'unexpected_listener'}else{'restart_needed'}
if($CheckOnly){@{status=$taskStatus;main_count=$taskMain.Count;age_seconds=$taskAge;port=$Port}|ConvertTo-Json -Compress;exit 0}
if($taskStatus -in @('healthy','starting')){exit 0}
New-Item -ItemType Directory -Path $taskLogDir -Force|Out-Null
if($taskStatus -eq 'unexpected_listener'){
    @{time=(Get-Date -Format o);action='blocked';reason='port_owned_by_other_process'}|ConvertTo-Json -Compress|Add-Content -LiteralPath (Join-Path $taskLogDir 'watchdog.jsonl') -Encoding UTF8
    exit 1
}
$taskIds=@($taskMain|ForEach-Object{[int]$_.ProcessId})
$taskChildren=@($taskProcesses|Where-Object{$_.ParentProcessId -in $taskIds})
$taskIds+=@($taskChildren|ForEach-Object{[int]$_.ProcessId})
@{time=(Get-Date -Format o);action='restart';reason='main_absent_or_unresponsive';pids=$taskIds;age_seconds=$taskAge}|ConvertTo-Json -Compress|Add-Content -LiteralPath (Join-Path $taskLogDir 'watchdog.jsonl') -Encoding UTF8
foreach($taskId in ($taskIds|Select-Object -Unique)){Stop-Process -Id $taskId -Force -ErrorAction SilentlyContinue}
$taskFFmpeg=Join-Path $PSScriptRoot '..\.tools\ffmpeg\bin'
if(Test-Path -LiteralPath (Join-Path $taskFFmpeg 'ffmpeg.exe')){$env:PATH="$([IO.Path]::GetFullPath($taskFFmpeg));$env:PATH"}
$env:PYTHONIOENCODING='utf-8'
$taskRun=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$taskStarted=Start-Process -FilePath $taskPython -ArgumentList '-X','faulthandler','-u','main.py' -WorkingDirectory $AstrBot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskLogDir "$taskRun.out.log") -RedirectStandardError (Join-Path $taskLogDir "$taskRun.err.log")
@{time=(Get-Date -Format o);action='started';pid=$taskStarted.Id;run=$taskRun}|ConvertTo-Json -Compress|Add-Content -LiteralPath (Join-Path $taskLogDir 'watchdog.jsonl') -Encoding UTF8
