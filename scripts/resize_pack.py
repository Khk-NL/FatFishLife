"""安全缩放表情包目录到最大边 300，先写临时文件再替换，避免写坏原图。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image

EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_EDGE = 300


def _save(image: Image.Image, path: Path, fmt: str, **kwargs) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        image.save(tmp, format=fmt, **kwargs)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def resize_file(path: Path) -> bool:
    with Image.open(path) as im:
        width, height = im.size
        if max(width, height) <= MAX_EDGE:
            return False
        scale = MAX_EDGE / max(width, height)
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        fmt = im.format or path.suffix.lstrip(".").upper()
        if getattr(im, "is_animated", False):
            frames = []
            for index in range(im.n_frames):
                im.seek(index)
                frames.append(im.convert("RGBA").resize(size, Image.LANCZOS))
            _save(
                frames[0],
                path,
                fmt,
                save_all=True,
                append_images=frames[1:],
                loop=im.info.get("loop", 0),
                duration=im.info.get("duration", 100),
            )
        else:
            image = im.convert("RGBA" if fmt in {"PNG", "WEBP"} else "RGB")
            _save(image.resize(size, Image.LANCZOS), path, fmt)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    resized, failed = 0, []
    for path in args.root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        try:
            if resize_file(path):
                resized += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"file": str(path), "error": str(exc)[:120]})
    print(json.dumps({"resized": resized, "failed": failed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
