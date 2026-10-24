"""Refresh a fixed set of public PRTS core facts without any model calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish_core.prts_facts import FENCE, SOURCE_TITLES, extract_page, markdown_document
from fatfish_core.prts_stories import fetch_page


def refresh(cache: Path, output: Path, report: Path, *, pages=SOURCE_TITLES, force=False):
    if not set(pages) <= set(SOURCE_TITLES):
        raise ValueError("Only the finite core source set is supported")
    previous = {}
    if output.is_file():
        for match in re.finditer(r"```" + FENCE + r"\s*\n(.*?)\n```", output.read_text(encoding="utf-8"), re.S):
            page = json.loads(match.group(1))
            previous[page["page"]] = page
    def one(title):
        try:
            source = fetch_page(title, cache, refresh=force)
            cached = cache / (hashlib.sha256(title.encode()).hexdigest() + ".json")
            fetched_at = datetime.fromtimestamp(cached.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            result = extract_page(title, source["html"], revision=source.get("revision"), fetched_at=fetched_at)
            if not result["relations"]:
                raise ValueError("No supported facts found")
            return {"page": title, "ok": True, "facts": result}
        except Exception as exc:
            return {"page": title, "ok": False, "error": type(exc).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, pages))
    valid = [r["facts"] for r in results if r["ok"]]
    if valid:
        merged = {**previous, **{page["page"]: page for page in valid}}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown_document([merged[title] for title in SOURCE_TITLES if title in merged]), encoding="utf-8")
    summary = {"attempted": len(results), "completed": len(valid), "failed": len(results)-len(valid),
               "relations": sum(len(p["relations"]) for p in valid),
               "retained_previous_failed": sum(not r["ok"] and r["page"] in previous for r in results),
               "sources": [{k: v for k, v in r.items() if k != "facts"} for r in results]}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=ROOT / ".web-data/prts-source")
    p.add_argument("--output", type=Path, default=ROOT / "docs/knowledge/prts/09-基础事实图谱.md")
    p.add_argument("--report", type=Path, default=ROOT / "outputs/knowledge-graph/core-facts-refresh.json")
    p.add_argument("--pages", nargs="+", choices=SOURCE_TITLES, default=SOURCE_TITLES)
    p.add_argument("--refresh", action="store_true", help="Request these finite pages again; otherwise reuse local cache")
    args = p.parse_args()
    result = refresh(args.cache, args.output, args.report, pages=args.pages, force=args.refresh)
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}))
    raise SystemExit(1 if result["failed"] else 0)
