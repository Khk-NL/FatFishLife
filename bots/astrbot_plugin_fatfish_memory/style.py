"""表达方式层：读取学到的说话风格，运行时拼进 prompt，不写库。

三个来源合并：
1. self_learning 的 expression_patterns（场景 → 表达，LLM 提炼）
2. 共享记忆里 kind='style' 的 n-gram 高频短语
3. B 站评论学到的表达（kind='bili_style'）
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

SELF_LEARNING_DB = Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_self_learning/messages.db")

HEADER = "\n\n【群友平时这么说话，参考语气，不要照抄也不要每次都用】\n"


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return None


def expression_patterns(limit: int = 6) -> list[tuple[str, str]]:
    """self_learning 提炼的「场景 → 表达」对。"""
    conn = _connect(SELF_LEARNING_DB)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            select situation, expression
            from expression_patterns
            where length(situation) between 2 and 40
              and length(expression) between 2 and 60
            order by rowid desc
            limit ?
            """,
            (limit,),
        ).fetchall()
        return [(str(a).strip(), str(b).strip()) for a, b in rows if a and b]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def style_phrases(memory_db: Path, kind: str = "style", limit: int = 10) -> list[str]:
    """共享记忆里按类别存的说法。"""
    conn = _connect(memory_db)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            select content from events
            where kind = ?
            order by created_at desc
            limit ?
            """,
            (kind, limit),
        ).fetchall()
        return [_strip_label(str(r[0])) for r in rows if r and str(r[0]).strip()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _strip_label(text: str) -> str:
    """去掉「群友最近常这样说：」这类前缀，只留说法本身。"""
    match = re.match(r"^[^：:]{0,20}[：:](.+)$", text)
    return (match.group(1) if match else text).strip()


def build_style_block(memory_db: Path, pairs_limit: int = 5, phrase_limit: int = 8) -> str:
    """拼成一段可直接追加到 system prompt 的文本，空则返回空串。"""
    lines: list[str] = []
    seen: set[str] = set()
    for situation, expression in expression_patterns(pairs_limit):
        key = f"{situation[:20]}|{expression[:20]}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- 对方说「{situation[:30]}」，可以接「{expression[:40]}」")
    for phrase in style_phrases(memory_db, "style", phrase_limit):
        if len(phrase) <= 30 and phrase not in seen:
            seen.add(phrase)
            lines.append(f"- 群里常出现：{phrase}")
    for phrase in style_phrases(memory_db, "bili_style", phrase_limit):
        if len(phrase) <= 30 and phrase not in seen:
            seen.add(phrase)
            lines.append(f"- 评论区常出现：{phrase}")
    if not lines:
        return ""
    return HEADER + "\n".join(lines[:16])


def stats(memory_db: Path) -> dict[str, Any]:
    """给 /记忆 或排查用。"""
    return {
        "expression_patterns": len(expression_patterns(50)),
        "style": len(style_phrases(memory_db, "style", 50)),
        "bili_style": len(style_phrases(memory_db, "bili_style", 50)),
    }
