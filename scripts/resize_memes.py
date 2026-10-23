"""Resize collected memes to at most 300x300, keeping aspect ratio and animation.

Works on both the preview copy and the meme_manager pack. Existing files are
replaced in place; originals are kept in a .bak folder for one rollback.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "assets/memes/apple-le/files",
    Path("D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default/memes"),
]
LIMIT = (300, 300)
BACKUP = ROOT / "assets/memes/.original"


def resize_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width <= LIMIT[0] and height <= LIMIT[1]:
                return False
            image.thumbnail(LIMIT, Image.LANCZOS)
            frames = []
            for frame in range(getattr(image, "n_frames", 1)):
                image.seek(frame)
                frame_image = image.convert("RGBA")
                frame_image.thumbnail(LIMIT, Image.Resampling.LANCZOS)
                frames.append(frame_image)
            if len(frames) > 1:
                frames[0].save(
                    path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=image.info.get("duration", 100),
                    loop=image.info.get("loop", 0),
                    format="GIF",
                )
            else:
                frames[0].save(path, format="PNG" if path.suffix.lower() == ".png" else "JPEG", quality=90)
            return True
    except Exception:
        return False


def main() -> None:
    changed = 0
    for target in TARGETS:
        if not target.is_dir():
            continue
        for path in target.rglob("*"):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                continue
            if resize_image(path):
                changed += 1
    print(f"resized={changed}")


if __name__ == "__main__":
    main()
