"""Measured capability experience in the existing private memory event stream.

Only controlled labels are persisted. Tool arguments, transcripts, search terms,
credentials, URLs, exception messages and provider responses are never stored.
"""

from __future__ import annotations

import json
from collections import Counter

CAPABILITIES = {
    "group_style": "群聊表达学习",
    "tts": "语音表达", "stt": "语音理解", "bili_learning": "B站标签学习",
    "pixiv": "插画检索", "anysearch": "资料检索", "video_review": "视频创作与审核",
    "obsidian": "独立知识库", "meme_semantics": "表情语义", "steam": "游戏价格查询",
}
STATUSES = {"success": "成功", "failed": "失败", "uncertain": "待核验", "blocked": "待条件就绪"}
STAGES = {"setup", "auth", "use", "generate", "transcribe", "delivery", "search", "learn", "review", "publish", "sync"}
ERROR_CODES = {"authorization", "network", "service_error", "no_result", "unconfirmed", "not_configured", "awaiting_review"}
TOOL_CAPABILITIES = {
    "tts_speak": ("tts", "generate"),
    "anysearch_batch_search": ("anysearch", "search"),
    "anysearch_search": ("anysearch", "search"),
    "anysearch_extract": ("anysearch", "search"),
    "pixiv_search_illust": ("pixiv", "search"),
    "pixiv_search_novel": ("pixiv", "search"),
    "bili_watch": ("bili_learning", "learn"),
    "search_memes": ("meme_semantics", "search"),
}


def record_capability(store, capability: str, status: str, *, stage="use", error_code="") -> int:
    """Record an actual observation, never inferred skill levels or experience XP."""
    if capability not in CAPABILITIES or status not in STATUSES or stage not in STAGES:
        raise ValueError("未知能力、状态或阶段")
    # Free-form error text may contain credentials or private content.
    code = error_code if error_code in ERROR_CODES else ""
    return store.remember(
        f"能力经历：{CAPABILITIES[capability]}，{STATUSES[status]}（{stage}）。",
        platform="system", scope="private", kind="capability", actor="bot",
        meta={"capability": capability, "status": status, "stage": stage, "error_code": code},
    )


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def tool_outcome(result) -> tuple[str, str]:
    """Read explicit errors before accepting a completed tool result.

    A search completion does not prove delivery, publication or owner approval.
    None and empty results remain unconfirmed instead of manufacturing success.
    """
    if result is None:
        return "uncertain", "unconfirmed"
    if _field(result, "isError", False):
        return "failed", "service_error"
    structured = _field(result, "structuredContent")
    if isinstance(structured, dict) and structured.get("ok") is False:
        return "failed", "service_error"
    content = _field(result, "content", []) or []
    found = False
    for block in content:
        if _field(block, "type") != "text":
            found = True
            continue
        text = str(_field(block, "text", "")).strip()
        if not text:
            continue
        found = True
        lowered = text.lower()
        if lowered.startswith(("错误", "搜索失败", "api调用错误", "发送图片失败", "error:", "error：", "failed:")):
            return "failed", "service_error"
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and (payload.get("ok") is False or payload.get("isError") is True or payload.get("error")):
            return "failed", "service_error"
    return ("success", "") if found else ("uncertain", "unconfirmed")


def capability_summary(rows: list[dict]) -> list[dict]:
    """Summarize only private capability metadata; conversation text is ignored."""
    counts = Counter()
    for row in rows:
        if row.get("kind") != "capability" or row.get("scope") != "private":
            continue
        meta = row.get("meta") or {}
        if not isinstance(meta, dict):
            continue
        capability, status, stage = meta.get("capability"), meta.get("status"), meta.get("stage")
        if capability in CAPABILITIES and status in STATUSES and stage in STAGES:
            counts[(capability, status, stage)] += 1
    return [{"capability": capability, "name": CAPABILITIES[capability], "status": status, "stage": stage, "count": count}
            for (capability, status, stage), count in sorted(counts.items())]
