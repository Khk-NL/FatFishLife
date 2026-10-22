"""Sticker library storage: no AstrBot imports, so it can be unit tested alone."""

from __future__ import annotations

import json
import random
import shutil
from datetime import datetime
from pathlib import Path


class StickerLibrary:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.images = self.base / "images"
        self.data_file = self.base / "library.json"
        self.images.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if self.data_file.exists():
            try:
                loaded = json.loads(self.data_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and "items" in loaded:
                    loaded.setdefault("next_id", 1)
                    return loaded
            except (OSError, ValueError):
                pass
        return {"next_id": 1, "items": {}}

    def save(self) -> None:
        self.data_file.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(
        self,
        source_path: Path | str,
        tags: list[str],
        approved: bool = False,
        source: str = "",
        added_by: str = "",
    ) -> dict:
        source_path = Path(source_path)
        sticker_id = str(self.data["next_id"])
        self.data["next_id"] = int(self.data["next_id"]) + 1
        suffix = source_path.suffix.lower() or ".png"
        target = self.images / f"{sticker_id}{suffix}"
        shutil.copy2(source_path, target)
        item = {
            "file": target.name,
            "tags": [tag.strip() for tag in tags if tag.strip()],
            "approved": bool(approved),
            "source": source,
            "added_by": str(added_by),
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.data["items"][sticker_id] = item
        self.save()
        return {"id": sticker_id, **item}

    def approve(self, sticker_id: str, tags: list[str] | None = None) -> dict | None:
        item = self.data["items"].get(str(sticker_id))
        if not item:
            return None
        item["approved"] = True
        if tags:
            item["tags"] = [tag.strip() for tag in tags if tag.strip()]
        self.save()
        return {"id": str(sticker_id), **item}

    def reject(self, sticker_id: str) -> bool:
        item = self.data["items"].pop(str(sticker_id), None)
        if not item:
            return False
        try:
            (self.images / item["file"]).unlink(missing_ok=True)
        except OSError:
            pass
        self.save()
        return True

    def approved(self) -> dict:
        return {key: value for key, value in self.data["items"].items() if value.get("approved")}

    def pending(self) -> dict:
        return {key: value for key, value in self.data["items"].items() if not value.get("approved")}

    def path(self, item: dict) -> Path:
        return self.images / item["file"]

    def pick(self, keyword: str = "") -> tuple[str, dict] | None:
        pool = self.approved()
        if not pool:
            return None
        if keyword:
            needle = keyword.lower()
            pool = {
                key: value
                for key, value in pool.items()
                if needle in " ".join(value.get("tags") or []).lower()
                or needle in value["file"].lower()
            }
            if not pool:
                return None
        sticker_id = random.choice(list(pool))
        return sticker_id, pool[sticker_id]
