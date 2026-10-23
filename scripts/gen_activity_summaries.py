"""批量生成明日方舟活动的登场人物与梗概（听说口吻）。

用 DeepSeek 生成，结果写 docs/knowledge/prts/07-活动梗概.md。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CFG = Path("D:/Code/Apps/AstrBot/data/cmd_config.json")
OUT = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "prts" / "07-活动梗概.md"
API = "https://api.deepseek.com/v1/chat/completions"

BAD = (
    "签到", "月卡", "复刻", "限时", "庆典", "专享", "网页", "关卡一览", "危机合约",
    "引航者", "矢量突破", "促融共竞", "卫戍协议", "争锋频道", "梦城堡", "回望泰拉",
    "愚人节", "登录", "补给", "组合包", "礼包", "家具", "时装", "开播", "预热",
    "纪念", "合作活动", "音律联觉", "端午", "跨年", "新春",
)


def api_key() -> str:
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    for source in cfg.get("provider_sources", []):
        if source.get("id") == "deepseek":
            key = source.get("key")
            return key[0] if isinstance(key, list) else str(key)
    raise RuntimeError("没有找到 DeepSeek Key")


def activity_titles(limit: int | None = None) -> list[str]:
    params = {"action": "parse", "page": "活动一览", "prop": "text", "format": "json", "formatversion": "2"}
    url = "https://prts.wiki/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "FatFishLife/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        html = json.loads(resp.read().decode())["parse"]["text"]
    links = re.findall(r'href="/w/([^"#?]+)"[^>]*>([^<]{2,40})</a>', html)
    seen, out = set(), []
    for href, _text in links:
        name = urllib.parse.unquote(href).replace("_", " ")
        if name in seen or name.startswith(("分类:", "文件:", "特殊:", "模板:")):
            continue
        seen.add(name)
        if any(bad in name for bad in BAD):
            continue
        if re.search(r"20\d{2}$", name):
            continue
        out.append(name)
    return out[:limit] if limit else out


def summarize(key: str, title: str) -> dict:
    NL = chr(10)
    prompt = (
        f"你在整理明日方舟活动资料，对这款游戏很熟。请给出《{title}》的：" + NL
        + "1. 主要登场人物，3-6 个角色名，用中文常用名" + NL
        + "2. 2-3 句剧情梗概，用「听说」开头，像群友闲聊" + NL
        + "尽力给出最可能的答案，不要因为细节记不全就写记不清。" + NL
        + "只输出 JSON，不要解释：{\"characters\": [\"...\"], \"summary\": \"...\"}"
    )
    body = json.dumps(
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3, "thinking": {"type": "disabled"},
            "max_tokens": 1500,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"characters": [], "summary": "记不清了"}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"characters": [], "summary": "记不清了"}


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    key = api_key()
    titles = activity_titles(limit)
    lines = ["# 活动梗概总览", "", "按 PRTS 活动一览整理，登场人物与梗概由模型生成，口吻是「听说」。", ""]
    for index, title in enumerate(titles, 1):
        try:
            result = summarize(key, title)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {title}: {exc}")
            continue
        chars = "、".join(result.get("characters") or []) or "记不清"
        summary = str(result.get("summary") or "记不清了").strip()
        lines.append(f"## {title}\n\n- 登场：{chars}\n- 梗概：{summary}\n")
        print(f"[{index}/{len(titles)}] {title}")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()