"""按标签学习 B 站热门视频和评论区表达。

只读：搜索、看评论、统计高频说法，写进共享记忆的 style 类目。
不点赞、不评论、不关注。
"""

from __future__ import annotations

from fatfish_core.learning import extract_terms


async def study_tag(run, store, tag: str, *, seen: set[str], top_n: int = 3, min_count: int = 2) -> dict:
    payload = await run("search", "video", tag, "--order", "views", "--size", str(max(1, top_n)))
    if not payload.get("ok"):
        return {"tag": tag, "videos": [], "terms": [], "comment_count": 0}
    items = (payload.get("data") or {}).get("items") or []
    videos, texts = [], []
    for item in items:
        bvid = str(item.get("bvid") or "")
        if not bvid or bvid in seen:
            continue
        seen.add(bvid)
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
            rows = (comments.get("data") or {}).get("items") or []
            texts.extend(str(row.get("content") or "") for row in rows)
            for row in rows:
                for reply in row.get("replies_preview") or []:
                    texts.append(str(reply.get("content") or ""))
    terms = extract_terms(texts, min_count=min_count)
    if terms:
        store.remember(
            f"B站「{tag}」评论区常见说法：" + "、".join(terms),
            platform="bilibili",
            scope="public",
            kind="style",
            actor="bot",
        )
    return {"tag": tag, "videos": videos, "terms": terms, "comment_count": len(texts)}
