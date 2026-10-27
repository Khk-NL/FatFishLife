"""图库业务：表情包索引、按标签检索、随机挑选。

素材格式沿用 meme_manager 的目录结构：
    <root>/memes/<分类>/<文件>
    <root>/semantic_metadata.json   # {"images": {entry_id: {caption, tags}}}

迁移时把整个 memes 目录与 metadata 一起搬，索引按需重建。
不依赖 AstrBot：只读文件系统，不加载插件。
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
STOP = {"的", "了", "是", "在", "和", "就", "都", "也", "很", "有", "我", "你", "他", "她"}


def root() -> Path:
    value = os.environ.get("FATFISH_MEME_ROOT", "").strip()
    if not value:
        raise RuntimeError("FATFISH_MEME_ROOT 未设置")
    path = Path(value).expanduser()
    if not path.is_dir():
        raise RuntimeError(f"图库目录不存在：{path}")
    return path


def _metadata(root_dir: Path) -> dict:
    path = root_dir / "semantic_metadata.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("images") or {}


def _memes_dir(base: Path) -> Path:
    """兼容两种布局：<root>/memes/<分类>/ 或 <root>/<分类>/。"""
    nested = base / "memes"
    return nested if nested.is_dir() else base


def images(root_dir: Path | None = None) -> list[dict]:
    """列出所有图片，带上分类与描述。"""
    base = root_dir or root()
    memes = _memes_dir(base)
    if not memes.is_dir():
        return []
    meta = _metadata(base)
    # metadata 的 key 是内容哈希，按路径反查需要扫描时比对文件名
    by_name: dict[str, dict] = {}
    for value in meta.values():
        if isinstance(value, dict):
            name = value.get("relative_path") or ""
            if name:
                by_name[Path(str(name)).name] = value

    out = []
    for path in sorted(memes.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIX:
            continue
        info = by_name.get(path.name) or {}
        out.append(
            {
                "path": str(path),
                "category": path.parent.name,
                "name": path.stem,
                "bytes": path.stat().st_size,
                "caption": str(info.get("caption") or ""),
                "tags": list(info.get("tags") or []),
            }
        )
    return out


def _terms(text: str) -> set[str]:
    return {t for t in re.split(r"[\s,，。、]+", str(text or "")) if len(t) >= 2 and t not in STOP}


def find(query: str, *, limit: int = 5, root_dir: Path | None = None) -> list[dict]:
    """按标签/描述/文件名检索，得分 = 命中词数。"""
    words = _terms(query)
    if not words:
        return []
    scored = []
    for item in images(root_dir):
        haystack = f"{item['name']} {item['category']} {item['caption']} {' '.join(item['tags'])}"
        score = sum(1 for w in words if w in haystack)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[: max(1, min(20, limit))]]


def random_pick(*, category: str = "", root_dir: Path | None = None) -> dict | None:
    pool = images(root_dir)
    if category:
        pool = [i for i in pool if i["category"] == category]
    return random.choice(pool) if pool else None


def stats(root_dir: Path | None = None) -> dict:
    items = images(root_dir)
    by_cat: dict[str, int] = {}
    for item in items:
        by_cat[item["category"]] = by_cat.get(item["category"], 0) + 1
    return {
        "total": len(items),
        "categories": by_cat,
        "described": sum(1 for i in items if i["caption"]),
        "broken": sum(1 for i in items if i["bytes"] == 0),
    }
