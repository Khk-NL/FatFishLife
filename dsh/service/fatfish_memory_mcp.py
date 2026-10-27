"""FatFish 记忆 MCP 服务：用官方 mcp SDK（2.x 的 MCPServer），供 DSH 通过 dsh-mcp-client 接入。

设计约束（迁移方案 §3.2）：
- 数据库路径只从 FATFISH_MEMORY_DB 取，工具参数不能指定路径。
- 工具白名单固定，不接受任意 SQL 或表名。
- FATFISH_SERVICE_READONLY=1 时写工具直接拒绝。
- 所有工具返回 JSON 字符串，便于模型直接读。

启动：
    FATFISH_MEMORY_DB=<path> python dsh/service/fatfish_memory_mcp.py
DSH 侧（cordis.patch.yml）：
    - id: memory-fatfish
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: fatfish
        transport: stdio
        command: <dsh-python>\\Scripts\\python.exe
        args: ['dsh/service/fatfish_memory_mcp.py']
        env: { FATFISH_MEMORY_DB: '<path>' }
        cwd: !!js process.cwd()
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from fatfish_core import MemoryStore  # noqa: E402
from fatfish_core.extract import (  # noqa: E402
    extract_candidates,
    promote_repeated,
    stats as candidate_stats,
)
from fatfish_core.tts import TTSConfig, TTSError, probe as tts_probe, synth_to_file  # noqa: E402
from fatfish_core import observe  # noqa: E402

MAX_LIMIT = 50

server = MCPServer(
    name="fatfish-memory",
    instructions=(
        "苹果乐的共享记忆库。查询用 recall/search，写入用 remember；"
        "长期记忆分候选和已确认两种，未确认的内容不要当成事实讲。"
    ),
)

_store: MemoryStore | None = None


def store() -> MemoryStore:
    global _store
    if _store is None:
        value = os.environ.get("FATFISH_MEMORY_DB", "").strip()
        if not value:
            raise RuntimeError("FATFISH_MEMORY_DB 未设置")
        path = Path(value).expanduser()
        if not path.is_file():
            raise RuntimeError("记忆库文件不存在")
        _store = MemoryStore(path)
    return _store


def _readonly() -> bool:
    return os.environ.get("FATFISH_SERVICE_READONLY", "0").strip() == "1"


def _limit(value: Any, default: int = 10) -> int:
    try:
        return max(1, min(MAX_LIMIT, int(value)))
    except (TypeError, ValueError):
        return default


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


@server.tool(description="按关键词回忆共享记忆（当前会话或公开范围）")
def recall(query: str, scope: str = "public", limit: int = 5) -> str:
    scopes = ("public", "private") if scope == "private" else ("public",)
    rows = store().recall(query, scopes=scopes, limit=_limit(limit))
    return _dump(
        [
            {"content": r["content"], "kind": r["kind"], "scope": r["scope"], "at": r["created_at"]}
            for r in rows
        ]
    )


@server.tool(description="在已确认的长期记忆里检索，按群隔离")
def search(query: str, group_id: str = "", limit: int = 5) -> str:
    return _dump(store().search(query, group_id=group_id, limit=_limit(limit)))


@server.tool(description="列出最近的记忆条目")
def recent(scope: str = "public", limit: int = 10) -> str:
    scopes = ("public", "private") if scope == "private" else ("public",)
    rows = store().recent(scopes=scopes, limit=_limit(limit))
    return _dump([{"content": r["content"], "kind": r["kind"], "at": r["created_at"]} for r in rows])


@server.tool(description="读取记忆块，例如 persona（只读）")
def get_block(label: str = "persona") -> str:
    return _dump(store().get_block(label))


@server.tool(description="列出待审核或已确认的记忆候选")
def candidates(status: str = "candidate", limit: int = 15) -> str:
    return _dump(store().list_candidates(status, _limit(limit)))


@server.tool(description="记忆库状态：块列表与候选计数")
def stats() -> str:
    s = store()
    return _dump({"blocks": s.list_blocks(), "candidates": candidate_stats(s)})


@server.tool(description="记一条笔记（只读模式下会被拒绝）")
def remember(content: str, scope: str = "private", kind: str = "note", session: str = "") -> str:
    if _readonly():
        return _dump({"ok": False, "error": "服务以只读模式启动"})
    row_id = store().remember(
        content,
        platform="qq",
        scope=scope,
        kind=kind,
        session=session or None,
        admit=False,
    )
    return _dump({"ok": True, "id": row_id})


@server.tool(description="审核候选记忆：verified 通过，rejected 拒绝")
def review(candidate_id: int, status: str, note: str = "mcp") -> str:
    if _readonly():
        return _dump({"ok": False, "error": "服务以只读模式启动"})
    return _dump({"ok": store().review_candidate(int(candidate_id), status, note)})


@server.tool(description="从聊天记录里提取候选记忆并晋升重复项")
def extract(since_id: int = 0) -> str:
    if _readonly():
        return _dump({"ok": False, "error": "服务以只读模式启动"})
    result = extract_candidates(store(), since_id=int(since_id))
    result["promoted"] = promote_repeated(store())
    result["stats"] = candidate_stats(store())
    return _dump(result)


@server.tool(description="合成一句语音，返回音频文件路径与大小（不直接发送）")
def tts_speak(text: str) -> str:
    """只负责合成落盘；发不发送由调用方决定。"""
    if _readonly():
        return _dump({"ok": False, "error": "服务以只读模式启动"})
    body = str(text or "").strip()
    if not body:
        return _dump({"ok": False, "error": "文本为空"})
    if len(body) > 200:
        body = body[:200]
    try:
        config = TTSConfig.from_env()
        out_dir = Path(os.environ.get("FATFISH_TTS_DIR") or "outputs/tts")
        path = synth_to_file(config, body, out_dir)
        return _dump({"ok": True, "path": str(path), "bytes": path.stat().st_size, "model": config.model})
    except TTSError as exc:
        observe.event("tts_failed", reason=str(exc))
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="TTS 连通性检查，不落盘")
def tts_check() -> str:
    try:
        return _dump({"ok": True, **tts_probe(TTSConfig.from_env())})
    except TTSError as exc:
        return _dump({"ok": False, "error": str(exc)})


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
