"""Small JSON state for offline notifications, recent lines and the shared flag."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


class StateStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"
        self.offline_path = self.dir / "offline.json"
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"notified": {}, "recent": {}, "manual": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("notified", {})
            data.setdefault("recent", {})
            data.setdefault("manual", None)
            return data
        except (OSError, ValueError):
            return {"notified": {}, "recent": {}, "manual": None}

    def _save(self) -> None:
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, temporary = tempfile.mkstemp(dir=str(self.dir), prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @property
    def manual(self) -> str | None:
        value = self.data.get("manual")
        return value if value in ("on", "off") else None

    def set_manual(self, value: str | None) -> None:
        self.data["manual"] = value if value in ("on", "off") else None
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

    def publish_offline(self, offline: bool, *, reason: str | None = None, resume_at: datetime | None = None) -> None:
        payload = {
            "offline": bool(offline),
            "reason": reason,
            "resume_at": resume_at.isoformat(timespec="seconds") if resume_at else None,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        fd, temporary = tempfile.mkstemp(dir=str(self.dir), prefix=".offline-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.offline_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
