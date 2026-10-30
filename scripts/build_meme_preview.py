"""Build a local HTML preview for the collected meme images.

Reads assets/memes/apple-le/sources.json, copies images out of the
meme_manager pack into assets/memes/apple-le/files/, and writes a static
preview page with category filters and a lightbox.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets/memes/apple-le/sources.json"
FILES_DIR = ROOT / "assets/memes/apple-le/files"
PACK_DIR = Path("D:/Code/Apps/AstrBot/data/plugin_data/meme_manager/packs/builtin-default/memes")
OUTPUT = ROOT / "assets/memes/preview.html"


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    images = data.get("images") or []
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    cards = []
    copied = 0
    for item in images:
        category = str(item.get("category") or "未分类")
        filename = str(item.get("filename") or "")
        if not filename:
            continue
        source = PACK_DIR / category / filename
        target_dir = FILES_DIR / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
            copied += 1
        if not target.exists():
            continue
        rel = f"apple-le/files/{category}/{filename}"
        author = str(item.get("author") or "")
        page = str(item.get("source_page") or "")
        keyword = str(item.get("keyword") or "")
        cards.append(
            {
                "src": rel,
                "name": filename,
                "category": category,
                "keyword": keyword,
                "author": author,
                "page": page,
            }
        )

    payload = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>大肥鲸 · 能天使 · 拉特兰 表情包预览</title>
<style>
:root {{
  --bg: #0f1115; --panel: #171a21; --line: #2a2f3a; --text: #e8eaf0;
  --muted: #9aa3b2; --accent: #e0556f;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }}
header {{ position: sticky; top: 0; z-index: 5; background: rgba(15,17,21,.92);
  backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
  padding: 16px 24px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
h1 {{ font-size: 18px; margin: 0; font-weight: 600; }}
.count {{ color: var(--muted); font-size: 13px; }}
.filters {{ display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }}
button {{ background: var(--panel); color: var(--text); border: 1px solid var(--line);
  border-radius: 8px; padding: 7px 14px; cursor: pointer; font-size: 13px; }}
button.active {{ border-color: var(--accent); color: #fff; background: #2a1a20; }}
main {{ padding: 20px 24px 48px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; cursor: zoom-in; transition: border-color .15s; }}
.card:hover {{ border-color: var(--accent); }}
.card img {{ width: 100%; height: 150px; object-fit: contain; display: block; background: #0b0d11; }}
.meta {{ padding: 8px 10px; font-size: 11px; color: var(--muted); line-height: 1.5;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.meta b {{ color: var(--text); font-weight: 500; }}
.lightbox {{ position: fixed; inset: 0; background: rgba(0,0,0,.92); display: none;
  align-items: center; justify-content: center; flex-direction: column; z-index: 50; padding: 24px; }}
.lightbox.open {{ display: flex; }}
.lightbox img {{ max-width: min(90vw, 800px); max-height: 78vh; object-fit: contain; }}
.lightbox .info {{ color: var(--muted); font-size: 13px; margin-top: 14px; text-align: center; line-height: 1.7; }}
.lightbox a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>大肥鲸 · 能天使 · 拉特兰 表情包</h1>
  <span class="count" id="count"></span>
  <div class="filters" id="filters"></div>
</header>
<main><div class="grid" id="grid"></div></main>
<div class="lightbox" id="lightbox">
  <img id="big" alt="">
  <div class="info" id="info"></div>
</div>
<script>
const items = {payload};
const cats = ["全部", ...Array.from(new Set(items.map(i => i.category)))];
let active = "全部";
const grid = document.getElementById("grid");
const count = document.getElementById("count");
const filters = document.getElementById("filters");
const lightbox = document.getElementById("lightbox");
const big = document.getElementById("big");
const info = document.getElementById("info");

cats.forEach(cat => {{
  const b = document.createElement("button");
  b.textContent = cat === "全部" ? "全部" : cat;
  b.onclick = () => {{ active = cat; render(); }};
  b.dataset.cat = cat;
  filters.appendChild(b);
}});

function render() {{
  document.querySelectorAll("#filters button").forEach(b => b.classList.toggle("active", b.dataset.cat === active));
  const shown = active === "全部" ? items : items.filter(i => i.category === active);
  count.textContent = `${{shown.length}} 张`;
  grid.innerHTML = "";
  shown.forEach(item => {{
    const card = document.createElement("div");
    card.className = "card";
    const img = document.createElement("img");
    img.src = item.src;
    img.loading = "lazy";
    img.alt = item.keyword || item.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<b>${{item.keyword || item.name}}</b><br>${{item.category}}`;
    card.appendChild(img);
    card.appendChild(meta);
    card.onclick = () => {{
      big.src = item.src;
      big.alt = item.keyword || item.name;
      info.innerHTML = `${{item.category}} · ${{item.keyword || item.name}}<br>${{item.author || ""}}<br>` +
        (item.page ? `<a href="${{item.page}}" target="_blank" rel="noreferrer">${{item.page}}</a>` : "");
      lightbox.classList.add("open");
    }};
    grid.appendChild(card);
  }});
}}
lightbox.onclick = () => lightbox.classList.remove("open");
document.addEventListener("keydown", e => {{ if (e.key === "Escape") lightbox.classList.remove("open"); }});
render();
</script>
</body>
</html>
"""
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"cards={len(cards)} copied={copied} -> {OUTPUT}")


if __name__ == "__main__":
    main()
