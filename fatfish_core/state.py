"""Persistent offline control state and cross-platform signal in shared SQLite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .runtime import RuntimeStore


class StateStore:
    def __init__(self, directory: Path, *, db_path: str | Path | None = None):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        # Legacy paths remain available for one-time import and rollback only.
        self.path = self.dir / "state.json"
        self.offline_path = self.dir / "offline.json"
        self.runtime = RuntimeStore(db_path or self.dir / "state.db")
        self.data = self.runtime.import_json(
            "offline", "control", self.path,
            {"notified": {}, "recent": {}, "manual": None},
        )
        self.data.setdefault("notified", {})
        self.data.setdefault("recent", {})
        self.data.setdefault("manual", None)
        self.runtime.import_json("offline", "signal", self.offline_path, {})

    def _save(self) -> None:
        self.runtime.set("offline", "control", self.data)

    @property
    def manual(self) -> str | None:
        value = self.data.get("manual")
        return value if value in ("on", "off") else None

    def set_manual(self, value: str | None) -> None:
        self.data["manual"] = value if value in ("on", "off") else None
        self._save()

    @property
    def silent(self) -> bool:
        """闭麦：只收不发。独立于 manual，不受高峰时段影响。"""
        data = self.data or {}
        return bool(data.get("silent"))

    def set_silent(self, value: bool) -> None:
        if self.data is None:
            self.data = {}
        self.data["silent"] = bool(value)
        self._save()

    def notified_today(self, group: str, day: str) -> bool:
        return self.data.get("notified", {}).get(group) == day

    def mark_notified(self, group: str, day: str) -> None:
        self.data.setdefault("notified", {})[group] = day
        # Keep only the most recent groups to avoid unbounded growth.
        if len(self.data["notified"]) > 500:
            self.data["notified"] = dict(list(self.data["notified"].items())[-300:])
        self._save()

    def recent_lines(self, group: str) -> list[str]:
        return list(self.data.get("recent", {}).get(group, []))

    def add_recent(self, group: str, line: str) -> None:
        recent = self.data.setdefault("recent", {}).setdefault(group, [])
        recent.append(line)
        self.data["recent"][group] = recent[-6:]
        self._save()

    def usage_count(self, hour_key: str) -> int:
        usage = self.data.get("usage") or {}
        return int(usage.get("count", 0)) if usage.get("hour") == hour_key else 0

    def bump_usage(self, hour_key: str) -> int:
        usage = self.data.get("usage") or {}
        if usage.get("hour") != hour_key:
            usage = {"hour": hour_key, "count": 0}
        usage["count"] = int(usage.get("count", 0)) + 1
        self.data["usage"] = usage
        self._save()
        return usage["count"]

    def ambient_state(self, group: str) -> dict:
        return dict((self.data.get("ambient") or {}).get(group) or {})

    def record_ambient(self, group: str, day: str, timestamp: float) -> None:
        ambient = self.data.setdefault("ambient", {})
        current = ambient.get(group) or {}
        count = int(current.get("count", 0)) if current.get("day") == day else 0
        ambient[group] = {"day": day, "count": count + 1, "last": timestamp}
        if len(ambient) > 500:
            self.data["ambient"] = dict(list(ambient.items())[-300:])
        self._save()

    def daily_apple_pie_state(self) -> dict:
        return dict(self.data.get("daily_apple_pie") or {})

    def set_daily_apple_pie_state(self, state: dict) -> None:
        self.data["daily_apple_pie"] = dict(state)
        self._save()

    def publish_offline(self, offline: bool, *, reason: str | None = None, resume_at: datetime | None = None) -> None:
        payload = {
            "offline": bool(offline),
            "reason": reason,
            "resume_at": resume_at.isoformat(timespec="seconds") if resume_at else None,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.runtime.set("offline", "signal", payload)
