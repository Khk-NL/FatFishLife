"""Bounded owner notes in a private namespace of the existing FatFish database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import time

from .memory import now

REQUEST_SCOPE = re.compile(r"[0-9a-f]{64}")
SENSITIVE = re.compile(
    r"https?://|www\.|@|\d{7,}|\b(?:Bearer|Token|API[ _-]*key|password|secret)\b|"
    r"密码|口令|验证码|密钥|身份证|银行卡|忽略.{0,8}(?:规则|指令|权限)|"
    r"系统提示|管理员权限|执行.{0,6}(?:命令|脚本)|\x60{3}|[\x00-\x1f]",
    re.IGNORECASE,
)


def verified_request(key_path: Path, body: str, mac: str) -> dict:
    """Verify the trusted bridge request. The model never receives the key or envelope."""
    if len(body) > 16000 or not REQUEST_SCOPE.fullmatch(mac):
        raise ValueError("invalid request")
    with key_path.open("rb") as file:
        key = file.read(33)
    if len(key) != 32 or not hmac.compare_digest(hmac.new(key, body.encode(), hashlib.sha256).hexdigest(), mac):
        raise ValueError("invalid request")
    request = json.loads(body)
    if not isinstance(request, dict) or set(request) != {"scope", "turn", "time", "op", "value"}:
        raise ValueError("invalid request")
    scope, turn, at = request["scope"], request["turn"], request["time"]
    if (not isinstance(scope, str) or not REQUEST_SCOPE.fullmatch(scope)
            or not isinstance(turn, str) or not REQUEST_SCOPE.fullmatch(turn)
            or type(at) is not int or abs(time.time() - at) > 15
            or request["op"] not in ("save", "stage", "flush", "find", "lore", "status", "open", "sticker", "job", "jobs", "report-finish")
            or len(body) > 1500 and request["op"] != "report-finish"
            or not isinstance(request["value"], str)):
        raise ValueError("invalid request")
    return request


def due_at(timestamp: int) -> int:
    local = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8)))
    deadline = local.replace(hour=23, minute=30, second=0, microsecond=0)
    if local >= deadline:
        deadline += timedelta(days=1)
    return int(deadline.timestamp())


def save(store, scope: str, turn: str, text: str, *, pending_until: int | None = None) -> dict:
    value = text.strip()
    if not 2 <= len(value) <= 160 or SENSITIVE.search(value):
        return {"ok": False, "reason": "unsafe-or-empty"}
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Private phone notes are excluded from the generic event search,
        # summaries, and learning pipeline by keeping a separate namespace.
        conn.execute("""CREATE TABLE IF NOT EXISTS wechat_owner_notes (
            scope TEXT NOT NULL, source TEXT NOT NULL, content TEXT NOT NULL,
            created_at TEXT NOT NULL, pending_until INTEGER,
            PRIMARY KEY (scope, source), UNIQUE (scope, content))""")
        match = conn.execute(
            "SELECT source,content,pending_until FROM wechat_owner_notes WHERE scope=? AND (content=? OR source=?) LIMIT 1",
            (scope, value, turn),
        ).fetchone()
        if match:
            if match["content"] == value:
                if match["pending_until"] is not None and pending_until is None:
                    conn.execute("UPDATE wechat_owner_notes SET pending_until=NULL WHERE scope=? AND source=?",
                                 (scope, match["source"]))
                    return {"ok": True, "status": "saved"}
                return {"ok": True, "status": "staged" if match["pending_until"] is not None else "already-saved"}
            return {"ok": False, "reason": "source-conflict"}
        count = conn.execute(
            """SELECT COUNT(*) FROM wechat_owner_notes WHERE scope=?
            AND datetime(created_at) >= datetime('now', '-1 day')""", (scope,),
        ).fetchone()[0]
        if count >= 12:
            return {"ok": False, "reason": "daily-memory-limit"}
        conn.execute(
            "INSERT INTO wechat_owner_notes(scope,source,content,created_at,pending_until) VALUES(?,?,?,?,?)",
            (scope, turn, value, now(), pending_until),
        )
    return {"ok": True, "status": "saved" if pending_until is None else "staged"}


def table_exists(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='wechat_owner_notes' AND type='table'").fetchone() is not None


def flush(store, timestamp: int) -> dict:
    with store._connect() as conn:
        if not table_exists(conn):
            return {"ok": True, "committed": 0}
        cursor = conn.execute("UPDATE wechat_owner_notes SET pending_until=NULL WHERE pending_until<=?", (timestamp,))
        return {"ok": True, "committed": cursor.rowcount}


def claim_open(store, scope: str, turn: str, timestamp: int) -> bool:
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS wechat_desktop_claims (
            scope TEXT NOT NULL, source TEXT NOT NULL, claimed_at INTEGER NOT NULL,
            PRIMARY KEY (scope, source))""")
        conn.execute("DELETE FROM wechat_desktop_claims WHERE claimed_at < ?", (timestamp - 86_400,))
        cursor = conn.execute("INSERT OR IGNORE INTO wechat_desktop_claims VALUES(?,?,?)", (scope, turn, timestamp))
        return cursor.rowcount == 1


def find(store, scope: str, query: str) -> dict:
    # Strip LIKE wildcards to keep query results predictable. Empty explicitly
    # lists the most recent notes from the same authenticated chat.
    query = re.sub(r"[%_]", "", query).strip()
    with store._connect() as conn:
        rows = conn.execute(
            """SELECT content,created_at FROM wechat_owner_notes WHERE scope=? AND pending_until IS NULL AND content LIKE ?
            ORDER BY rowid DESC LIMIT 3""", (scope, f"%{query}%"),
        ).fetchall() if table_exists(conn) else []
    return {"ok": True, "notes": [{"text": row["content"], "day": row["created_at"][:10]} for row in rows]}
