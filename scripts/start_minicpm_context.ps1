param([string]$Root='D:\Code\Apps\MiniCPM',[int]$Port=6193)
$ErrorActionPreference='Stop'
$taskExe=Join-Path $Root 'llama\llama-server.exe'
$taskModel=Join-Path $Root 'MiniCPM5-2B-Q4_K_M.gguf'
$taskKey=Join-Path $Root 'api-key.local'
if(-not (Test-Path -LiteralPath $taskExe) -or -not (Test-Path -LiteralPath $taskModel) -or -not (Test-Path -LiteralPath $taskKey)){return}
$taskHeaders=@{Authorization='Bearer '+(Get-Content -LiteralPath $taskKey -Raw).Trim()}
try{$taskHealth=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Headers $taskHeaders -TimeoutSec 3;if($taskHealth.status -eq 'ok'){return}}catch{}
if(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue){return}
$taskLog=Join-Path $Root 'runtime_logs'
New-Item -ItemType Directory -Path $taskLog -Force|Out-Null
$taskRun=Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Process -FilePath $taskExe -ArgumentList '--model',("`""+$taskModel+"`""),'--host','127.0.0.1','--port',"$Port",'--ctx-size','16384','--parallel','1','--threads','6','--threads-batch','8','--reasoning','off','--no-reasoning-preserve','--alias','fatfish-context','--n-predict','1024','--api-key-file',("`""+$taskKey+"`""),'--cors-origins','http://127.0.0.1:6185' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLog "$taskRun.out.log") -RedirectStandardError (Join-Path $taskLog "$taskRun.err.log")|Out-Null
