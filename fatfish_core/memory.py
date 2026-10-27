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
from .chat_text import clean_chat_text
from .admission import classify

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

-- Letta 风格的 memory block：label / value / limit / read_only
CREATE TABLE IF NOT EXISTS blocks (
    label TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    char_limit INTEGER,
    read_only INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    updated_at TEXT NOT NULL
);

-- 候选记忆：先入库待审，通过后才算长期记忆
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT,
    speaker TEXT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    confidence REAL NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status, kind);
CREATE INDEX IF NOT EXISTS idx_candidates_dedupe ON candidates(group_id, kind, content);

-- One source message is one observation, even after retries or restarts.
-- No sender or message body is copied into this evidence ledger.
CREATE TABLE IF NOT EXISTS candidate_sources (
    event_id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_sources_candidate ON candidate_sources(candidate_id);

-- 中文检索：trigram 支持 3 字以上子串匹配，2 字靠 LIKE/别名兜底
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    kind UNINDEXED,
    group_id UNINDEXED,
    ref_id UNINDEXED,
    tokenize='trigram'
);
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
            # Candidate attribution must survive expiry of the source event.
            # Older rows are bound only when every surviving ledger entry can
            # prove one public platform/session; missing evidence stays unbound.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(candidates)")}
            migrated = False
            for column in ("platform", "scope"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE candidates ADD COLUMN {column} TEXT")
                    migrated = True
            if migrated:
                rows = conn.execute(
                    """SELECT c.id, MIN(e.platform) AS platform
                       FROM candidates c JOIN candidate_sources s ON s.candidate_id=c.id
                       LEFT JOIN events e ON e.id=s.event_id
                       GROUP BY c.id
                       HAVING COUNT(*)=COUNT(e.id) AND COUNT(DISTINCT e.platform)=1
                         AND MIN(e.platform)<>'' AND MIN(e.scope)='public' AND MAX(e.scope)='public'
                         AND COUNT(e.session)=COUNT(*) AND MIN(e.session)=c.group_id AND MAX(e.session)=c.group_id"""
                ).fetchall()
                conn.executemany("UPDATE candidates SET platform=?,scope='public' WHERE id=?",
                                 [(row["platform"], row["id"]) for row in rows])
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_conversation ON candidates(platform,group_id,scope,status)")
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

    def get_block(self, label: str) -> dict | None:
        """读取一个 memory block（Letta 风格）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT label, value, char_limit, read_only, description, updated_at FROM blocks WHERE label=?",
                (label,),
            ).fetchone()
            return dict(row) if row else None

    def set_block(
        self,
        label: str,
        value: str,
        *,
        char_limit: int | None = None,
        read_only: bool = False,
        description: str | None = None,
        force: bool = False,
    ) -> bool:
        """写入 memory block。read_only 的块只有 force=True 才能改。"""
        text = str(value or "")
        if not text.strip():
            raise ValueError("block 内容不能为空")
        if char_limit:
            text = text[:char_limit]
        with self._lock, self._connect() as conn:
            current = conn.execute(
                "SELECT read_only FROM blocks WHERE label=?", (label,)
            ).fetchone()
            if current and int(current["read_only"]) and not force:
                raise PermissionError(f"block `{label}` 是只读的，需要 force=True 才能修改")
            conn.execute(
                """
                INSERT INTO blocks(label, value, char_limit, read_only, description, updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(label) DO UPDATE SET
                    value=excluded.value,
                    char_limit=excluded.char_limit,
                    read_only=excluded.read_only,
                    description=COALESCE(excluded.description, blocks.description),
                    updated_at=excluded.updated_at
                """,
                (
                    label,
                    text,
                    char_limit,
                    1 if read_only else 0,
                    description,
                    now(),
                ),
            )
            return True

    def list_blocks(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT label, length(value) AS chars, char_limit, read_only FROM blocks ORDER BY label"
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 候选记忆：candidate → verified ----------

    def add_candidate(
        self,
        content: str,
        *,
        kind: str,
        group_id: str = "",
        speaker: str = "",
        confidence: float = 0.0,
        source_event_id: int | None = None,
    ) -> int:
        """写入候选；有来源ID时同一原消息只计一次，重放返回0。"""
        text = " ".join(str(content or "").split())[:300]
        if not text:
            return 0
        stamp = now()
        platform, scope = "", ""
        with self._lock, self._connect() as conn:
            if source_event_id is not None:
                if not group_id:
                    raise ValueError("候选来源缺少会话归属")
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM candidate_sources WHERE event_id=?", (source_event_id,)).fetchone():
                    return 0
                source = conn.execute(
                    "SELECT created_at,platform,scope FROM events WHERE id=? AND kind='message' AND scope='public' AND session=?",
                    (source_event_id, group_id),
                ).fetchone()
                if source is None:
                    raise ValueError("候选来源必须属于当前公开会话")
                stamp = str(source["created_at"])
                platform, scope = str(source["platform"]), str(source["scope"])
                if conn.execute(
                    "SELECT 1 FROM candidates WHERE group_id=? AND kind=? AND content=? "
                    "AND COALESCE(platform,'')='' AND status IN ('rejected','verified') LIMIT 1",
                    (group_id, kind, text),
                ).fetchone():
                    return 0  # New attribution must not bypass an old manual decision.
            row = conn.execute(
                "SELECT id, hits FROM candidates WHERE group_id=? AND kind=? AND content=? "
                "AND COALESCE(platform,'')=? AND COALESCE(scope,'')=?",
                (group_id, kind, text, platform, scope),
            ).fetchone()
            if row:
                candidate_id = int(row["id"])
                if source_event_id is not None:
                    conn.execute("INSERT INTO candidate_sources VALUES (?,?,?)", (source_event_id, candidate_id, stamp))
                conn.execute(
                    "UPDATE candidates SET hits=hits+1, first_seen=MIN(first_seen,?), last_seen=MAX(last_seen,?), confidence=MAX(confidence,?) WHERE id=?",
                    (stamp, stamp, confidence, candidate_id),
                )
                return candidate_id
            cursor = conn.execute(
                """
                INSERT INTO candidates(group_id, speaker, kind, content, status, confidence, hits, first_seen, last_seen,platform,scope)
                VALUES (?,?,?,?,'candidate',?,1,?,?,?,?)
                """,
                (group_id, speaker, kind, text, confidence, stamp, stamp, platform, scope),
            )
            candidate_id = int(cursor.lastrowid or 0)
            if source_event_id is not None:
                conn.execute("INSERT INTO candidate_sources VALUES (?,?,?)", (source_event_id, candidate_id, stamp))
            return candidate_id

    def recall_verified(self, terms, *, conversation: tuple[str, str] | None,
                        scopes: tuple[str, ...] = ("public",), limit: int = 6) -> list[dict]:
        """Bounded, attributed long-term recall for the normal context builder.

        Candidate extraction currently accepts only public source events. Private
        permission alone never broadens this query to another conversation.
        """
        if not conversation or not all(conversation) or "public" not in scopes:
            return []
        tokens = sorted({str(term) for term in terms if str(term)})[:32]
        if not tokens:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,content,kind,group_id AS session,platform,scope,last_seen AS created_at "
                "FROM candidates WHERE status='verified' AND platform=? AND group_id=? AND scope='public' AND ("
                + " OR ".join("content LIKE ?" for _ in tokens) + ") ORDER BY last_seen DESC,id DESC LIMIT ?",
                (*conversation, *(f"%{term}%" for term in tokens), max(1,min(40,int(limit)))),
            ).fetchall()
            return [{**dict(row), "verified": True} for row in rows]

    def review_candidate(self, candidate_id: int, status: str, note: str = "", *, automatic: bool = False) -> bool:
        if status not in ("verified", "rejected", "candidate"):
            raise ValueError("status 必须是 candidate / verified / rejected")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE candidates SET status=?, review_note=? WHERE id=?" + (" AND status='candidate'" if automatic else ""),
                (status, note, candidate_id),
            )
            if cur.rowcount:
                # Review and FTS are one write transaction. A second connection
                # cannot write while this UPDATE holds SQLite's writer lock.
                conn.execute("DELETE FROM memory_fts WHERE ref_id=?", (candidate_id,))
            if status == "verified" and cur.rowcount:
                row = conn.execute(
                    "SELECT group_id, kind, content, speaker FROM candidates WHERE id=?",
                    (candidate_id,),
                ).fetchone()
                if row:
                    self._index(conn, row["content"], row["kind"], row["group_id"], candidate_id)
            return bool(cur.rowcount)

    def list_candidates(self, status: str = "candidate", limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, group_id, speaker, kind, content, confidence, hits, first_seen, status
                FROM candidates WHERE status=? ORDER BY hits DESC, last_seen DESC LIMIT ?
                """,
                (status, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def _index(self, conn: sqlite3.Connection, content: str, kind: str, group_id: str, ref_id: int) -> None:
        conn.execute(
            "INSERT INTO memory_fts(content, kind, group_id, ref_id) VALUES (?,?,?,?)",
            (content, kind, group_id, ref_id),
        )

    def rebuild_candidate_index(self) -> int:
        """Repair legacy missing/duplicate/stale rows without changing reviews."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM memory_fts")
            conn.execute(
                """INSERT INTO memory_fts(content, kind, group_id, ref_id)
                   SELECT content, kind, group_id, id FROM candidates
                   WHERE status='verified'"""
            )
            return int(conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])

    def search(
        self,
        query: str,
        *,
        group_id: str = "",
        limit: int = 5,
    ) -> list[dict]:
        """FTS5 检索；查询不足 3 字时退化为 LIKE。"""
        text = " ".join(str(query or "").split())
        if not text:
            return []
        with self._connect() as conn:
            if len(text) >= 3:
                try:
                    rows = conn.execute(
                        """
                        SELECT content, kind, group_id, ref_id
                        FROM memory_fts
                        WHERE memory_fts MATCH ? AND (? = '' OR group_id = ?)
                        ORDER BY rank LIMIT ?
                        """,
                        (text, group_id, group_id, limit),
                    ).fetchall()
                    if rows:
                        return [dict(r) for r in rows]
                except sqlite3.Error:
                    pass
            rows = conn.execute(
                """
                SELECT content, kind, group_id, id AS ref_id
                FROM candidates
                WHERE status='verified' AND content LIKE ? AND (? = '' OR group_id = ?)
                ORDER BY hits DESC LIMIT ?
                """,
                (f"%{text}%", group_id, group_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

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
        admit: bool = False,
    ) -> int:
        # 群聊消息先过准入：只有「值得记」的类型才落库，且按来源改写内容
        if admit and kind == "message" and scope == "public":
            verdict = classify(content, speaker=str(actor or ""), group=str(session or ""))
            if verdict is None or verdict.kind in ("banter", "chat"):
                return 0
            if verdict.kind == "claim":
                # 转述只能进候选，等人工审核，不进长期记忆
                self.add_candidate(
                    verdict.content,
                    kind="claim",
                    group_id=str(session or ""),
                    speaker=str(actor or ""),
                    confidence=0.3,
                )
                return 0
            if verdict.kind == "preference":
                # 本人声明可信度高，直接晋升
                candidate_id = self.add_candidate(
                    verdict.content,
                    kind="preference",
                    group_id=str(session or ""),
                    speaker=str(actor or ""),
                    confidence=0.9,
                )
                if candidate_id:
                    self.review_candidate(candidate_id, "verified", "本人声明", automatic=True)
            content = verdict.content
            kind = verdict.kind
            meta = {**(meta or {}), "admission": verdict.kind, "confident": verdict.confident}
            actor = None
        if kind == "message":
            # Chat memory is deliberately sender-free. Keep only its cleaned
            # body, time and conversation boundary, even for other adapters.
            content = meta.get("plain_text", content) if isinstance(meta, dict) else content
            content = clean_chat_text(content)
            if scope == "public" and actor and actor != "bot":
                content = content.replace(str(actor), "某人")
            actor, meta = None, {}
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
        conversation_only: bool = False,
    ) -> list[dict]:
        # Keep legacy inbox snapshots out of public access even before a reload.
        where = ["NOT (platform='bilibili' AND kind='inbox' AND scope='public')"]
        params: list[str] = []
        if scopes:
            where.append("scope IN (" + ",".join("?" for _ in scopes) + ")")
            params.extend(scopes)
        if conversation_only and (conversation is None or not all(conversation)):
            where.append("0")
        elif conversation is not None:
            where.append("(platform=? AND session=?)" if conversation_only else
                         "(kind <> 'message' OR (platform=? AND session=?))")
            params.extend(conversation)
        if kinds is not None:
            where.append("kind IN (" + ",".join("?" for _ in kinds) + ")" if kinds else "0")
            params.extend(kinds)
        for token in str(query).split():
            where.append("content LIKE ?")
            params.append(f"%{token}%")
        sql = "SELECT id, platform, scope, kind, session, actor, content, created_at, meta FROM events"
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
        conversation_only: bool = False,
    ) -> list[dict]:
        return self.recall("", scopes=scopes, limit=limit, conversation=conversation, kinds=kinds,
                           conversation_only=conversation_only)

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

    def summaries(self, limit: int = 10, *, source: str | None = None) -> list[dict]:
        where = " WHERE source=?" if source is not None else ""
        params = (() if source is None else (source,)) + (max(1, min(100, int(limit))),)
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, period, content, created_at, source FROM summaries" + where + " ORDER BY id DESC LIMIT ?",
                    params,
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

    def journals(self, limit: int = 10, *, source: str | None = None) -> list[dict]:
        where = " WHERE source=?" if source is not None else ""
        params = (() if source is None else (source,)) + (max(1, min(100, int(limit))),)
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, day, content, source, created_at FROM journals" + where + " ORDER BY id DESC LIMIT ?",
                    params,
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
