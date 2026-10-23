"""Repair the old path-keyed metadata using the installed manager's migrator.

No models are called. Original records, including removed files, remain in backup.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path


def normalize_legacy(data: dict, pack: Path) -> dict:
    if str(data.get("schema_version")) != "1":
        raise ValueError("此工具只迁移旧版 schema_version=1 的路径索引")
    result = dict(data, images={})
    for key, value in data["images"].items():
        relative = Path(value.get("relative_path") or key)
        source = (pack / relative if relative.parts[0] == "memes" else pack / "memes" / relative).resolve()
        if not source.is_relative_to((pack / "memes").resolve()):
            raise ValueError("图片记录路径越界")
        if not source.is_file():
            continue
        record = dict(value, content_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      relative_path=source.relative_to(pack).as_posix())
        result["images"][record["content_sha256"] + ":" + record["relative_path"]] = record
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--plugin", type=Path, required=True)
    args = parser.parse_args()
    pack = args.pack.resolve()
    path = pack / "semantic_metadata.json"
    original = json.loads(path.read_text(encoding="utf-8-sig"))
    normalized = normalize_legacy(original, pack)
    # Import only the manager's storage implementation, without starting its plugin.
    package = types.ModuleType("_meme_metadata_migration")
    package.__path__ = [str(args.plugin.resolve())]
    sys.modules[package.__name__] = package
    storage = importlib.import_module(package.__name__ + ".backend.semantic.storage")
    migrated = storage.migrate_legacy_metadata(
        normalized, storage.scan_images(pack), storage.load_category_descriptions(pack), pack.name,
    )
    backup = path.with_name(f"semantic_metadata.before-collection-{datetime.now():%Y%m%d-%H%M%S-%f}.json")
    shutil.copy2(path, backup)
    try:
        # Native saving validates the old file too; first repair its missing hashes.
        storage._write_json_atomic(path, normalized)
        storage.save_metadata(pack, migrated)
    except Exception:
        shutil.copy2(backup, path)
        raise
    verified = storage.load_metadata(pack)
    if verified.get("metadata_read_only"):
        raise RuntimeError("迁移后元数据验证失败，原文件已备份")
    print(json.dumps({"schema_version": verified["schema_version"], "records": len(verified["images"]),
                      "backup": str(backup)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
