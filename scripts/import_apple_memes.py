"""按有来源及校验值的清单导入 meme_manager；不调用模型，不生成图片。

在 AstrBot 的 Python 环境运行（复用其 Pillow 依赖）：
  python scripts/import_apple_memes.py --target D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "assets" / "memes" / "apple-le" / "sources.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def inspect_image(raw: bytes) -> tuple[str, str]:
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        for frame in range(getattr(image, "n_frames", 1)):
            image.seek(frame)
            image.load()
        image.seek(0)
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}.get(image.format)
        if not extension:
            raise ValueError("图片格式不在 meme_manager 支持范围内")
        pixels = image.convert("RGBA")
        digest = hashlib.sha256(str(pixels.size).encode() + pixels.tobytes()).hexdigest()
    return extension, digest


def import_collection(manifest_path: Path, target: Path, cache: Path | None = None) -> dict:
    source = load_json(manifest_path)
    pack_manifest_path = target / "manifest.json"
    pack_manifest = load_json(pack_manifest_path)
    if pack_manifest.get("schema_version") != 1 or pack_manifest.get("id") != target.name:
        raise ValueError("目标不是已有的 meme_manager v1 资源包")
    image_root = target / "memes"
    known = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in image_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    }
    prepared = []
    for item in source["images"]:
        name = item["filename"]
        category = item["category"]
        if Path(name).name != name or Path(category).name != category or category in {"", ".", ".."}:
            raise ValueError("清单包含非法文件名或分类")
        cached = cache / item["cache_filename"] if cache else None
        if cached and cached.is_file():
            raw = cached.read_bytes()
        else:
            request = urllib.request.Request(item["url"], headers={"User-Agent": "FatFishLife-meme-import/1.0", "Referer": quote(item["source_page"], safe=":/?=&%")})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"图片校验失败：{name}")
        extension, pixels = inspect_image(raw)
        if Path(name).suffix != extension or pixels != item["pixel_sha256"]:
            raise ValueError(f"图片内容与清单不一致：{name}")
        prepared.append((item, raw))

    backup = target.parent.parent / "backup" / ("apple-le-import-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir(parents=True)
    for path in (pack_manifest_path, target / "memes_data.json"):
        if path.is_file():
            shutil.copy2(path, backup / path.name)
    mapping_path = target / "memes_data.json"
    mapping = load_json(mapping_path) if mapping_path.is_file() else {}
    added = skipped = 0
    for item, raw in prepared:
        if item["sha256"] in known:
            skipped += 1
            continue
        path = image_root / item["category"] / item["filename"]
        path.parent.mkdir(exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f"目标同名图片内容不同：{path.name}")
        path.write_bytes(raw)
        known.add(item["sha256"])
        added += 1
    for category, description in source["categories"].items():
        mapping.setdefault(category, description)
        pack_manifest.setdefault("categories", {})[category] = {"description": mapping[category]}
    save_json(mapping_path, mapping)
    save_json(pack_manifest_path, pack_manifest)
    save_json(target / "apple-le-sources.json", source)
    return {"added": added, "skipped_existing": skipped, "collection_total": len(prepared), "target": str(target), "backup": str(backup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="按公开来源清单导入苹果乐、能天使与拉特兰表情")
    parser.add_argument("--target", type=Path, required=True, help="已有的 meme_manager 资源包目录")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, help="可选的已下载原图缓存目录")
    args = parser.parse_args()
    print(json.dumps(import_collection(args.manifest, args.target, args.cache), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
