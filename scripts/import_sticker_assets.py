"""把 G 盘表情包素材里挑一部分导入 FatFishLife 本地图库（data/memes）。

策略：不整体搬 13G。只挑和"大肥鲸"人设相关或通用的几套，按体积阈值取样：
  鲸鱼娘（动图优先 + 小静图） 200 张
  贴吧表情                    全部 94 张
  doro                        100 张最小的
生成 semantic_metadata.json（按内容 sha1 作 key，字段 caption/tags/relative_path），
让 MCP 的 meme_find 能按分类/标签检索。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

SRC = Path(r"G:\素材╰(°▽°)╯\表情包大全（正在收录更新.....）全是up精心整理收集的")
ROOT = Path(r"D:\Code\Projects\FatFishLife\data\memes")
IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIX)


def take_small(paths: list[Path], limit: int) -> list[Path]:
    return sorted(paths, key=lambda p: p.stat().st_size)[:limit]


def main() -> None:
    plans: list[tuple[str, list[Path], list[str]]] = []

    whale_dirs = [p for p in SRC.iterdir() if p.is_dir() and "鲸鱼娘" in p.name]
    whale_files = [f for d in whale_dirs for f in files(d)]
    anim = [f for f in whale_files if f.suffix.lower() == ".gif"]
    still = [f for f in whale_files if f.suffix.lower() != ".gif" and f.stat().st_size <= 400_000]
    picked = take_small(anim, 120) + take_small(still, 80)
    plans.append(("鲸鱼娘", picked, ["鲸鱼娘", "大肥鱼", "表情"]))

    tieba = SRC / "贴吧表情包图片"
    if tieba.is_dir():
        plans.append(("贴吧", files(tieba)[:120], ["贴吧", "表情", "通用"]))

    doro = SRC / "doro表情包"
    if doro.is_dir():
        plans.append(("doro", take_small(files(doro), 100), ["doro", "表情", "通用"]))

    ROOT.mkdir(parents=True, exist_ok=True)
    meta_path = ROOT / "semantic_metadata.json"
    meta = {"images": {}}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.setdefault("images", {})
        except ValueError:
            meta = {"images": {}}

    total = 0
    for category, paths, tags in plans:
        target = ROOT / category
        target.mkdir(parents=True, exist_ok=True)
        for path in paths:
            data = path.read_bytes()
            digest = hashlib.sha1(data).hexdigest()
            name = f"{digest[:10]}{path.suffix.lower()}"
            dest = target / name
            if not dest.is_file():
                dest.write_bytes(data)
            extra = ["动图"] if path.suffix.lower() == ".gif" else ["静图"]
            meta["images"][digest] = {
                "caption": f"{category}表情",
                "tags": total_tags(category, tags, extra),
                "relative_path": f"{category}/{name}",
            }
            total += 1
        print(f"[import] {category}: {len(paths)} 个 -> {target}")

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[import] 共 {total} 张，metadata {len(meta['images'])} 条 -> {meta_path}")


def total_tags(category: str, tags: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    for item in [category, *tags, *extra]:
        if item not in out:
            out.append(item)
    return out


if __name__ == "__main__":
    main()
