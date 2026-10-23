"""从 PRTS（明日方舟 wiki）抓页面正文，转成 markdown 供知识库导入。

PRTS 是 MediaWiki，走标准 api.php。只抓公开页面，不登录、不写操作。

用法：
  python scripts/fetch_prts.py 能天使 "能天使/语音记录" 拉特兰
输出到 docs/knowledge/prts/<标题>.md
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://prts.wiki/api.php"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "prts"


def _clean(html: str) -> str:
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_page(title: str) -> str:
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "formatversion": "2",
        "disablelimitreport": "1",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FatFishLife-knowledge/1.0 (personal use)"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"].get("info") or "PRTS 返回错误")
    return _clean(data["parse"]["text"])


def _cn_only(text: str) -> str:
    """只保留含中文的行，去掉日/英/韩配音文本。"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"[\u4e00-\u9fff]", stripped) and not re.search(r"[\u3040-\u30ff]", stripped):
            lines.append(stripped)
    return "\n".join(lines)


def save(title: str, text: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|]", "_", title)
    path = OUT_DIR / f"{safe}.md"
    path.write_text(f"# {title}\n\n{_cn_only(text)}\n", encoding="utf-8")
    return path


def main() -> None:
    titles = sys.argv[1:]
    if not titles:
        print("用法: python scripts/fetch_prts.py 页面标题 [页面标题...]")
        return
    for title in titles:
        try:
            text = fetch_page(title)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {title}: {exc}")
            continue
        path = save(title, text)
        print(f"[ok] {title} -> {path} ({len(text)} 字)")


if __name__ == "__main__":
    main()
