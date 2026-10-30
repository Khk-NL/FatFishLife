"""人设 block 守护，对标 Letta 的 read_only memory block。

行为：
1. 首次运行：把 AstrBot personas 表里的人设写进 blocks.persona，并锁为只读。
2. 之后每次运行：比对 block 与 AstrBot 的人设，不一致就告警并按 block 还原。

用法：
    python scripts/persona_guard.py            # 检查，发现漂移就还原
    python scripts/persona_guard.py --init     # 用当前 AstrBot 人设初始化 block
    python scripts/persona_guard.py --allow    # 认可当前人设为新基线（人工改完后执行）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fatfish_core import MemoryStore  # noqa: E402

ASTRBOT_DB = Path("D:/Code/Apps/AstrBot/data/data_v4.db")
MEMORY_DB = Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db")
PERSONA_ID = "apple-le"
LABEL = "persona"
CHAR_LIMIT = 6000


def read_astrbot_prompt() -> str:
    conn = sqlite3.connect(ASTRBOT_DB)
    try:
        row = conn.execute(
            "select system_prompt from personas where persona_id=?", (PERSONA_ID,)
        ).fetchone()
        return str(row[0] or "") if row else ""
    finally:
        conn.close()


def write_astrbot_prompt(text: str) -> None:
    conn = sqlite3.connect(ASTRBOT_DB)
    try:
        conn.execute(
            "update personas set system_prompt=?, updated_at=? where persona_id=?",
            (text, "2026-10-25T00:00:00", PERSONA_ID),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="用当前人设初始化只读 block")
    parser.add_argument("--allow", action="store_true", help="把当前人设认可为新基线")
    args = parser.parse_args()

    store = MemoryStore(MEMORY_DB)
    current = read_astrbot_prompt()
    if not current.strip():
        print("错误：AstrBot 里没有人设", file=sys.stderr)
        return 1

    block = store.get_block(LABEL)

    if args.init or block is None:
        store.set_block(
            LABEL,
            current,
            char_limit=CHAR_LIMIT,
            read_only=True,
            description="大肥鲸常驻人设，只读；改动走人工并执行 --allow",
            force=True,
        )
        print(f"已初始化只读 block（{len(current)} 字符）")
        return 0

    if args.allow:
        store.set_block(LABEL, current, char_limit=CHAR_LIMIT, read_only=True, force=True)
        print(f"已把当前人设认可为新基线（{len(current)} 字符）")
        return 0

    baseline = str(block["value"])
    if current.strip() == baseline.strip():
        print(f"人设未漂移（{len(current)} 字符）")
        return 0

    print(
        f"检测到人设漂移：block {len(baseline)} 字符 / 现行 {len(current)} 字符，正在还原",
        file=sys.stderr,
    )
    write_astrbot_prompt(baseline)
    print("已还原到只读 block 的内容")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
