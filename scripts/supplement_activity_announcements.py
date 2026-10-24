"""Fill announcement-only activity gaps with verified activity types, never invented plot."""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish_core.prts_stories import fetch_page
from bots.astrbot_plugin_fatfish_lore.prts import _clean


def activity_type(text):
    # Inspect the announcement introduction, not later navigation or reward tables.
    intro = text[:1800]
    rules = [
        (r"EP\d+ [^\n]+作战环境", "主线章节", "是主题曲主线章节的活动页面，含关卡、奖励和剧情入口；具体剧情须查对应章节。"),
        (r"奇象寻迹[^\n]*|奇象拟合", "奇象巡展", "包含奇象收集与对战项目，也支持和其他玩家同场游玩；公告不等于独立剧情梗概。"),
        (r"生息日、决断与行为", "生息演算", "以探索、营地建设和资源经营为主；具体故事仍需对应剧情原文。"),
        (r"翻牌次数|祈愿牌的翻转", "翻牌奖励", "通过每日登录获得翻牌机会，领取活动奖励；不是独立剧情活动。"),
        (r"完结庆祝活动", "动画纪念", "是动画完结的纪念奖励活动，登录活动页面领取奖励；不把动画内容当成新游戏剧情。"),
        (r"公测开启|新人寻访特惠", "开服福利", "汇集公测开服时的寻访、时装、物资和登录补给等福利；不是单独的剧情活动。"),
        (r"签到活动|累计(?:活动)?签到|活动签到", "签到", "通过活动签到领取奖励；不是独立剧情活动。"),
        (r"集成战略", "集成战略", "以集成战略探索和关卡挑战为主；具体故事应查对应章节，不能由活动公告推断。"),
        (r"危机合约", "危机合约", "以合约条件下的关卡挑战为主；公告本身不提供完整剧情。"),
        (r"保全派驻", "保全派驻", "以保全派驻玩法和挑战为主；公告本身不提供完整剧情。"),
        (r"生息演算", "生息演算", "以生息演算探索和经营玩法为主；具体故事应查对应章节。"),
        (r"限时寻访|联合寻访|限定寻访", "寻访", "是寻访活动介绍；不把干员获取规则当作活动剧情。"),
        (r"限时(?:微型)?故事集|故事集活动", "故事集", "包含活动故事；当前只核实活动公告，具体情节仍需对应剧情原文。"),
        (r"限时(?:作战|挑战)|挑战(?:关卡|任务)|活动关卡|作战关卡|活动剧情|作战环境&敌人", "活动关卡", "含活动关卡及相关奖励；当前只核实公告和玩法，具体剧情仍需对应原文。"),
    ]
    for pattern, category, description in rules:
        match = re.search(pattern, intro)
        if match:
            return category, description, intro[max(0, match.start()-30):match.end()+70]
    return None


def run():
    target = ROOT / "docs/knowledge/prts/07-活动梗概.md"
    text = target.read_text(encoding="utf-8")
    gaps = [(name, body) for name, body in re.findall(r"(?ms)^## (.+?)\n(.*?)(?=^## |\Z)", text)
            if "梗概：资料不足" in body or "资料范围：" in body]
    def one(item):
        name, body = item
        try:
            source = fetch_page(name, ROOT / ".web-data/prts-source")
            found = activity_type(unescape(_clean(source["html"])))
            if not found:
                return {"name": name, "status": "unclassified"}
            category, description, evidence = found
            return {"name": name, "status": "verified", "category": category,
                    "description": description, "evidence": evidence, "revision": source.get("revision"),
                    "source": "https://prts.wiki/w/" + quote(source["title"]), "body": body}
        except Exception as exc:
            return {"name": name, "status": "failed", "error": type(exc).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, gaps))
    for row in results:
        if row["status"] != "verified":
            continue
        body = row.pop("body")
        replacement = re.sub(r"(?m)^- 梗概：.*$", "- 梗概：" + row["description"], body)
        replacement = re.sub(r"(?m)^- (?:资料范围|来源)：.*\n?", "", replacement)
        replacement = replacement.rstrip() + "\n- 资料范围：" + row["category"] + "公告，未据此补写剧情或登场人物。\n- 来源：" + row["source"] + "\n\n"
        text = text.replace("## " + row["name"] + "\n" + body, "## " + row["name"] + "\n" + replacement, 1)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    report = {"checked": len(gaps), "verified": sum(r["status"] == "verified" for r in results), "entries": results}
    output = ROOT / "outputs/activity-grounded/announcement-types.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "entries"}))


if __name__ == "__main__":
    run()
