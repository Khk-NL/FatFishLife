param(
    [string]$OllamaBin = $env:OLLAMA_BIN,
    [string]$OllamaModels = $env:OLLAMA_MODELS,
    [string]$OllamaHost = $env:OLLAMA_HOST
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $OllamaBin) { $OllamaBin = Join-Path $root "..\..\Apps\llm\ollama\ollama.exe" }
if (-not $OllamaModels) { $OllamaModels = Join-Path $root "..\..\Apps\llm\models" }
if (-not $OllamaHost) { $OllamaHost = "127.0.0.1:11434" }

if (-not (Test-Path $OllamaBin)) {
    Write-Error "找不到 ollama.exe：$OllamaBin（可用 OLLAMA_BIN 指定）"
    exit 1
}

try {
    $null = Invoke-WebRequest -Uri "http://$OllamaHost/api/tags" -TimeoutSec 3 -UseBasicParsing
    Write-Output "ollama 已在运行：$OllamaHost"
    exit 0
} catch { }

$env:OLLAMA_MODELS = $OllamaModels
$env:OLLAMA_HOST = $OllamaHost
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "ollama.log"

Start-Process -FilePath $OllamaBin -ArgumentList "serve" -WindowStyle Hidden
Write-Output "ollama 已启动：$OllamaHost，模型目录 $OllamaModels"
