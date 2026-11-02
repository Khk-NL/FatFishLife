"""成长记录的两端：写一条、生成摘要喂给提示词。

用法：
    python scripts/growth_cli.py record --capability qzone_post --status success --note "发了条说说"
    python scripts/growth_cli.py digest [--limit 8]     # 写 data/dsh/growth-digest.txt

设计：
- 复用 fatfish_core.growth 的受控标签，不新造词表；
- 只写 memory.db 的 events(kind='capability')，不动表情/照片等其它表；
- 摘要文件是纯文本，桥读它拼进系统提示，读不到就当没有。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fatfish_core import growth, memory as memory_api  # noqa: E402

DB = Path(os.environ.get("FATFISH_MEMORY_DB") or "D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db")
DIGEST = Path(os.environ.get("FATFISH_GROWTH_DIGEST") or ROOT / "data" / "dsh" / "growth-digest.txt")


def resolve(capability: str) -> tuple[str, str]:
    """允许直接写工具名（qzone_post）或受控标签（qzone），统一映射成受控标签。"""
    if capability in growth.TOOL_CAPABILITIES:
        return growth.TOOL_CAPABILITIES[capability]
    if capability in growth.CAPABILITIES:
        return capability, "use"
    raise ValueError("未知能力、状态或阶段")


def record(capability: str, status: str, note: str) -> dict:
    store = memory_api.MemoryStore(DB)
    try:
        label, stage = resolve(capability)
        event_id = growth.record_capability(store, label, status, stage=stage)
        capability = label
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    if note:
        # 备注单独一条 note，方便以后按自然语言找回来；不作为能力标签。
        store.remember(note, platform="system", scope="private", kind="note", actor="bot")
    return {"ok": True, "id": event_id, "capability": capability, "status": status}


def digest(limit: int = 8) -> dict:
    store = memory_api.MemoryStore(DB)
    rows = store.recent(scopes=("public", "private"), limit=200, kinds=("capability",))
    summary = growth.capability_summary(rows)
    tally: dict[str, dict] = {}
    for item in summary:
        name = item.get("name") or item.get("capability") or ""
        if not name:
            continue
        bucket = tally.setdefault(name, {"ok": 0, "bad": 0})
        if item.get("status") == "success":
            bucket["ok"] += item.get("count", 0)
        else:
            bucket["bad"] += item.get("count", 0)
    ranked = sorted(tally.items(), key=lambda pair: (-pair[1]["ok"], pair[1]["bad"]))
    lines = []
    for name, bucket in ranked[:limit]:
        text = f"- {name}：成了 {bucket['ok']} 次"
        if bucket["bad"]:
            text += f"，磕碰 {bucket['bad']} 次"
        lines.append(text)
    text = "\n".join(lines)
    DIGEST.parent.mkdir(parents=True, exist_ok=True)
    DIGEST.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return {"ok": True, "path": str(DIGEST), "lines": len(lines)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["record", "digest"])
    parser.add_argument("--capability", default="")
    parser.add_argument("--status", default="success")
    parser.add_argument("--note", default="")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    if args.action == "record":
        payload = record(args.capability, args.status, args.note)
    else:
        payload = digest(args.limit)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
