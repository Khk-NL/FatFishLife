"""Prepare curated front-view model sheets as actual, separate transparent layers.

Source sheets are copied into assets/fronts/sources before running this script.
The crops below are in source pixels, not reused illustration avatars.
"""
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "assets/fronts"
PRESETS = {
    "1006": {"file": "silverwolf.jpg", "crop": [2202, 0, 2448, 326], "face": [.50, .675, .43, .36], "head_bottom": .88,
             "source": "https://x.com/DragaliaArchive/status/1652015595703943170"},
    "1005": {"file": "kafka.jpg", "crop": [872, 110, 1398, 748], "face": [.51, .64, .55, .38], "head_bottom": .85,
             "source": "https://www.miyoushe.com/sr/article/49604498"},
    "1205": {"file": "blade.jpg", "crop": [705, 137, 1277, 770], "face": [.51, .61, .52, .43], "head_bottom": .82,
             "source": "https://www.miyoushe.com/sr/article/49604498"},
    "1224": {"file": "march.jpg", "crop": [944, 155, 1480, 690], "face": [.51, .65, .51, .40], "head_bottom": .87,
             "source": "https://www.miyoushe.com/dby/article/56610386"},
}


def main():
    for key, preset in PRESETS.items():
        source = cv2.imdecode(np.frombuffer((FOLDER / "sources" / preset["file"]).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        left, top, right, bottom = preset["crop"]
        image = source[top:bottom, left:right].copy()
        height, width = image.shape[:2]
        # Only border-connected white is background: white hair and clothing survive.
        white = (np.min(image, axis=2) >= 243).astype(np.uint8)
        _, labels = cv2.connectedComponents(white)
        border_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        background = np.isin(labels, border_labels[border_labels != 0])
        alpha = np.where(background, 0, 255).astype(np.uint8)
        count, components, stats, _ = cv2.connectedComponentsWithStats((alpha > 0).astype(np.uint8))
        if count > 1:
            main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            alpha[components != main] = 0
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        image[:, :, 3] = alpha
        cx, cy, fw, fh = preset["face"]
        hole = np.zeros((height, width), np.uint8)
        cv2.ellipse(hole, (round(cx * width), round(cy * height)), (round(fw * width / 2), round(fh * height / 2)), 0, 0, 360, 255, -1)
        hair_mask = np.zeros_like(hole)
        hair_mask[:round(height * preset["head_bottom"])] = 255
        hair_mask[hole > 0] = 0
        hair = image.copy()
        hair[:, :, 3] = np.minimum(alpha, hair_mask)
        base = image.copy()
        base[:, :, 3] = np.where((hair_mask > 0) | (hole > 0), 0, alpha)
        for suffix, pixels in (("front", image), ("hair", hair), ("base", base)):
            ok, encoded = cv2.imencode(".png", pixels)
            if not ok:
                raise RuntimeError("PNG 编码失败")
            (FOLDER / f"{key}-{suffix}.png").write_bytes(encoded.tobytes())
        preset["size"] = [width, height]
    (FOLDER / "presets.json").write_text(json.dumps(PRESETS, ensure_ascii=False, indent=2), encoding="utf-8")
    catalog_path = ROOT / "assets/characters/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    for character in catalog["characters"]:
        preset = PRESETS.get(character["id"])
        if preset:
            character["front"] = {**preset, **{kind: f"/assets/fronts/{character['id']}-{kind}.png" for kind in ("front", "hair", "base")}}
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(PRESETS)} curated front-view model portraits and their layers.")


if __name__ == "__main__":
    main()
