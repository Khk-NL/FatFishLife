"""按子目录分类导入用户整理的表情包，按内容哈希去重。

用法：
  python scripts/import_user_memes.py --source "G:/素材/applei" --target D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default
子目录名会去掉「表情包」后缀作为分类，例如「能天使表情包」-> 能天使。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def content_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_user_memes(source: Path, target: Path) -> dict:
    image_root = target / "memes"
    image_root.mkdir(parents=True, exist_ok=True)
    known = {
        content_digest(path)
        for path in image_root.rglob("*")
        if path.is_file() and path.suffix.lower() in EXTS
    }
    added, skipped, empty = [], [], []
    for category_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        category = category_dir.name.replace("表情包", "").strip() or category_dir.name
        for path in sorted(category_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in EXTS:
                continue
            raw = path.read_bytes()
            if not raw:
                empty.append(str(path))
                continue
            digest = hashlib.sha256(raw).hexdigest()
            if digest in known:
                skipped.append(str(path))
                continue
            dest = image_root / category / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = image_root / category / f"{digest[:8]}_{path.name}"
            dest.write_bytes(raw)
            known.add(digest)
            added.append(str(dest.relative_to(image_root)).replace("\\", "/"))
    return {"added": len(added), "skipped": len(skipped), "empty": len(empty), "categories": added}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_user_memes(args.source, args.target), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
