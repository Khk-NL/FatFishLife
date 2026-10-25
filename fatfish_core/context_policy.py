"""Bound multimodal history without converting encoded media into text tokens."""
from __future__ import annotations

import ast
import copy
import json
import re

DATA_URI = re.compile(r"data:(?:image|audio|video)/[^;\s]+;base64,[A-Za-z0-9+/=\r\n]+")
MEDIA_TYPES = {"image_url", "input_image", "input_audio", "audio_url", "video_url"}
OMITTED = "[较早图片或音频已省略，需细看时请重新发送]"
VOICE_DIRECTION = re.compile(r"(?m)^[ \t]*[\[【](?:语气|语速|音色|朗读提示)[：:][^\]\】\r\n]{1,160}[\]】][ \t]*\n?")
CONNECTION_FAILURE = re.compile(r"^\s*LLM\s*响应错误[：:]\s*All chat models failed:\s*(?:APIConnectionError|APITimeoutError):", re.I)


def clean_assistant_text(text: str) -> str:
    """Remove leaked delivery instructions, retaining the actual answer."""
    return VOICE_DIRECTION.sub("", str(text or "")).strip()


def is_connection_failure(text: str) -> bool:
    return bool(CONNECTION_FAILURE.match(str(text or "")))


def _legacy_parts(content):
    if not isinstance(content, str) or not content.lstrip().startswith(('[{"', "[{'")):
        return content, False
    if not any(kind in content for kind in MEDIA_TYPES) or len(content) > 2_097_152:
        return content, False
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        try:
            value = ast.literal_eval(content)
        except (ValueError, SyntaxError, TypeError, RecursionError):
            return content, False
    if isinstance(value, list) and all(isinstance(v, dict) for v in value):
        return value, True
    return content, False


def normalize_history(messages: list[dict], *, image_turns=1) -> tuple[list[dict], dict]:
    """Preserve text/tool rounds, remove old media and known synthetic self-checks."""
    result, stats = [], {"legacy_media":0, "media_removed":0, "synthetic_removed":0, "thought_removed":0,
                         "voice_direction_removed":0, "connection_failure_removed":0}
    skip_example_reply = False
    for original in messages:
        if not isinstance(original, dict):
            continue
        message = copy.deepcopy(original)
        content = message.get("content")
        if message.get("role") == "user" and content == "（系统自检：请报告当前情感状态）":
            skip_example_reply = True
            stats["synthetic_removed"] += 1
            continue
        if skip_example_reply:
            skip_example_reply = False
            if message.get("role") == "assistant" and "星绘的情感核心" in str(content):
                stats["synthetic_removed"] += 1
                continue
        if message.get("role") == "system" and "[PROTOCOL_ENFORCEMENT]" in str(content) and "INITIATING COGNITIVE" in str(content):
            stats["synthetic_removed"] += 1
            continue
        content, legacy = _legacy_parts(content)
        if legacy:
            stats["legacy_media"] += 1
            content = [part for part in content if part.get("type") not in MEDIA_TYPES] + [{"type":"text", "text":OMITTED}]
        if isinstance(content, str):
            content, count = DATA_URI.subn(OMITTED, content)
            stats["media_removed"] += count
            if message.get("role") == "assistant":
                if is_connection_failure(content) and not message.get("tool_calls"):
                    stats["connection_failure_removed"] += 1
                    continue
                content, count = VOICE_DIRECTION.subn("", content)
                stats["voice_direction_removed"] += count
                content, count = re.subn(r"<thought>.*?</thought>", "", content, flags=re.S)
                stats["thought_removed"] += count
                content = content.strip() or ("" if message.get("tool_calls") else "[旧自检过程已省略]")
        message["content"] = content
        result.append(message)
    media_messages = [i for i, message in enumerate(result) if isinstance(message.get("content"), list)
                      and any(part.get("type") in MEDIA_TYPES for part in message["content"] if isinstance(part, dict))]
    keep = set(media_messages[-max(0, image_turns):]) if image_turns > 0 else set()
    for index in media_messages:
        parts, kept_images = [], 0
        for part in result[index]["content"]:
            media = isinstance(part, dict) and part.get("type") in MEDIA_TYPES
            # Historical audio is already transcribed; retain at most one image
            # in each retained image turn. Current attachments are handled separately.
            if media and (index not in keep or part.get("type") not in {"image_url", "input_image"} or kept_images >= 1):
                stats["media_removed"] += 1
                continue
            if media:
                kept_images += 1
            parts.append(part)
        if len(parts) != len(result[index]["content"]):
            parts.append({"type":"text", "text":OMITTED})
        result[index]["content"] = parts
    return result, stats


def retrieval_budget(query: str) -> tuple[int, int]:
    """Small factual questions need fewer evidence fragments than comparisons."""
    complex_query = len(query) > 45 or any(word in query for word in ("为什么", "对比", "比较", "分别", "经过", "前因后果", "哪些活动"))
    return (5, 1400) if complex_query else (2, 700)
