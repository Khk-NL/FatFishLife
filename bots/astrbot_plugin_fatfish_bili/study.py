"""按标签学习 B 站热门视频和评论区表达。

只读：搜索、看评论、统计高频说法，写进共享记忆的 style 类目。
不点赞、不评论、不关注。
"""

from __future__ import annotations

from fatfish_core.learning import extract_terms
from fatfish_core.growth import record_capability


async def study_tag(run, store, tag: str, *, seen: set[str], top_n: int = 3, min_count: int = 2) -> dict:
    payload = await run("search", "video", tag, "--order", "views", "--size", str(max(1, top_n)))
    if not payload.get("ok"):
        record_capability(store, "bili_learning", "failed", stage="search", error_code="service_error")
        return {"ok": False, "tag": tag, "videos": [], "terms": [], "comment_count": 0}
    items = (payload.get("data") or {}).get("items") or []
    videos, texts, failures = [], [], 0
    for item in items:
        bvid = str(item.get("bvid") or "")
        if not bvid or bvid in seen:
            continue
        videos.append(
            {
                "bvid": bvid,
                "title": str(item.get("title") or ""),
                "play": item.get("play"),
                "url": f"https://www.bilibili.com/video/{bvid}",
            }
        )
        comments = await run("comment", "list", bvid, "--sort", "hot")
        if comments.get("ok"):
            seen.add(bvid)
            rows = (comments.get("data") or {}).get("items") or []
            texts.extend(str(row.get("content") or "") for row in rows)
            for row in rows:
                for reply in row.get("replies_preview") or []:
                    texts.append(str(reply.get("content") or ""))
        else:
            failures += 1
    terms = extract_terms(texts, min_count=min_count)
    if terms:
        store.remember(
            f"B站「{tag}」评论区常见说法：" + "、".join(terms),
            platform="bilibili",
            scope="public",
            kind="style",
            actor="bot",
        )
    status = "failed" if failures else "success" if texts else "uncertain"
    record_capability(store, "bili_learning", status, stage="learn",
                      error_code="service_error" if failures else "no_result" if not texts else "")
    return {"ok": not failures, "tag": tag, "videos": videos, "terms": terms, "comment_count": len(texts)}
