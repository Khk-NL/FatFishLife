"""轻量心情状态：本地规则更新，不额外调用模型。

数值 0-100，50 为中性。被搭理、被夸会涨，被冷落、被呛会掉，
每小时向 50 回归一点，避免长期停在极端。
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

NEUTRAL = 50.0
DECAY_PER_HOUR = 6.0

LABELS = (
    (80.0, "很兴奋"),
    (62.0, "心情不错"),
    (42.0, "挺平静"),
    (24.0, "有点累"),
    (0.0, "蔫蔫的"),
)


def _now() -> float:
    return time.time()


def label_for(value: float) -> str:
    for threshold, label in LABELS:
        if value >= threshold:
            return label
    return LABELS[-1][1]


class MoodStore:
    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS mood("
                "scope TEXT PRIMARY KEY, value REAL NOT NULL, reason TEXT DEFAULT '', updated_at REAL NOT NULL)"
            )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _decayed(self, value: float, updated_at: float) -> float:
        hours = max(0.0, (_now() - updated_at) / 3600.0)
        if value > NEUTRAL:
            return max(NEUTRAL, value - DECAY_PER_HOUR * hours)
        return min(NEUTRAL, value + DECAY_PER_HOUR * hours)

    def get(self, scope: str = "global") -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, reason, updated_at FROM mood WHERE scope=?", (scope,)
            ).fetchone()
        if not row:
            return {"value": NEUTRAL, "label": label_for(NEUTRAL), "reason": ""}
        value = self._decayed(float(row[0]), float(row[2]))
        return {"value": round(value, 1), "label": label_for(value), "reason": row[1] or ""}

    def nudge(self, delta: float, reason: str = "", scope: str = "global") -> dict:
        current = self.get(scope)
        value = max(0.0, min(100.0, current["value"] + delta))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mood(scope, value, reason, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(scope) DO UPDATE SET value=excluded.value, reason=excluded.reason, updated_at=excluded.updated_at",
                (scope, value, reason[:120], _now()),
            )
        return {"value": round(value, 1), "label": label_for(value), "reason": reason}

    def describe(self, scope: str = "global") -> str:
        state = self.get(scope)
        if state["reason"]:
            return f"现在心情：{state['label']}（{state['reason']}）"
        return f"现在心情：{state['label']}"


def react_to(text: str, *, addressed: bool = False) -> float:
    """按一轮消息粗判情绪变化，纯本地规则。"""
    text = (text or "").strip()
    delta = 0.0
    if addressed:
        delta += 2.0
    if any(word in text for word in ("谢谢", "可爱", "喜欢", "厉害", "好棒", "哈哈")):
        delta += 4.0
    if any(word in text for word in ("滚", "闭嘴", "烦", "傻", "笨", "垃圾")):
        delta -= 5.0
    if any(word in text for word in ("难过", "累", "哭", "不开心")):
        delta -= 2.0
    if len(text) <= 3:
        delta -= 1.0
    return delta
