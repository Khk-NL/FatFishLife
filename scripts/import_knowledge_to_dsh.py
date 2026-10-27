"""把 data/knowledge 的 Markdown 导入 DSH 的知识库插件（dsh-knowledge-base）。

目标库结构（插件自建）：
    kb(id, category, name, summary, payload, tags, source, updated_at)
    kb_fts 是 content='kb' 的外部内容 FTS5，trigram 分词

策略：
- 一个 .md 文件 = 一条记录；子目录名作为 category
- 标题行（# xxx）作为 name，首段作 summary，全文进 payload
- tags 里放目录路径，方便按来源过滤
- --rebuild 会先清空再导入；默认是「同名同分类则更新」

用法：
    python scripts/import_knowledge_to_dsh.py --dry-run
    python scripts/import_knowledge_to_dsh.py
    python scripts/import_knowledge_to_dsh.py --rebuild
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "knowledge"
KB_DB = Path("C:/Users/kongb/.dsh/knowledge-base/kb.sqlite")
MAX_PAYLOAD = 200_000


def summarize(text: str) -> str:
    """取第一个非标题段落作为摘要。"""
    lines = [l.strip() for l in text.splitlines()]
    buf: list[str] = []
    for line in lines:
        if not line or line.startswith("#") or line.startswith("|") or line.startswith("```"):
            if buf:
                break
            continue
        buf.append(line)
        if sum(len(x) for x in buf) > 160:
            break
    return " ".join(buf)[:200]


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
            if name:
                return name[:80]
    return fallback[:80]


def collect() -> list[dict]:
    if not SOURCE.is_dir():
        raise SystemExit(f"找不到知识目录：{SOURCE}")
    rows = []
    for path in sorted(SOURCE.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        rel = path.relative_to(SOURCE)
        category = rel.parts[0] if len(rel.parts) > 1 else "总览"
        rows.append(
            {
                "category": category,
                "name": title_of(text, path.stem),
                "summary": summarize(text),
                "payload": text[:MAX_PAYLOAD],
                "tags": json.dumps([str(rel), category], ensure_ascii=False),
                "source": str(path),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--db", type=Path, default=KB_DB)
    args = parser.parse_args()

    rows = collect()
    by_cat: dict[str, int] = {}
    for row in rows:
        by_cat[row["category"]] = by_cat.get(row["category"], 0) + 1

    if args.dry_run:
        print(json.dumps({"files": len(rows), "by_category": by_cat, "db": str(args.db)}, ensure_ascii=False, indent=2))
        return 0

    if not args.db.is_file():
        raise SystemExit(f"知识库不存在（先用 DSH 打开一次让插件建库）：{args.db}")

    conn = sqlite3.connect(args.db)
    try:
        if args.rebuild:
            conn.execute("DELETE FROM kb")
            conn.execute("DELETE FROM kb_fts")
        added = updated = 0
        for row in rows:
            existing = conn.execute(
                "SELECT id FROM kb WHERE category=? AND name=?", (row["category"], row["name"])
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE kb SET summary=?, payload=?, tags=?, source=?, updated_at=datetime('now') WHERE id=?",
                    (row["summary"], row["payload"], row["tags"], row["source"], existing[0]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO kb(category, name, summary, payload, tags, source) VALUES (?,?,?,?,?,?)",
                    (row["category"], row["name"], row["summary"], row["payload"], row["tags"], row["source"]),
                )
                added += 1
        # 外部内容表需要显式重建索引
        conn.execute("INSERT INTO kb_fts(kb_fts) VALUES('rebuild')")
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM kb_fts").fetchone()[0]
    finally:
        conn.close()

    print(json.dumps(
        {"added": added, "updated": updated, "total": total, "indexed": indexed, "by_category": by_cat},
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
