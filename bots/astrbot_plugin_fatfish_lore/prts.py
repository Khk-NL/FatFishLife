"""按需抓 PRTS 页面并本地缓存，避免预导入整个 wiki。"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://prts.wiki/api.php"
CACHE_DIR = Path(__file__).resolve().parent / "prts_cache"


def _clean(html: str) -> str:
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for src, dst in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(src, dst)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and re.search(r"[\u4e00-\u9fff]", line)
        and not re.search(r"[\u3040-\u30ff]", line)
    ]
    return "\n".join(lines)


def fetch_page(title: str, *, max_chars: int = 4000, use_cache: bool = True) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|]", "_", title)
    cache = CACHE_DIR / f"{safe}.txt"
    if use_cache and cache.is_file():
        return cache.read_text(encoding="utf-8")[:max_chars]

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
        url, headers={"User-Agent": "FatFishLife-lore/1.0 (personal use)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"].get("info") or "PRTS 没有这个页面")
    text = _clean(data["parse"]["text"])
    cache.write_text(text, encoding="utf-8")
    return text[:max_chars]
