"""Plain chat text and presentation-only repetition compression."""
from __future__ import annotations

import json
import re
from datetime import datetime


def clean_chat_text(value) -> str:
    """Remove explicit transport placeholders, never guess where a literal @ ends."""
    text = str(value or "")
    text = re.sub(r"\[CQ:(?:at|reply|image|record|video|face|poke)(?:,[^\]\r\n]*)?\]", " ", text, flags=re.I)
    text = re.sub(r"\[At:(?:\d+|all|全体成员)\]", " ", text, flags=re.I)
    text = re.sub(r"(?<!\S)@\d+(?=\s|$|[\u4e00-\u9fff，,。!！?？:：;；])", " ", text)
    text = re.sub(r"\[(?:图片|语音|视频|表情包|转发|转发消息|合并消息|合并转发|引用消息|表情(?::[^\]\r\n]+)?)\]", " ", text)
    text = re.sub(r"\[(?:Image|Record|Video|Face|Forward|Merge)\]", " ", text, flags=re.I)
    return " ".join(text.split())


def event_chat_text(event) -> str:
    """Read Plain components only when a real message chain is available."""
    message = getattr(event, "message_obj", None)
    raw = getattr(message, "raw_message", None)
    if isinstance(raw, dict) and raw.get("post_type") in {"notice", "request", "meta_event"}:
        return ""
    components = getattr(message, "message", None)
    if isinstance(components, (list, tuple)) and components:
        parts = []
        for component in components:
            if isinstance(component, dict):
                if component.get("type") == "text":
                    parts.append(str((component.get("data") or {}).get("text") or ""))
            elif type(component).__name__ == "Plain":
                parts.append(str(getattr(component, "text", "") or ""))
        return clean_chat_text(" ".join(parts))
    return clean_chat_text(getattr(event, "message_str", ""))


def recorded_chat_text(row) -> str:
    """Read plain text, including the prior version's structured-text metadata."""
    try:
        meta = json.loads(row.get("meta") or "{}")
    except (TypeError, ValueError):
        meta = {}
    if isinstance(meta, dict) and isinstance(meta.get("plain_text"), str):
        return clean_chat_text(meta["plain_text"])
    return clean_chat_text(row.get("content", ""))


def collapse_chat_repeats(rows):
    """Collapse adjacent equal chat records within exactly one permission scope.

    Source rows remain untouched. Intervening records, including non-message
    kinds or messages that clean to empty, break a repetition run. A run spans
    at most five minutes; the same greeting on another day is not a chorus.
    """
    result = []
    for original in rows:
        row = dict(original)
        row.pop("actor", None)
        row.pop("_actors", None)
        if row.get("kind") != "message":
            result.append(row)
            continue
        row["content"] = recorded_chat_text(row)
        row["repeat_count"] = 1
        previous = result[-1] if result else None
        key = lambda item: tuple(item.get(k) for k in ("platform", "scope", "session", "kind", "content"))
        within_window = False
        if previous:
            try:
                first_at = datetime.fromisoformat(previous.get("first_at", previous["created_at"]))
                within_window = 0 <= (datetime.fromisoformat(row["created_at"]) - first_at).total_seconds() <= 300
            except (KeyError, TypeError, ValueError):
                pass
        if row["content"] and previous and previous.get("kind") == "message" and key(previous) == key(row) and within_window:
            previous["repeat_count"] += 1
            previous["id"] = row["id"]
            previous.setdefault("first_at", previous["created_at"])
            previous["created_at"] = row["created_at"]
        else:
            result.append(row)
    return result
