"""Write docs/persona/apple-le-core.md into AstrBot's persona table.

Stop AstrBot first (or accept that SQLite may briefly lock), then run:
    python scripts/sync_persona.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "docs/persona/apple-le-core.md"
DEFAULT_DB = Path("D:/Code/Apps/AstrBot/data/data_v4.db")
DEFAULT_PERSONA_ID = "apple-le"


def main() -> int:
    parser = argparse.ArgumentParser(description="同步大肥鲸常驻人设到 AstrBot")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--persona-id", default=DEFAULT_PERSONA_ID)
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"错误：找不到人设文件 {args.source}", file=sys.stderr)
        return 1
    if not args.db.is_file():
        print(f"错误：找不到数据库 {args.db}", file=sys.stderr)
        return 1

    text = args.source.read_text(encoding="utf-8").strip()
    if not text:
        print("错误：人设文件为空", file=sys.stderr)
        return 1

    connection = sqlite3.connect(args.db, timeout=10)
    try:
        row = connection.execute(
            "SELECT id FROM personas WHERE persona_id=?", (args.persona_id,)
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE personas SET system_prompt=?, updated_at=datetime('now') WHERE persona_id=?",
                (text, args.persona_id),
            )
            action = "updated"
        else:
            connection.execute(
                "INSERT INTO personas(created_at,updated_at,persona_id,system_prompt,begin_dialogs,tools,skills,custom_error_message,folder_id,sort_order) "
                "VALUES (datetime('now'),datetime('now'),?,?, '[]','null','null',NULL,NULL,1)",
                (args.persona_id, text),
            )
            action = "inserted"
        connection.commit()
    finally:
        connection.close()

    print(f"{action} persona={args.persona_id} chars={len(text)} db={args.db}")
    print("重启 AstrBot，并在 QQ 里发送 /reset 让新会话使用新人设。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
