"""从聊天记录里提取候选记忆。

分层：
- events(kind='message')  → 原始聊天记录，短期上下文，谁都能写
- candidates              → 过准入的候选，等审核
- memory_fts / verified   → 长期记忆，检索用

准入规则见 admission.py。这里只负责批量扫描、去重和晋升。
"""

from __future__ import annotations

from pathlib import Path

from .admission import classify
from .memory import MemoryStore

# 单次最多扫多少条，避免大表拖慢
SCAN_LIMIT = 500


def extract_candidates(store: MemoryStore, *, since_id: int = 0, limit: int = SCAN_LIMIT) -> dict:
    """扫描新的聊天记录，把够格的写进候选区。返回统计。"""
    stats = {"scanned": 0, "preference": 0, "claim": 0, "skipped": 0, "last_id": since_id}
    with store._connect() as conn:  # noqa: SLF001 - 同包内部使用
        rows = conn.execute(
            """
            SELECT id, content, actor, session, platform
            FROM events
            WHERE kind='message' AND scope='public' AND id > ?
            ORDER BY id LIMIT ?
            """,
            (since_id, limit),
        ).fetchall()

    for row in rows:
        stats["scanned"] += 1
        stats["last_id"] = int(row["id"])
        text = str(row["content"] or "")
        # 长段落多半是复制、转述或引用 bot 的话，不适合做记忆
        if len(text) > 120:
            stats["skipped"] += 1
            continue
        verdict = classify(
            text,
            speaker=str(row["actor"] or ""),
            group=str(row["session"] or ""),
        )
        if verdict is None or verdict.kind in ("banter", "chat"):
            stats["skipped"] += 1
            continue
        if verdict.kind == "claim":
            # 转述只进候选，不自动生效
            store.add_candidate(
                verdict.content,
                kind="claim",
                group_id=str(row["session"] or ""),
                speaker=str(row["actor"] or ""),
                confidence=0.3,
            )
            stats["claim"] += 1
        elif verdict.kind == "preference":
            cid = store.add_candidate(
                verdict.content,
                kind="preference",
                group_id=str(row["session"] or ""),
                speaker=str(row["actor"] or ""),
                confidence=0.9,
            )
            if cid:
                store.review_candidate(cid, "verified", "本人声明")
            stats["preference"] += 1
    return stats


def promote_repeated(store: MemoryStore, *, min_hits: int = 3, limit: int = 50) -> int:
    """同一候选在不同时间被反复命中，视为群文化，自动晋升。"""
    promoted = 0
    with store._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            """
            SELECT id, first_seen, last_seen FROM candidates
            WHERE status='candidate' AND kind='claim' AND hits >= ?
              AND substr(first_seen, 1, 10) <> substr(last_seen, 1, 10)
            LIMIT ?
            """,
            (min_hits, limit),
        ).fetchall()
    for row in rows:
        store.review_candidate(int(row["id"]), "verified", f"重复出现 {min_hits} 次以上")
        promoted += 1
    return promoted


def stats(store: MemoryStore) -> dict:
    with store._connect() as conn:  # noqa: SLF001
        def count(status: str) -> int:
            return int(
                conn.execute("SELECT COUNT(*) FROM candidates WHERE status=?", (status,)).fetchone()[0]
            )

        return {
            "candidate": count("candidate"),
            "verified": count("verified"),
            "rejected": count("rejected"),
        }
