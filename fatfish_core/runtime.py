"""Small cross-plugin state in the shared SQLite database.

The legacy JSON files are imported once and left untouched for rollback. Chat
engagement and short context stay in memory rather than becoming database rows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path


def resolve_shared_db(data_root: str | Path, configured: str | Path | None = None) -> Path:
    """Resolve the memory plugin's existing setting, including its old default."""
    override = os.environ.get("FATFISH_MEMORY_DB", "").strip()
    if override:
        return Path(override).expanduser()
    if configured and str(configured).strip():
        return Path(configured).expanduser()
    root = Path(os.environ.get("FATFISH_DATA_DIR") or data_root)
    config_path = root / "config" / "astrbot_plugin_fatfish_memory_config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        configured = str(config.get("db_path") or "").strip()
        if configured:
            return Path(configured).expanduser()
    return root / "plugin_data" / "astrbot_plugin_fatfish_memory" / "memory.db"


memory_db_path = resolve_shared_db


class RuntimeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS runtime_state (
                    namespace TEXT NOT NULL, key TEXT NOT NULL,
                    value TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, key)
                );
                CREATE TABLE IF NOT EXISTS seen_keys (
                    namespace TEXT NOT NULL, key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, key)
                );
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, namespace: str, key: str, default=None):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM runtime_state WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, namespace: str, key: str, value) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runtime_state VALUES (?,?,?,?) ON CONFLICT(namespace,key) "
                "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (namespace, key, payload, datetime.now().astimezone().isoformat(timespec="seconds")),
            )

    def merge(self, namespace: str, key: str, changes: dict) -> dict:
        """Merge owned fields atomically, preserving controls changed by another writer."""
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT value FROM runtime_state WHERE namespace=? AND key=?',
                                     (namespace, key)).fetchone()
            value = json.loads(row[0]) if row else {}
            value.update(changes)
            connection.execute(
                'INSERT INTO runtime_state VALUES (?,?,?,?) ON CONFLICT(namespace,key) '
                'DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (namespace, key, json.dumps(value, ensure_ascii=False), datetime.now().astimezone().isoformat(timespec='seconds')),
            )
        return value

    def import_json(self, namespace: str, key: str, source: str | Path, default=None):
        """Atomically initialize once; never replay an older JSON after a reload."""
        current = self.get(namespace, key)
        if current is not None:
            return current
        path = Path(source)
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO runtime_state VALUES (?,?,?,?)",
                (namespace, key, json.dumps(value, ensure_ascii=False), datetime.now().astimezone().isoformat(timespec="seconds")),
            )
        return self.get(namespace, key, default)


class SeenStore:
    """Bounded inbox reply deduplication, independent of public/private memories."""

    def __init__(self, path: str | Path, *, namespace: str = "bilibili", legacy_path: str | Path | None = None):
        self.runtime = RuntimeStore(path)
        self.namespace = namespace
        if legacy_path is not None and self.runtime.get(namespace, "seen_migrated") is None:
            path = Path(legacy_path)
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            self.save(self.load() | {str(key) for key in data.get("keys", [])})
            self.runtime.set(namespace, "seen_migrated", True)

    def load(self) -> set[str]:
        with self.runtime._connect() as connection:
            return {row[0] for row in connection.execute(
                "SELECT key FROM seen_keys WHERE namespace=?", (self.namespace,)
            )}

    def save(self, keys: set[str]) -> set[str]:
        keep = set(sorted(keys)[-500:]) if len(keys) > 800 else set(keys)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.runtime._connect() as connection:
            connection.execute("DELETE FROM seen_keys WHERE namespace=?", (self.namespace,))
            connection.executemany(
                "INSERT INTO seen_keys VALUES (?,?,?)", ((self.namespace, key, timestamp) for key in keep)
            )
        return keep


def read_offline(db_path: str | Path, legacy_path: str | Path | None = None) -> dict:
    """Read the unified signal; the old JSON is only a migration fallback."""
    runtime = _runtime_store(str(Path(db_path).resolve()))
    state = runtime.get("offline", "signal")
    if state is None and legacy_path is not None:
        state = runtime.import_json("offline", "signal", legacy_path, {})
    return state or {}


@lru_cache(maxsize=32)
def _runtime_store(path: str) -> RuntimeStore:
    return RuntimeStore(path)


def is_silent(db_path: str | Path) -> bool:
    """跨插件读取静默开关：只收不发，用于「暂停说话」。"""
    try:
        store = RuntimeStore(db_path)
        control = store.get("offline", "control", {}) or {}
        return bool(control.get("silent"))
    except Exception:
        return False
