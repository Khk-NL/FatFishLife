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
from uuid import uuid4
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from fatfish_core import MemoryStore  # noqa: E402
from fatfish_core.extract import (  # noqa: E402
    extract_candidates,
    promote_repeated,
    stats as candidate_stats,
)
from fatfish_core.tts import TTSConfig, TTSError, preflight as tts_preflight, synth_to_file  # noqa: E402
from fatfish_core import observe  # noqa: E402
from fatfish_core import bili  # noqa: E402
from fatfish_core import gallery  # noqa: E402
from fatfish_core.steam import SteamStore, SteamError, format_result as steam_format  # noqa: E402
from fatfish_core import local_llm  # noqa: E402
from fatfish_core.delivery import DeliveryPolicy  # noqa: E402

MAX_LIMIT = 50

server = MCPServer(
    name="fatfish-memory",
    instructions=(
        "苹果乐的共享记忆库。查询用 recall/search，写入用 remember；"
        "长期记忆分候选和已确认两种，未确认的内容不要当成事实讲。"
    ),
)

_store: MemoryStore | None = None
_delivery: DeliveryPolicy | None = None
_delivery_lock = Lock()


def delivery() -> DeliveryPolicy:
    global _delivery
    with _delivery_lock:
        if _delivery is None:
            path = Path(os.environ.get('FATFISH_BEHAVIOR_FILE') or Path(__file__).resolve().parents[2] / 'data/dsh/behavior.json')
            _delivery = DeliveryPolicy(json.loads(path.read_text(encoding='utf-8')))
    return _delivery


@server.tool(description="宿主内部最终回复的媒体概率决策；社交模型不得直接调用")
def delivery_prepare(scope: str, text: str, incoming: str = '') -> str:
    plan = delivery().prepare(scope, text, incoming)
    return _dump({key: plan[key] for key in ('id', 'voice', 'meme')})


@server.tool(description="宿主内部记录实际发送回执；生成、选中不等于已发送")
def delivery_finish(plan_id: str, replied: bool, voice_sent: bool = False, meme_sent: bool = False) -> str:
    return _dump(delivery().finish(plan_id, replied=replied, voice_sent=voice_sent, meme_sent=meme_sent))


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
    if _readonly() and os.environ.get('FATFISH_MEDIA_WRITE') != '1':
        return _dump({"ok": False, "error": "服务以只读模式启动"})
    body = str(text or "").strip()
    if not body:
        return _dump({"ok": False, "error": "文本为空"})
    try:
        config = TTSConfig.from_env()
        out_dir = Path(os.environ.get("FATFISH_TTS_DIR") or Path(__file__).resolve().parents[2] / "outputs/dsh-media/tts") / uuid4().hex
        path = synth_to_file(config, body, out_dir)
        return _dump({"ok": True, "path": str(path), "bytes": path.stat().st_size, "model": config.model})
    except TTSError as exc:
        observe.event("tts_failed", reason=str(exc))
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="TTS本地配置检查，不合成、不收费；不代表真实语音已验收")
def tts_check() -> str:
    try:
        return _dump(tts_preflight(TTSConfig.from_env()))
    except TTSError as exc:
        return _dump({"ok": False, "error": str(exc)})


# ---------- B 站（只读优先；写操作受 FATFISH_BILI_WRITE 控制） ----------

@server.tool(description="B 站登录态与 CLI 连通性检查")
def bili_check() -> str:
    try:
        data = bili.probe()
        data.pop("who", None)
        return _dump(data)
    except Exception as exc:  # noqa: BLE001
        return _dump({"ok": False, "error": type(exc).__name__})


@server.tool(description="搜索 B 站视频")
def bili_search(keyword: str, size: int = 5) -> str:
    try:
        result = bili.search(keyword, size=_limit(size, 5))
        items = (result.get("data") or {}).get("items") or []
        slim = [
            {"title": str(i.get("title"))[:80], "bvid": i.get("bvid"), "author": i.get("author") or i.get("owner")}
            for i in items[:10]
        ]
        return _dump({"ok": result.get("ok"), "items": slim})
    except bili.BiliError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="读一个 B 站视频的基本信息")
def bili_video(bvid: str) -> str:
    try:
        result = bili.video_info(bvid)
        data = result.get("data") or {}
        return _dump({
            "ok": result.get("ok"),
            "title": data.get("title"),
            "desc": str(data.get("desc") or "")[:300],
            "view": data.get("view"),
            "owner": data.get("owner"),
        })
    except bili.BiliError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="读视频字幕或 AI 总结，用于把攻略视频转成文字")
def bili_transcript(bvid: str) -> str:
    try:
        result = bili.video_transcript(bvid)
        data = result.get("data") or {}
        text = data.get("summary") or data.get("subtitle") or data.get("text") or ""
        return _dump({"ok": result.get("ok"), "chars": len(str(text)), "text": str(text)[:2000]})
    except bili.BiliError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="读视频热评，用于了解评论区表达")
def bili_comments(bvid: str, limit: int = 10) -> str:
    try:
        result = bili.comments(bvid)
        data = result.get("data") or {}
        rows = data.get("comments") or data.get("items") or []
        slim = [
            {"user": str((c.get("member") or {}).get("uname") or c.get("user") or "")[:20],
             "text": str(c.get("content") or c.get("message") or "")[:150]}
            for c in rows[: _limit(limit, 10)]
        ]
        return _dump({"ok": result.get("ok"), "comments": slim})
    except bili.BiliError as exc:
        return _dump({"ok": False, "error": str(exc)})


# ---------- Steam（只读价格查询） ----------

def _steam() -> SteamStore:
    return SteamStore(
        country=os.environ.get("FATFISH_STEAM_COUNTRY", "cn"),
        proxy=os.environ.get("FATFISH_STEAM_PROXY", ""),
        timeout=float(os.environ.get("FATFISH_STEAM_TIMEOUT", "20")),
    )


@server.tool(description="查 Steam 游戏当前区域价格，不需要 Web API Key")
def steam_price(query: str) -> str:
    try:
        result = _steam().lookup(query)
        return _dump({"ok": True, "text": steam_format(result), "data": result})
    except SteamError as exc:
        return _dump({"ok": False, "error": f"{exc}（代码 {exc.code}）"})
    except ValueError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="按名字搜 Steam 游戏，返回候选")
def steam_search(query: str, limit: int = 5) -> str:
    try:
        rows = _steam().search(query)[: _limit(limit, 5)]
        return _dump({"ok": True, "items": [{"appid": r.get("id"), "name": r.get("name")} for r in rows]})
    except SteamError as exc:
        return _dump({"ok": False, "error": f"{exc}（代码 {exc.code}）"})


# ---------- 图库 ----------

@server.tool(description="图库统计：总数、分类、多少张有描述")
def meme_stats() -> str:
    try:
        return _dump({"ok": True, **gallery.stats()})
    except RuntimeError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="按标签或描述找表情包")
def meme_find(query: str, limit: int = 3) -> str:
    try:
        hits = gallery.find(query, limit=_limit(limit, 3))
        return _dump({"ok": True, "items": [{"path": h["path"], "tags": h["tags"], "caption": h["caption"][:80]} for h in hits]})
    except RuntimeError as exc:
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="随机挑一张表情包，可按分类限定")
def meme_random(category: str = "") -> str:
    try:
        item = gallery.random_pick(category=category)
        return _dump({"ok": bool(item), **({"path": item["path"], "category": item["category"], "tags": item["tags"]} if item else {"error": "没有匹配的表情"})})
    except RuntimeError as exc:
        return _dump({"ok": False, "error": str(exc)})


# ---------- 本地模型（峰谷切换时的高峰通道） ----------

@server.tool(description="用本地模型回答，不走远程 API（高峰期省钱用）")
def local_chat(prompt: str, system: str = "") -> str:
    body = str(prompt or "").strip()
    if not body:
        return _dump({"ok": False, "error": "问题为空"})
    try:
        text = local_llm.chat(system, body)
        return _dump({"ok": True, "text": text[:800]})
    except local_llm.LocalLLMError as exc:
        observe.event("local_llm_failed", reason=str(exc))
        return _dump({"ok": False, "error": str(exc)})


@server.tool(description="本地模型连通性检查（MiniCPM 与 Ollama 分别报）")
def local_check() -> str:
    try:
        return _dump({"ok": True, "backends": local_llm.probe()})
    except Exception as exc:  # noqa: BLE001
        return _dump({"ok": False, "error": str(exc)})


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
