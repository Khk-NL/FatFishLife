"""统一检索：把四处独立存储（记忆库 / 知识库 / Obsidian / 群聊归档）按一次提问合并。

为什么单独成文件：MCP 服务里要 import mcp SDK，测试环境不一定装了；
把检索逻辑放这里，`python -m unittest` 就能直接跑，不用起 MCP。

四条来源各自独立，路径都能用环境变量覆盖：
- FATFISH_KB_DB        知识库（dsh-knowledge-base 的 kb.sqlite）
- FATFISH_OBSIDIAN_VAULT  Obsidian 库根目录
- FATFISH_GROUP_DB     群聊归档（dsh-im 的 group-history.sqlite）
- 记忆库由调用方传 memory_search 进来（避免这里依赖 MemoryStore）
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

DEFAULT_KB_DB = Path.home() / ".dsh" / "knowledge-base" / "kb.sqlite"
DEFAULT_VAULT = Path("D:/obsidian/vaults/SCSldr")
DEFAULT_GROUP_DB = Path.home() / ".dsh" / "integrations" / "dsh-im" / "group-history.sqlite"
OBSIDIAN_SCAN_LIMIT = 5000
MAX_LIMIT = 50


def _limit(value: Any, default: int = 3) -> int:
    try:
        return max(1, min(MAX_LIMIT, int(value)))
    except (TypeError, ValueError):
        return default


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else fallback


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def kb_rows(query: str, limit: int) -> list[dict]:
    path = _env_path("FATFISH_KB_DB", DEFAULT_KB_DB)
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, category, name, summary, source, updated_at FROM kb"
            " WHERE name LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\'"
            " OR payload LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\'"
            " ORDER BY updated_at DESC LIMIT ?",
            (_like(query),) * 4 + (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"source": "kb", "id": row[0], "category": row[1], "name": row[2],
         "summary": str(row[3] or "")[:200], "updated_at": row[5]}
        for row in rows
    ]


def obsidian_rows(query: str, limit: int) -> list[dict]:
    root = _env_path("FATFISH_OBSIDIAN_VAULT", DEFAULT_VAULT)
    if not root.is_dir():
        return []
    needle = query.casefold()
    hits: list[dict] = []
    scanned = 0
    for path in root.rglob("*.md"):
        if scanned >= OBSIDIAN_SCAN_LIMIT or len(hits) >= limit:
            break
        scanned += 1
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in path.name.casefold():
            hits.append({"source": "obsidian", "path": str(path.relative_to(root)),
                         "snippet": body[:120].replace("\n", " ")})
            continue
        index = body.casefold().find(needle)
        if index >= 0:
            start = max(0, index - 60)
            hits.append({"source": "obsidian", "path": str(path.relative_to(root)),
                         "snippet": body[start:index + 120].replace("\n", " ")})
    return hits[:limit]


def group_rows(query: str, limit: int) -> list[dict]:
    path = _env_path("FATFISH_GROUP_DB", DEFAULT_GROUP_DB)
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT sender_name, text, sent_at, group_id FROM messages"
            " WHERE text LIKE ? ESCAPE '\\' ORDER BY sent_at DESC LIMIT ?",
            (_like(query), limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"source": "group", "sender": row[0], "text": str(row[1] or "")[:200],
         "sent_at": row[2], "group_id": row[3]}
        for row in rows
    ]


def recall_all(
    query: str,
    limit: int = 3,
    *,
    memory_search: Callable[[str, int], list] | None = None,
) -> dict:
    """查四处，每个来源独立失败：一个库坏了不影响另外三个。"""
    term = str(query or "").strip()
    if not term:
        return {"error": "query 不能为空"}
    per = _limit(limit)
    checks: dict[str, Callable[[], list]] = {
        "kb": lambda: kb_rows(term, per),
        "obsidian": lambda: obsidian_rows(term, per),
        "group": lambda: group_rows(term, per),
    }
    if memory_search is not None:
        checks["memory"] = lambda: memory_search(term, per)
    sources: dict[str, Any] = {}
    for name, run in checks.items():
        try:
            rows = run()
            sources[name] = {"count": len(rows), "items": rows}
        except Exception as error:  # noqa: BLE001 - 单个源坏掉不该拖垮其他源
            sources[name] = {"count": 0, "error": type(error).__name__}
    return {"query": term, "sources": sources}
