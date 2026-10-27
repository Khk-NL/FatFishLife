"""把 self_learning 的 expression_patterns 迁进共享记忆候选区。

背景：旧系统的「场景 → 表达」样本存在
`plugin_data/astrbot_plugin_self_learning/messages.db` 的 expression_patterns 表里，
共 157 条。迁移不直接当成长期记忆，先全部进 candidates（status=candidate），
由主人审核后再 verified。

用法：
    python scripts/migrate_style_candidates.py --dry-run
    python scripts/migrate_style_candidates.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fatfish_core import MemoryStore  # noqa: E402

SOURCE_DB = Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_self_learning/messages.db")
TARGET_DB = Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db")

# 明显是系统噪声或旧插件残留，不进候选
BLOCK_MARKERS = ("LLM 响应错误", "Traceback", "自检", "星绘", "XML", "<#", "合成失败")


def read_patterns() -> list[tuple[str, str, str]]:
    if not SOURCE_DB.is_file():
        raise SystemExit(f"找不到源库：{SOURCE_DB}")
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT situation, expression, COALESCE(persona_id, '')
            FROM expression_patterns
            WHERE length(situation) BETWEEN 2 AND 60
              AND length(expression) BETWEEN 2 AND 120
            """
        ).fetchall()
    finally:
        conn.close()
    out = []
    for situation, expression, persona in rows:
        text = f"{situation} → {expression}"
        if any(marker in text for marker in BLOCK_MARKERS):
            continue
        out.append((str(situation).strip(), str(expression).strip(), str(persona)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target", type=Path, default=TARGET_DB)
    args = parser.parse_args()

    patterns = read_patterns()
    print(f"源样本 {len(patterns)} 条（已过滤系统噪声）")

    if args.dry_run:
        for situation, expression, _ in patterns[:5]:
            print("  样例:", situation[:30], "→", expression[:40])
        return 0

    store = MemoryStore(args.target)
    added = 0
    for situation, expression, _ in patterns:
        # 同一个「场景 → 表达」只入一次；重复出现由 add_candidate 累加 hits
        candidate_id = store.add_candidate(
            f"{situation} → {expression}",
            kind="style",
            group_id="",
            speaker="",
            confidence=0.5,
        )
        if candidate_id:
            added += 1
    print(f"写入候选 {added} 条（status=candidate，需主人审核）")
    print("当前候选统计:", {s: len(store.list_candidates(s, 500)) for s in ("candidate", "verified", "rejected")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
