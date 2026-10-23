#!/usr/bin/env bash
# Start the whole stack on Linux: Ollama, AstrBot, NapCat.
# Paths come from the environment so the same file works after migration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASTRBOT_HOME="${ASTRBOT_HOME:-$ROOT/../Apps/AstrBot}"
NAPCAT_HOME="${NAPCAT_HOME:-$ROOT/../Apps/NapCat}"
QQ_NUMBER="${FATFISH_QQ:-1670515707}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_DIR/start_all.log"; }

log "启动 Ollama"
"$ROOT/scripts/start_local_model.sh" || log "Ollama 启动失败，离线模型不可用"

log "启动 AstrBot"
if [ -x "$ASTRBOT_HOME/.venv/bin/python" ]; then
    cd "$ASTRBOT_HOME"
    nohup .venv/bin/python main.py >>"$LOG_DIR/astrbot.out.log" 2>&1 &
    cd - >/dev/null
else
    log "找不到 AstrBot venv：$ASTRBOT_HOME/.venv/bin/python"
fi

for _ in $(seq 1 60); do
    if curl -sf --max-time 2 http://127.0.0.1:6185/ >/dev/null 2>&1; then
        log "AstrBot 端口已就绪"
        break
    fi
    sleep 2
done

log "启动 NapCat"
if [ -f "$NAPCAT_HOME/launcher.sh" ]; then
    nohup bash "$NAPCAT_HOME/launcher.sh" "$QQ_NUMBER" >>"$LOG_DIR/napcat.out.log" 2>&1 &
elif command -v napcat >/dev/null 2>&1; then
    nohup napcat "$QQ_NUMBER" >>"$LOG_DIR/napcat.out.log" 2>&1 &
else
    log "未找到 NapCat 启动脚本，请参考 deploy/README 配置系统服务"
fi

log "启动流程结束"
