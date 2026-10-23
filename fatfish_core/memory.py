"""SQLite-backed shared memory for the QQ and Bilibili bots.

Both platform adapters read and write the same database file. Private rows are
only returned to an owner; public rows can be used for content generation.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    session TEXT,
    actor TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_scope ON events(scope);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session);

CREATE TABLE IF NOT EXISTS personas (
    name TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS owners (
    platform TEXT NOT NULL,
    uid TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (platform, uid)
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT
);

CREATE TABLE IF NOT EXISTS journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journals_day ON journals(day);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # Earlier inbox snapshots included private messages under public scope.
            conn.execute(
                "UPDATE events SET scope='private' WHERE platform='bilibili' AND kind='inbox' AND scope='public'"
            )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def remember(
        self,
        content: str,
        *,
        platform: str = "system",
        scope: str = "private",
        kind: str = "message",
        session: str | None = None,
        actor: str | None = None,
        meta: dict | None = None,
        limit: int = 500,
    ) -> int:
        text = " ".join(str(content).split())
        if not text:
            raise ValueError("记忆内容不能为空")
        text = text[: max(20, limit)]
        if scope not in ("private", "public"):
            raise ValueError("scope 必须是 private 或 public")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO events(platform, scope, kind, session, actor, content, created_at, meta) VALUES (?,?,?,?,?,?,?,?)",
                (platform, scope, kind, session, actor, text, now(), json.dumps(meta or {}, ensure_ascii=False)),
            )
            return int(cursor.lastrowid or 0)

    def recall(
        self,
        query: str = "",
        *,
        scopes: tuple[str, ...] = ("public",),
        limit: int = 20,
        conversation: tuple[str, str] | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[dict]:
        # Keep legacy inbox snapshots out of public access even before a reload.
        where = ["NOT (platform='bilibili' AND kind='inbox' AND scope='public')"]
        params: list[str] = []
        if scopes:
            where.append("scope IN (" + ",".join("?" for _ in scopes) + ")")
            params.extend(scopes)
        if conversation is not None:
            where.append("(kind <> 'message' OR (platform=? AND session=?))")
            params.extend(conversation)
        if kinds is not None:
            where.append("kind IN (" + ",".join("?" for _ in kinds) + ")" if kinds else "0")
            params.extend(kinds)
        for token in str(query).split():
            where.append("content LIKE ?")
            params.append(f"%{token}%")
        sql = "SELECT id, platform, scope, kind, session, actor, content, created_at FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(str(max(1, min(100, int(limit)))))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def recent(
        self,
        *,
        scopes: tuple[str, ...] = ("public",),
        limit: int = 20,
        conversation: tuple[str, str] | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[dict]:
        return self.recall("", scopes=scopes, limit=limit, conversation=conversation, kinds=kinds)

    def set_persona(self, content: str, name: str = "default") -> None:
        text = str(content).strip()
        if not text:
            raise ValueError("人设不能为空")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO personas(name, content, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                (name, text, now()),
            )

    def get_persona(self, name: str = "default") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT content FROM personas WHERE name=?", (name,)).fetchone()
            return row["content"] if row else ""

    def add_owner(self, platform: str, uid: str, note: str = "") -> None:
        if not platform or not uid:
            raise ValueError("platform 和 uid 不能为空")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO owners(platform, uid, note, created_at) VALUES (?,?,?,?) ON CONFLICT(platform, uid) DO UPDATE SET note=excluded.note",
                (platform, str(uid), note, now()),
            )

    def owners(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT platform, uid, note, created_at FROM owners ORDER BY created_at")]

    def is_owner(self, platform: str, uid: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM owners WHERE platform=? AND uid=?", (platform, str(uid))).fetchone()
            return row is not None

    def add_summary(self, content: str, *, period: str = "", source: str = "") -> int:
        text = str(content).strip()
        if not text:
            raise ValueError("总结内容不能为空")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO summaries(period, content, created_at, source) VALUES (?,?,?,?)",
                (period, text, now(), source),
            )
            return int(cursor.lastrowid or 0)

    def summaries(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, period, content, created_at, source FROM summaries ORDER BY id DESC LIMIT ?",
                    (max(1, min(100, int(limit))),),
                ).fetchall()
            ]

    def add_journal(self, content: str, *, day: str = "", source: str = "") -> int:
        text = " ".join(str(content).split())
        if not text:
            raise ValueError("札记不能为空")
        day = day or datetime.now().astimezone().date().isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO journals(day, content, source, created_at) VALUES (?,?,?,?)",
                (day, text[:2000], source, now()),
            )
            return int(cursor.lastrowid or 0)

    def journals(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, day, content, source, created_at FROM journals ORDER BY id DESC LIMIT ?",
                    (max(1, min(100, int(limit))),),
                ).fetchall()
            ]

    def prune(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc).astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
            return int(cursor.rowcount)

    def stats(self) -> dict:
        with self._connect() as conn:
            events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            private = conn.execute("SELECT COUNT(*) AS n FROM events WHERE scope='private'").fetchone()["n"]
            public = conn.execute("SELECT COUNT(*) AS n FROM events WHERE scope='public'").fetchone()["n"]
            last = conn.execute("SELECT created_at FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "path": str(self.path),
            "events": events,
            "private": private,
            "public": public,
            "last_event": last["created_at"] if last else None,
            "persona_chars": len(self.get_persona()),
            "owners": len(self.owners()),
        }
