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


STOP_GRAMS = {
    "什么", "怎么", "这个", "那个", "就是", "不是", "可以", "一个", "现在", "还是",
    "已经", "因为", "所以", "但是", "如果", "然后", "这样", "那样", "我们", "你们",
    "他们", "自己", "知道", "觉得", "应该", "可能", "真的", "有点", "时候", "地方",
    "东西", "事情", "问题", "感觉", "一样", "这么", "那么", "多少", "为什", "么样",
    "么办", "有没", "没有", "是不", "不能", "不会", "不要", "能不", "我就", "你了",
}


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", str(text or ""))
    if len(clean) < 2:
        return {clean} if clean and clean not in STOP_GRAMS else set()
    return {
        clean[i : i + 2]
        for i in range(len(clean) - 1)
        if clean[i : i + 2] not in STOP_GRAMS
    }


def _score(query_grams: set[str], text: str) -> float:
    """重合度打分，除以长度平方根避免长句占便宜。"""
    if not query_grams:
        return 0.0
    grams = _bigrams(text)
    if not grams:
        return 0.0
    shared = len(query_grams & grams)
    if shared < 2:
        return 0.0
    return shared / (len(grams) ** 0.5 + 1)


def expression_patterns(limit: int = 200, *, conversation: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    """self_learning 提炼的「场景 → 表达」对。"""
    # Upstream has only group_id, so only a complete QQ group UMO can prove
    # attribution. Legacy bare group IDs cannot distinguish adapter instances.
    if not conversation or conversation[0] != "qq" or not re.fullmatch(r"[^:]+:GroupMessage:[^:]+", conversation[1]):
        return []
    conn = _connect(SELF_LEARNING_DB)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            select situation, expression
            from expression_patterns
            where group_id = ? and length(situation) between 2 and 40
              and length(expression) between 2 and 60
            order by rowid desc
            limit ?
            """,
            (conversation[1], limit),
        ).fetchall()
        return [(str(a).strip(), str(b).strip()) for a, b in rows if a and b]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def style_phrases(memory_db: Path, kind: str = "style", limit: int = 10, *, conversation: tuple[str, str] | None = None) -> list[str]:
    """共享记忆里按类别存的说法。"""
    if not conversation or not all(conversation):
        return []
    conn = _connect(memory_db)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            select content from events
            where kind = ? and platform = ? and session = ? and scope = 'public'
            order by created_at desc
            limit ?
            """,
            (kind, conversation[0], conversation[1], limit),
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


def build_style_block(
    memory_db: Path,
    query: str = "",
    *,
    max_items: int = 6,
    conversation: tuple[str, str] | None = None,
) -> str:
    """按当前消息挑最相关的几条说法；query 为空时取最近两条。"""
    if not conversation or not all(conversation):
        return ""
    query_grams = _bigrams(query)
    seen: set[str] = set()
    scored: list[tuple[float, str]] = []

    for situation, expression in expression_patterns(conversation=conversation):
        key = f"{situation[:20]}|{expression[:20]}"
        if key in seen:
            continue
        seen.add(key)
        # 场景和表达都参与匹配：对方原话可能只命中回复里的词
        score = max(_score(query_grams, situation), _score(query_grams, expression) * 0.8)
        scored.append(
            (score, f"- 对方说「{situation[:30]}」，可以接「{expression[:40]}」")
        )

    chat_phrases = style_phrases(memory_db, "style", 20, conversation=conversation)
    bili_phrases = style_phrases(memory_db, "bili_style", 20, conversation=conversation)
    tagged = [(p, "群里常出现") for p in chat_phrases] + [(p, "评论区常出现") for p in bili_phrases]
    for phrase, label in tagged:
        if len(phrase) > 30 or phrase in seen:
            continue
        seen.add(phrase)
        scored.append((_score(query_grams, phrase), f"- {label}：{phrase}"))

    if not scored:
        return ""

    hits = [text for score, text in sorted(scored, key=lambda x: -x[0]) if score > 0][:max_items]
    if not hits:
        # 没有相关说法就不注入，避免硬塞不相干的内容带偏语气
        return ""
    return HEADER + "\n".join(hits)


def stats(memory_db: Path) -> dict[str, Any]:
    """Aggregate counts for maintenance; no cross-session text is returned."""
    result = {"expression_patterns": 0, "style": 0, "bili_style": 0}
    for path, sql in (
        (SELF_LEARNING_DB, "SELECT 'expression_patterns',COUNT(*) FROM expression_patterns WHERE length(situation) BETWEEN 2 AND 40 AND length(expression) BETWEEN 2 AND 60"),
        (memory_db, "SELECT kind,COUNT(*) FROM events WHERE kind IN ('style','bili_style') GROUP BY kind"),
    ):
        conn = _connect(path)
        if conn is None:
            continue
        try:
            result.update({str(kind): int(count) for kind, count in conn.execute(sql)})
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return result
