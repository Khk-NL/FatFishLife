"""峰时攒下的消息，留到谷时（DeepSeek 便宜时段）一次性总结。

设计约束（用户 2026-11-01 要求）：
- 峰时只做最便宜的落盘：桥把入站消息按行追加到 data/dsh/peak-queue.jsonl，
  不调模型、不进内存、不占上下文。
- 谷时（12:05、18:05 这两个峰时刚结束的点）由控制层调用本脚本：
  读队列 → 调一次 DeepSeek 做总结 → 写记忆 / 成长 / 心情 / 日记 → 归档队列。
- 任何一步失败都不丢数据：队列只在全部写完后才归档并清空。

用法：
    python scripts/consolidate_peak.py --dry-run
    python scripts/consolidate_peak.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "dsh"
QUEUE = DATA_DIR / "peak-queue.jsonl"
ARCHIVE_DIR = DATA_DIR / "peak-archive"
MAX_CHARS = 6000          # 送进模型的正文上限，超了只保留最近的
MAX_ITEMS = 40


def read_queue(path: Path = QUEUE) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("text"):
            items.append(row)
    return items[-MAX_ITEMS:]


def clean_text(raw: object) -> str:
    """去掉 CQ 码（图片/表情的 URL 又长又没用）、链接和多余空白。"""
    text = str(raw or "")
    text = re.sub(r"\[CQ:[^\]]*\]", "[图]", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(items: list[dict]) -> str:
    """把队列压成给模型看的一小段文本；按时间正序，超长丢最早的。"""
    lines: list[str] = []
    total = 0
    for row in reversed(items):
        name = str(row.get("name") or row.get("userId") or "群友")[:12]
        where = "私聊" if str(row.get("chatId", "")).startswith("private:") else "群聊"
        text = clean_text(row.get("text"))[:120]
        if not text or text == "[图]":
            continue
        line = f"[{where}] {name}: {text}"
        if total + len(line) > MAX_CHARS:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(reversed(lines))


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".dsh" / ".credentials.yaml"
    if not path.exists():
        raise RuntimeError("找不到 DEEPSEEK_API_KEY")
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"DEEPSEEK_API_KEY\s*:\s*[\"']?([A-Za-z0-9_\-]+)", text)
    if not match:
        raise RuntimeError("凭据文件里没有 DEEPSEEK_API_KEY")
    return match.group(1)


SYSTEM = """你在替一只 QQ 群里的鲸鱼娘整理"峰时攒下没空看的消息"。
只输出一个 JSON 对象，键固定：
{"summary": "120 字以内的当天进展总结",
 "memories": [{"text": "值得长期记住的事实，80 字内", "scope": "public"}],
 "growth": ["她这次学到/用上的能力标识"],
 "mood_delta": 0,
 "mood_reason": "20 字内"}
要求：
- memories 只收真正值得记的（人的偏好、约定、重要事件），最多 5 条；没有就空数组。
- scope 用 public（群里公开说过的）或 private（只有老大私聊说过）。
- growth 只能从这些里挑：qzone bili_dynamic image_gen sticker voice_send memory_note web_lookup bili_lookup persona group_mode wallet peak_pricing。
- mood_delta 取 -6 到 6 的整数，表示这半天整体让她心情变好还是变差。
- 不要编造没出现过的信息；宁可为空。"""


def ask_model(text: str, *, timeout: int = 60) -> dict:
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={"content-type": "application/json", "authorization": "Bearer " + api_key()},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def apply_result(result: dict, day: str, *, dry_run: bool = False) -> dict:
    from fatfish_core import hub
    from fatfish_core.growth import CAPABILITIES, record_capability
    from fatfish_core.memory import MemoryStore

    db = hub.memory_db_path()
    if db is None:
        raise RuntimeError("FATFISH_MEMORY_DB 未设置")
    store = MemoryStore(db)

    written = {"memories": 0, "growth": 0, "mood": None, "journal": False}
    for item in (result.get("memories") or [])[:5]:
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        if not text:
            continue
        scope = "private" if item.get("scope") == "private" else "public"
        if dry_run:
            written["memories"] += 1
            continue
        store.remember(text[:200], platform="qq", scope=scope, kind="note",
                       actor="bot", admit=True)
        written["memories"] += 1

    for cap in (result.get("growth") or [])[:6]:
        cap = str(cap).strip()
        if cap not in CAPABILITIES:
            continue
        if not dry_run:
            record_capability(store, cap, "success", stage="use")
        written["growth"] += 1

    delta = result.get("mood_delta")
    if isinstance(delta, (int, float)) and delta:
        delta = max(-6.0, min(6.0, float(delta)))
        reason = str(result.get("mood_reason") or "峰时攒的消息总结")[:40]
        written["mood"] = delta
        if not dry_run:
            hub.mood_nudge(delta, reason)

    summary = re.sub(r"\s+", " ", str(result.get("summary") or "")).strip()
    if summary and not dry_run:
        hub.journal_write(day, f"[峰时汇总] {summary}", source="dsh")
        written["journal"] = True
    elif summary:
        written["journal"] = True
    return written


def archive(path: Path = QUEUE) -> Path | None:
    if not path.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / f"peak-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    path.replace(target)
    return target


def prune_archives(keep_days: int = 1) -> list[str]:
    """汇总完就清：只留最近 keep_days 天的归档，省存储。"""
    if keep_days < 0 or not ARCHIVE_DIR.exists():
        return []
    cutoff = time.time() - keep_days * 86400
    removed: list[str] = []
    for item in sorted(ARCHIVE_DIR.glob("peak-*.jsonl")):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
                removed.append(item.name)
        except OSError:
            continue
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--queue", default=str(QUEUE))
    parser.add_argument("--keep-days", type=int, default=1, help="归档保留天数（默认 1 天）")
    args = parser.parse_args()

    queue_path = Path(args.queue)
    items = read_queue(queue_path)
    if not items:
        print(json.dumps({"ok": True, "skipped": "empty-queue"}, ensure_ascii=False))
        return 0

    text = compact(items)
    day = time.strftime("%Y-%m-%d")
    try:
        result = ask_model(text)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, ValueError) as error:
        print(json.dumps({"ok": False, "error": f"模型调用失败：{error}", "items": len(items)},
                         ensure_ascii=False))
        return 1

    try:
        written = apply_result(result, day, dry_run=args.dry_run)
    except Exception as error:  # noqa: BLE001 —— 写库失败要原样报出来，且不归档
        print(json.dumps({"ok": False, "error": f"写库失败：{error}", "items": len(items)},
                         ensure_ascii=False))
        return 1

    # 模型返回空壳时不能归档，否则这批消息就白攒了。
    usable = written["memories"] or written["growth"] or written["journal"] or written["mood"]
    if not usable and not args.dry_run:
        print(json.dumps({"ok": False, "error": "模型没产出可用内容，队列保留", "items": len(items),
                          "summary": str(result.get("summary", ""))[:80]}, ensure_ascii=False))
        return 1

    summary = re.sub(r"\s+", " ", str(result.get("summary") or "")).strip()
    if summary and not args.dry_run:
        digest = DATA_DIR / "peak-digest.txt"
        digest.parent.mkdir(parents=True, exist_ok=True)
        digest.write_text(f"{time.strftime('%m-%d %H:%M')} 峰时攒下 {len(items)} 条：{summary[:300]}\n",
                          encoding="utf-8")

    moved = None if args.dry_run else archive(queue_path)
    removed = [] if args.dry_run else prune_archives(keep_days=args.keep_days)
    print(json.dumps({
        "ok": True, "items": len(items), "written": written,
        "archive": str(moved) if moved else None,
        "pruned": removed,
        "summary": str(result.get("summary", ""))[:200],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
