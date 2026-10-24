"""按标签学习 B 站热门视频和评论区表达。

只读：标题、标签、简介、已有字幕和评论，统计高频说法。
复用 bili-cli 的纯文本模式；不抽帧、不下载音频、不调用 ASR。
不点赞、不评论、不关注。
"""

from __future__ import annotations

from fatfish_core.learning import extract_terms
from fatfish_core.growth import record_capability


async def read_video_text(run, video_id: str, *, comments=5, max_chars=3000) -> dict:
    """Use the installed CLI's explicit subtitle-only/no-frames path."""
    payload = await run("video", "watch", video_id, "--frames", "0", "--transcript", "subtitle",
                        "--comments", str(comments), "--max-chars", str(max_chars), timeout=120)
    if not payload.get("ok"):
        return payload
    source = payload.get("data") or {}
    data = {key: source.get(key) for key in ("bvid", "title", "desc", "url", "tags", "ai_summary", "summary", "hot_comments")}
    transcript = source.get("transcript") or {}
    subtitle = str(transcript.get("source") or "").startswith("subtitle:")
    data["transcript"] = {"source": transcript.get("source") if subtitle else None,
                          "text": str(transcript.get("text") or "")[:max_chars] if subtitle else ""}
    # Ignore any old frame paths, ASR transcripts or CLI recommendations to
    # download/transcribe when captions are unavailable.
    return {"ok": True, "data": data}


async def study_tag(run, store, tag: str, *, seen: set[str], top_n: int = 3, min_count: int = 2) -> dict:
    payload = await run("search", "video", tag, "--order", "views", "--size", str(max(1, top_n)))
    if not payload.get("ok"):
        record_capability(store, "bili_learning", "failed", stage="search", error_code="service_error")
        return {"ok": False, "tag": tag, "videos": [], "terms": [], "comment_count": 0}
    items = (payload.get("data") or {}).get("items") or []
    videos, texts, failures, text_reads = [], [], 0, 0
    for item in items:
        bvid = str(item.get("bvid") or "")
        if not bvid or bvid in seen:
            continue
        payload = await read_video_text(run, bvid)
        if not payload.get("ok"):
            failures += 1
            continue
        data = payload.get("data") or {}
        title = str(data.get("title") or item.get("title") or bvid)
        videos.append(
            {
                "bvid": bvid,
                "title": title,
                "play": item.get("play"),
                "url": f"https://www.bilibili.com/video/{bvid}",
            }
        )
        seen.add(bvid)
        text_reads += 1
        rows = data.get("hot_comments") or []
        texts.extend(str(row.get("content") or "") for row in rows)
        transcript = data.get("transcript") or {}
        tags = "、".join(str(value) for value in (data.get("tags") or [])[:12])
        excerpt = str(transcript.get("text") or data.get("ai_summary") or data.get("desc") or "")[:350]
        store.remember(f"读取B站文字资料《{title}》\n来源：https://www.bilibili.com/video/{bvid}\n标签：{tags}\n文字摘录：{excerpt}",
                       platform="bilibili", scope="public", kind="video", limit=800,
                       meta={"source":"bili_text", "bvid":bvid, "subtitle_available":bool(transcript.get("text"))})
    terms = extract_terms(texts, min_count=min_count)
    if terms:
        store.remember(
            f"B站「{tag}」评论区常见说法：" + "、".join(terms),
            platform="bilibili",
            scope="public",
            kind="style",
            actor="bot",
        )
    status = "failed" if failures else "success" if text_reads else "uncertain"
    record_capability(store, "bili_learning", status, stage="learn",
                      error_code="service_error" if failures else "no_result" if not text_reads else "")
    return {"ok": not failures, "tag": tag, "videos": videos, "terms": terms, "comment_count": len(texts), "text_reads":text_reads}
