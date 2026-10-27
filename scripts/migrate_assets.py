"""把 AstrBot 侧的资产整体搬到项目自己的数据根，之后不再依赖旧目录。

搬运清单：
    memory.db           记忆 + 候选 + 札记（SQLite 在线备份 API，不是 cp）
    memes/              表情包素材 + semantic_metadata.json
    knowledge/          公开设定资料（从 docs/knowledge 复制，保持独立可搬运）
    persona/            人设卡与完整角色卡

设计：
- 目标是 FatFishLife/data/，不写进 .git（.gitignore 已排除）
- 每个文件都算 sha256，输出清单，便于日后核对
- 已存在的目标文件不覆盖，除非 --force
- dry-run 只报告数量与体积

用法：
    python scripts/migrate_assets.py --dry-run
    python scripts/migrate_assets.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data"

SOURCES = {
    "memory.db": Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db"),
    "memes": Path("D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default/memes"),
    "meme_meta": Path("D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default/semantic_metadata.json"),
    "knowledge": ROOT / "docs/knowledge",
    "persona": ROOT / "docs/persona",
}

IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_db(source: Path, target: Path, *, force: bool) -> dict:
    """SQLite 在线备份：即使源正在被写也一致。"""
    if target.exists() and not force:
        return {"skipped": True, "reason": "exists"}
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    counts = {}
    conn = sqlite3.connect(target)
    try:
        for table in ("events", "candidates", "summaries", "journals", "blocks"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
    finally:
        conn.close()
    return {"skipped": False, "bytes": target.stat().st_size, "sha256": sha256(target), "counts": counts}


def copy_tree(source: Path, target: Path, *, force: bool, suffixes: set[str] | None = None) -> dict:
    if not source.is_dir():
        return {"skipped": True, "reason": "missing"}
    copied = 0
    kept = 0
    total = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(source)
        dest = target / rel
        if dest.exists() and not force:
            kept += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
        total += dest.stat().st_size
    return {"skipped": False, "copied": copied, "kept": kept, "bytes": total}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()

    target_root: Path = args.target
    report: dict = {"target": str(target_root), "dry_run": args.dry_run, "items": {}}

    if args.dry_run:
        for name, src in SOURCES.items():
            if src.is_dir():
                n = sum(1 for p in src.rglob("*") if p.is_file())
                size = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
                report["items"][name] = {"source": str(src), "files": n, "bytes": size}
            elif src.is_file():
                report["items"][name] = {"source": str(src), "bytes": src.stat().st_size}
            else:
                report["items"][name] = {"source": str(src), "missing": True}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    target_root.mkdir(parents=True, exist_ok=True)

    if SOURCES["memory.db"].is_file():
        report["items"]["memory.db"] = copy_db(SOURCES["memory.db"], target_root / "memory.db", force=args.force)
    else:
        report["items"]["memory.db"] = {"skipped": True, "reason": "missing"}

    report["items"]["memes"] = copy_tree(SOURCES["memes"], target_root / "memes", force=args.force, suffixes=IMAGE_SUFFIX)

    meta = SOURCES["meme_meta"]
    if meta.is_file():
        dest = target_root / "memes" / "semantic_metadata.json"
        if dest.exists() and not args.force:
            report["items"]["meme_meta"] = {"skipped": True, "reason": "exists"}
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(meta, dest)
            report["items"]["meme_meta"] = {"skipped": False, "bytes": dest.stat().st_size}

    report["items"]["knowledge"] = copy_tree(SOURCES["knowledge"], target_root / "knowledge", force=args.force)
    report["items"]["persona"] = copy_tree(SOURCES["persona"], target_root / "persona", force=args.force)

    (target_root / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
