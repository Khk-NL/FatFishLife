"""Finite, deterministic PRTS fact extraction with short original evidence."""
from __future__ import annotations

from html import unescape
import json
import re
from urllib.parse import quote


CHARACTERS = ("能天使", "新约能天使", "德克萨斯", "莫斯提马", "蕾缪安")
SOURCE_TITLES = (*CHARACTERS, "泰拉大典:组织", "泰拉大典:地理/拉特兰", "泰拉大典:地理/龙门",
                 "泰拉大典:组织/企鹅物流", "泰拉大典:生物", "作战机制", "泰拉大典:百科/概念")
FENCE = "fatfish-graph-facts"


def plain_text(html: str) -> str:
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr|td|th)>", "\n", html, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", "", html))
    return "\n".join(line for raw in text.splitlines() if (line := " ".join(raw.split())))


def extract_page(title: str, html: str, *, revision=None, fetched_at="") -> dict:
    text = plain_text(html)
    community = title.startswith("泰拉大典:")
    result = {"page": title, "title": title + ("（PRTS社区整理）" if community else ""),
              "source_url": "https://prts.wiki/w/" + quote(title), "revision": revision,
              "fetched_at": fetched_at, "entities": [], "relations": [], "notes": []}
    entities = {}

    def add(subject, predicate, obj, evidence, *, subject_type="概念", object_type="概念"):
        if not evidence or (evidence not in text and evidence not in html):
            raise ValueError("Evidence is not present in the fetched page")
        if len(evidence) > 160:
            raise ValueError("Evidence must be a short source fragment")
        entities.setdefault(subject, {"name": subject, "type": subject_type})
        entities.setdefault(obj, {"name": obj, "type": object_type})
        result["relations"].append({"subject": subject, "predicate": predicate, "object": obj,
                                    "evidence": evidence, "confidence": .85 if community else .95})

    if title in CHARACTERS:
        # The operator page carries literal JSON fields used by PRTS's own card.
        # Read only the named card, never execute any script from the wiki.
        start = re.search(r'"name"\s*:\s*"' + re.escape(title) + r'"', html)
        card = html[start.start():start.start() + 1800] if start else ""
        for field, predicate, kind in (("group", "游戏阵营", "组织"), ("class", "职业", "概念"), ("branch", "职业分支", "概念")):
            match = re.search(r'"' + field + r'"\s*:\s*("(?:[^"\\]|\\.)*")', card)
            if not match:
                result["notes"].append("缺少字段：" + predicate)
                continue
            value = json.loads(match.group(1))
            object_kind = "地点" if value in {"拉特兰", "哥伦比亚", "龙门", "叙拉古"} else kind
            add(title, predicate, value, match.group(0), subject_type="人物", object_type=object_kind)
        for field, kind in (("出身地", "地点"), ("种族", "概念")):
            match = re.search(r"【" + field + r"】([^\n]+)", text)
            if not match or match.group(1) in {"未公开", "未知", "不详", "?", "？"}:
                result["notes"].append(field + "未公开或未提供，不据外观推断。")
                continue
            add(title, field, match.group(1), match.group(0), subject_type="人物", object_type=kind)
    elif title == "泰拉大典:组织":
        for subject, category in (("罗德岛", "制药公司"), ("企鹅物流", "物流公司")):
            pattern = re.escape(category) + r"\n(?:\[编辑\]\n)?" + re.escape(subject) + r"[^\n]*"
            match = re.search(pattern, text)
            if match:
                add(subject, "PRTS归类", category, match.group(0), subject_type="组织")
    elif title == "泰拉大典:地理/拉特兰":
        for predicate, obj, evidence in (("地理位置", "泰拉大陆中部", "位于泰拉大陆中部"),
                                          ("PRTS政体描述", "神权国家", "神权国家")):
            if evidence in text:
                add("拉特兰", predicate, obj, evidence, subject_type="地点", object_type="地点" if predicate == "地理位置" else "概念")
    elif title == "泰拉大典:地理/龙门":
        match = re.search(r"龙门（Lungmen），炎国的移动城邦", text)
        if match:
            add("龙门", "所属国家", "炎国", match.group(0), subject_type="地点", object_type="地点")
            add("龙门", "地点类型", "移动城邦", match.group(0), subject_type="地点")
    elif title == "泰拉大典:组织/企鹅物流":
        for predicate, obj, evidence in (("核心业务区域", "龙门", "以龙门作为核心业务区域"),
                                          ("业务类型", "物流运输", "正常的物流运输业务")):
            if evidence in text:
                add("企鹅物流", predicate, obj, evidence, subject_type="组织", object_type="地点" if obj == "龙门" else "概念")
    elif title == "泰拉大典:生物":
        start = text.find("萨科塔\n[编辑]")
        section = text[start:start + 2000] if start >= 0 else ""
        for predicate, obj, evidence in (("通称", "天使", "通称“天使”"),
                                          ("外观特征", "光环", "悬浮于头顶的光环"),
                                          ("外观特征", "光翼", "背后的晶体状光翼")):
            if evidence in section:
                add("萨科塔", predicate, obj, evidence)
    elif title == "泰拉大典:百科/概念":
        for predicate, obj, evidence in (("俗称", "法术", "常被俗称为“法术”"),
                                          ("改变性状", "物质", "令物质改变原有性状")):
            if evidence in text:
                add("源石技艺", predicate, obj, evidence)
    elif title == "作战机制":
        quote_text = "按伤害类型，可分为物理、法术、真实、元素伤害等。"
        if quote_text in text:
            for name in ("物理伤害", "法术伤害", "真实伤害", "元素伤害"):
                add("伤害类型", "包含", name, quote_text)
        if "治疗也是一种伤害类型" in text:
            add("治疗", "机制分类", "伤害类型", "治疗也是一种伤害类型")
        for subject, predicate, obj, evidence in (("护盾", "每层抵挡", "一次伤害", "每层护盾可以抵挡一次伤害"),
                                                  ("屏障", "作用", "吸收一定数值的伤害", "可以吸收一定数值的伤害")):
            if evidence in text:
                add(subject, predicate, obj, evidence)
        result["notes"].append("PRTS社区机制整理；这里只记录已核对的分类和短定义，不据此推导全部伤害公式或承诺适用所有版本。")
    if community:
        result["notes"].insert(0, "PRTS社区世界观整理，可能包含主观考据；不是官方站点声明，不将考据当作官方定论。")
    result["entities"] = list(entities.values())
    if any(name not in text and name not in html for name in entities):
        raise ValueError("Entity is not present in the fetched page")
    evidence = list(dict.fromkeys(row["evidence"] for row in result["relations"]))
    # Keep independently checked original snippets separate from declarations.
    # Graph validation must not accept a quote just because it appears in JSON.
    result["source_excerpt"] = title + "\n" + "\n".join(evidence) + "\n实体原文：" + "、".join(entities)
    return result


def markdown_document(pages: list[dict]) -> str:
    lines = ["# PRTS 基础事实图谱", "", "有限核心页的可核对基础关系，不是整站镜像。人物字段来自PRTS转录的干员资料；泰拉大典和机制页明确按社区整理标注。",
             "每条关系附原文短依据；未公开字段保持未知。下方结构块直接进入现有图谱证据校验，无需再调用模型提取。", ""]
    for page in pages:
        lines.extend(["## " + page["title"], "", "来源：" + page["source_url"],
                      "采集时间：" + page["fetched_at"] + "；页面修订号：" + str(page["revision"] or "接口未提供"), ""])
        lines.extend("> " + note for note in page["notes"])
        lines.extend(["", "| 实体 | 关系 | 对象 | 原文短依据 |", "|---|---|---|---|"])
        for row in page["relations"]:
            cells = [row["subject"], row["predicate"], row["object"], row["evidence"]]
            lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
        lines.extend(["", "```" + FENCE, json.dumps(page, ensure_ascii=False, separators=(",", ":")), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def structured_documents(text: str, relative: str, collection: str):
    """Keep caller-selected collection isolation and feed the existing validator."""
    for match in re.finditer(r"```" + FENCE + r"\s*\n(.*?)\n```", text, re.S):
        page = json.loads(match.group(1))
        if not all(key in page for key in ("page", "title", "source_url", "source_excerpt", "entities", "relations")):
            raise ValueError("Incomplete PRTS structured source")
        source_text = page["title"] + "\n" + "\n".join(page.get("notes", [])) + "\n" + page["source_excerpt"]
        yield {"collection": collection, "source": relative + "#" + page["page"],
               "title": page["title"], "source_url": page["source_url"], "text": source_text,
               "structured": {"entities": page["entities"], "relations": page["relations"]}}
