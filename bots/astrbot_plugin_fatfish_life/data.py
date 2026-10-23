"""Read daily activity and measured usage without loading conversation identities."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")


def _day(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(value) if isinstance(value, str) else value


def beijing_day_bounds(day: date | str) -> tuple[datetime, datetime]:
    """Return the Beijing half-open calendar-day window, including its timezone."""
    start = datetime.combine(_day(day), time.min, tzinfo=BEIJING)
    return start, start + timedelta(days=1)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间范围必须包含时区")
    return value.astimezone(timezone.utc)


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def events_between(
    db_path: str | Path,
    start: datetime,
    end: datetime,
    scopes: tuple[str, ...] = ("public",),
    limit: int = 200,
) -> list[dict]:
    """Read the latest selected events, in chronological order, with decoded metadata."""
    start_utc, end_utc = _utc(start), _utc(end)
    if not scopes or int(limit) <= 0 or end_utc <= start_utc:
        return []
    if any(scope not in ("public", "private") for scope in scopes):
        raise ValueError("scope 必须是 public 或 private")
    path = Path(db_path)
    if not path.is_file():
        return []
    placeholders = ",".join("?" for _ in scopes)
    with closing(_readonly(path)) as connection:
        if not _has_table(connection, "events"):
            return []
        rows = connection.execute(
            f"""
            SELECT id, platform, scope, kind, session, actor, content, created_at, meta
            FROM events
            WHERE julianday(created_at) >= julianday(?)
              AND julianday(created_at) < julianday(?)
              AND scope IN ({placeholders})
              AND NOT (platform='bilibili' AND kind='inbox' AND scope='public')
            ORDER BY julianday(created_at) DESC, id DESC LIMIT ?
            """,
            (start_utc.isoformat(), end_utc.isoformat(), *scopes, int(limit)),
        ).fetchall()
    result = []
    for row in reversed(rows):
        item = dict(row)
        try:
            metadata = json.loads(item["meta"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        item["meta"] = metadata if isinstance(metadata, dict) else {}
        result.append(item)
    return result


def upsert_daily_journal(
    db_path: str | Path,
    day: date | str,
    content: str,
    source: str = "daily-reflection",
) -> int:
    """Update one generated daily journal while leaving other sources untouched."""
    day_text = _day(day).isoformat()
    text = str(content).strip()
    source = str(source).strip()
    if not text or not source:
        raise ValueError("每日总结内容和来源不能为空")
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with closing(sqlite3.connect(path, timeout=15)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT id FROM journals WHERE day=? AND source=? ORDER BY id LIMIT 1",
            (day_text, source),
        ).fetchone()
        if existing is not None:
            journal_id = int(existing[0])
            connection.execute("UPDATE journals SET content=? WHERE id=?", (text, journal_id))
            return journal_id
        cursor = connection.execute(
            "INSERT INTO journals(day, content, source, created_at) VALUES (?,?,?,?)",
            (day_text, text, source, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        return int(cursor.lastrowid)


def read_usage(db_path: str | Path, start: datetime, end: datetime) -> dict:
    """Aggregate only actual provider counters; absent statistics are not zero usage."""
    start_utc, end_utc = _utc(start), _utc(end)
    result = {
        "available": False,
        "calls": 0,
        "input_other": 0,
        "input_cached": 0,
        "output": 0,
        "total": 0,
    }
    path = Path(db_path)
    if not path.is_file():
        return result
    # AstrBot's ProviderStat stores UTC in a timezone-naive DateTime column.
    bounds = tuple(value.replace(tzinfo=None).isoformat() for value in (start_utc, end_utc))
    with closing(_readonly(path)) as connection:
        if not _has_table(connection, "provider_stats"):
            return result
        row = connection.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(token_input_other), 0) AS input_other,
                   COALESCE(SUM(token_input_cached), 0) AS input_cached,
                   COALESCE(SUM(token_output), 0) AS output
            FROM provider_stats
            WHERE julianday(created_at) >= julianday(?)
              AND julianday(created_at) < julianday(?)
            """,
            bounds,
        ).fetchone()
    result.update({key: int(row[key]) for key in ("calls", "input_other", "input_cached", "output")})
    result["available"] = True
    result["total"] = result["input_other"] + result["input_cached"] + result["output"]
    return result


async def record_usage(context, provider, response, *, umo: str, agent_type: str) -> None:
    """Persist provider-reported tokens for a direct call outside AstrBot's agent runner."""
    usage = response.usage
    if usage is None:
        return
    await context.get_db().insert_provider_stat(
        umo=umo,
        provider_id=provider.meta().id,
        provider_model=provider.get_model(),
        status="error" if response.role == "err" else "completed",
        stats={
            "token_usage": {
                "input_other": usage.input_other,
                "input_cached": usage.input_cached,
                "output": usage.output,
            }
        },
        agent_type=agent_type,
    )
