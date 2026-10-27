"""Create a private, verified baseline without changing either running bot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

EXCLUDED = {"node_modules", "cache", "temp", "logs", "runtime_logs", "dist", "private-config-backups", "__pycache__"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def files(root: Path):
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name not in EXCLUDED
            and not (Path(current) / name).is_symlink()
            and not (Path(current) / name).is_junction()
        )
        for name in sorted(names):
            source = Path(current) / name
            if not source.is_symlink() and not source.is_junction():
                yield source


def copy_verified(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream:
        sqlite = stream.read(16) == b"SQLite format 3\x00"
    if sqlite:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
            with closing(sqlite3.connect(destination)) as backup:
                live.backup(backup)
                backup.execute("pragma journal_mode=DELETE")
                if backup.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite backup failed integrity check")
        return {"kind": "sqlite_snapshot", "bytes": destination.stat().st_size, "sha256": digest(destination)}
    for _ in range(3):
        before = source.stat()
        shutil.copy2(source, destination)
        copied_hash = digest(destination)
        live_hash = digest(source)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and copied_hash == live_hash:
            return {"kind": "file", "bytes": after.st_size, "sha256": copied_hash}
    raise RuntimeError("Source remained busy; rerun baseline after writes settle")


def snapshot(roots: dict[str, Path], destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    report = {"created_at": datetime.now().astimezone().isoformat(), "roots": {}, "excluded": sorted(EXCLUDED), "files": []}
    for label, root in roots.items():
        root = root.resolve(strict=True)
        report["roots"][label] = str(root)
        for source in files(root):
            # SQLite's backup API includes committed WAL pages; copying sidecars
            # beside the new consistent snapshot would reintroduce stale state.
            if source.name.endswith(("-wal", "-shm", "-journal")):
                continue
            relative = source.relative_to(root)
            record = copy_verified(source, destination / label / relative)
            report["files"].append({"root": label, "relative_path": str(relative), **record})
    report["complete"] = True
    (destination / "manifest.private.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsh-home", type=Path, default=Path.home() / ".dsh")
    parser.add_argument("--astrbot-data", type=Path, default=Path("D:/Code/Apps/AstrBot/data"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[1] / "outputs/dsh-migration" / datetime.now().strftime("baseline-%Y%m%d-%H%M%S")
    report = snapshot({"dsh": args.dsh_home, "legacy_data": args.astrbot_data}, output)
    print(json.dumps({"complete": report["complete"], "files": len(report["files"]), "sqlite_snapshots": sum(row["kind"] == "sqlite_snapshot" for row in report["files"]), "backup_directory": str(output)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
