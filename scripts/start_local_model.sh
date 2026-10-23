#!/usr/bin/env bash
# Start the local Ollama server used by the offline plugin.
# Paths come from the environment so the same script works on a server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLLAMA_BIN="${OLLAMA_BIN:-$ROOT/../Apps/llm/ollama/ollama}"
OLLAMA_MODELS="${OLLAMA_MODELS:-$ROOT/../Apps/llm/models}"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

if [ ! -x "$OLLAMA_BIN" ] && ! command -v ollama >/dev/null 2>&1; then
    echo "找不到 ollama（可用 OLLAMA_BIN 指定，或安装系统 ollama）" >&2
    exit 1
fi

if curl -sf --max-time 3 "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    echo "ollama 已在运行：$OLLAMA_HOST"
    exit 0
fi

mkdir -p "$ROOT/logs"
export OLLAMA_MODELS OLLAMA_HOST

if [ -x "$OLLAMA_BIN" ]; then
    nohup "$OLLAMA_BIN" serve >"$ROOT/logs/ollama.log" 2>&1 &
else
    nohup ollama serve >"$ROOT/logs/ollama.log" 2>&1 &
fi

echo "ollama 已启动：$OLLAMA_HOST，模型目录 $OLLAMA_MODELS"
