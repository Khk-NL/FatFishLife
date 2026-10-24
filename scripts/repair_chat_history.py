"""Back up and normalize corrupted multimodal history; never reset another session."""
import argparse
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish_core.context_policy import normalize_history


def repair(db_path: Path, backup_dir: Path, *, apply=False):
    report = {"checked":0,"changed":0,"chars_before":0,"chars_after":0,"legacy_media":0,"synthetic_removed":0}
    with closing(sqlite3.connect(db_path)) as db:
        for identifier, raw in db.execute("SELECT inner_conversation_id,content FROM conversations").fetchall():
            report["checked"] += 1
            try: messages = json.loads(raw)
            except (TypeError, ValueError): continue
            if not isinstance(messages, list): continue
            fixed, stats = normalize_history(messages)
            if fixed == messages: continue
            updated = json.dumps(fixed, ensure_ascii=False)
            report["changed"] += 1
            report["chars_before"] += len(raw); report["chars_after"] += len(updated)
            for key in ("legacy_media","synthetic_removed"): report[key] += stats[key]
            if apply:
                backup_dir.mkdir(parents=True, exist_ok=True)
                target = backup_dir / (str(identifier) + ".json")
                with target.open("x", encoding="utf-8") as output: output.write(raw)
                with db:
                    cursor = db.execute("UPDATE conversations SET content=? WHERE inner_conversation_id=? AND content=?", (updated, identifier, raw))
                    if cursor.rowcount != 1: raise RuntimeError("Conversation changed during repair")
    report["applied"] = apply
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--backup-dir", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    args=p.parse_args()
    print(json.dumps(repair(args.db, args.backup_dir, apply=args.apply)))
