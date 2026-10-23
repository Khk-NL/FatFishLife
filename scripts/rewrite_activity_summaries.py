"""用 PRTS 页面原文重写不确定活动的梗概，禁止模型自由发挥。

对 07-活动梗概.md 里的每个活动，抓 PRTS 页面文本，只根据文本生成；
页面没有剧情信息就写「资料不足，别编」。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_activity_summaries import api_key  # noqa: E402

TARGET = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "prts" / "07-活动梗概.md"
API = "https://api.deepseek.com/v1/chat/completions"


def prts_text(title: str, limit: int = 1800) -> str:
    params = {"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": "2"}
    url = "https://prts.wiki/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "FatFishLife/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            html = json.loads(resp.read().decode())["parse"]["text"]
    except Exception:
        return ""
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    lines = [line.strip() for line in text.splitlines() if re.search(r"[\u4e00-\u9fff]", line)]
    return "\n".join(lines)[:limit]


def rewrite(key: str, title: str, source: str) -> dict:
    prompt = (
        f"下面是 PRTS 上《{title}》的活动页面文字。只根据这些文字，总结：\n"
        "1. 主要登场人物（页面里出现的人名），没有就写空\n"
        "2. 2-3 句剧情梗概，用「听说」开头\n"
        "页面里没有剧情信息就写「资料不足，别编」，绝对不要自己补充你没看到的内容。\n"
        f"页面文字：\n{source}\n\n"
        "只输出 JSON：{\"characters\": [], \"summary\": \"\"}"
    )
    body = json.dumps(
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "thinking": {"type": "disabled"},
            "max_tokens": 1200,
        }
    ).encode()
    req = urllib.request.Request(
        API, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"].get("content") or ""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"characters": [], "summary": "资料不足，别编"}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"characters": [], "summary": "资料不足，别编"}


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    key = api_key()
    text = TARGET.read_text(encoding="utf-8")
    blocks = re.findall(r"## (.+?)\n\n- 登场：(.+?)\n- 梗概：(.+?)\n", text)
    targets = [b for b in blocks if "资料不足" not in b[2]][:limit] if limit else blocks
    for index, (title, chars, summary) in enumerate(targets, 1):
        source = prts_text(title)
        if not source:
            print(f"[{index}/{len(targets)}] {title} 无页面，跳过")
            continue
        try:
            result = rewrite(key, title, source)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {title}: {exc}")
            continue
        new_chars = "、".join(result.get("characters") or []) or "资料不足"
        new_summary = str(result.get("summary") or "资料不足，别编").strip()
        old_block = f"## {title}\n\n- 登场：{chars}\n- 梗概：{summary}\n"
        new_block = f"## {title}\n\n- 登场：{new_chars}\n- 梗概：{new_summary}\n"
        text = text.replace(old_block, new_block, 1)
        TARGET.write_text(text, encoding="utf-8")
        print(f"[{index}/{len(targets)}] {title}")


if __name__ == "__main__":
    main()
