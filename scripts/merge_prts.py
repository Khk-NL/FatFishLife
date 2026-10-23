"""把 docs/knowledge/prts 下的散文件合并成少数几个大文件，减少知识库碎块。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "prts"

GROUPS = {
    "01-世界观与地理.md": [
        "泰拉大典_Index", "泰拉大典_地理", "泰拉大典_组织", "泰拉人种与地理",
        "泰拉大典_地理_乌萨斯", "泰拉大典_地理_维多利亚", "泰拉大典_地理_莱塔尼亚",
        "泰拉大典_地理_谢拉格", "泰拉大典_地理_萨尔贡", "泰拉大典_地理_哥伦比亚",
        "泰拉大典_地理_卡西米尔", "泰拉大典_地理_伊比利亚", "泰拉大典_地理_炎",
        "泰拉大典_地理_拉特兰", "泰拉大典_地理_龙门",
    ],
    "02-剧情梗概与索引.md": ["剧情梗概", "剧情一览", "活动一览"],
    "03-集成战略.md": [
        "集成战略", "傀影与猩红孤钻", "水月与深蓝之树", "探索者的银凇止境",
        "萨卡兹的无终奇语", "沉沦者的黑流树海",
    ],
    "04-玩法机制.md": ["寻访规则", "罗德岛基建", "干员模组一览"],
    "05-干员.md": [
        "能天使", "能天使_语音记录", "德克萨斯", "拉普兰德", "莫斯提马", "干员一览",
    ],
    "06-活动剧情.md": [
        "吾导先路", "空想花庭", "孤星", "叙拉古人", "巴别塔", "众生行记", "喧闹法则",
    ],
}


def main() -> None:
    used: set[str] = set()
    for out_name, stems in GROUPS.items():
        parts = [f"# {out_name.removesuffix('.md')}\n"]
        for stem in stems:
            path = ROOT / f"{stem}.md"
            if not path.is_file():
                continue
            used.add(path.name)
            text = path.read_text(encoding="utf-8").strip()
            text = re.sub(r"^#\s+.*\n", "", text, count=1).strip()
            parts.append(f"\n## {stem.replace('_', ' ')}\n\n{text}\n")
        (ROOT / out_name).write_text("\n".join(parts), encoding="utf-8")

    for path in sorted(ROOT.glob("*.md")):
        if path.name in GROUPS or path.name in used:
            continue
        print("未分组，保留：", path.name)


if __name__ == "__main__":
    main()
