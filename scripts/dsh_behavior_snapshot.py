"""Export only behavior settings; never export account IDs, keys or login data."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot(data: Path) -> dict:
    sources = {}
    def read(relative):
        path = data / relative
        raw = path.read_bytes()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw.decode("utf-8-sig"))
    native = read("cmd_config.json")
    tts = native["provider_tts_settings"]
    meme = read("config/meme_manager_config.json")["generation"]["emotion"]
    life = read("config/astrbot_plugin_fatfish_life_config.json")
    bili = read("config/astrbot_plugin_fatfish_bili_config.json")
    with closing(sqlite3.connect((data / 'data_v4.db').as_uri() + '?mode=ro', uri=True)) as connection:
        row = connection.execute("SELECT value FROM preferences WHERE scope='global' AND scope_id='global' AND key='inactivated_plugins'").fetchone()
    inactive = json.loads(row[0]).get('val', []) if row else []
    sources['inactivated_plugins'] = hashlib.sha256(json.dumps(inactive, sort_keys=True).encode()).hexdigest()
    def enabled(name):
        return (data / 'plugins' / name).is_dir() and f'data.plugins.{name}.main' not in inactive
    return {
        "version": 1,
        "captured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_hashes": sources,
        "voice": {"source": "AstrBot native result_decorate", "enabled": bool(tts["enable"]),
                  "base": float(tts["trigger_probability"]), "step": 0.0, "max": 1.0,
                  "text_alongside_voice": bool(tts.get("dual_output", False)),
                  "cooldown_seconds": 0, "max_text_length": None, "manual_trigger": False,
                  "fallback_to_text": True},
        "meme": {"enabled": enabled('meme_manager'),
                 "base": float(meme["probability"]) / 100, "step": float(meme["probability_step"]) / 100,
                 "max": float(meme["probability_max"]) / 100, "manual_trigger": bool(meme.get("manual_trigger", True)),
                 "max_per_message": int(meme.get("max_memes_per_message", 1))},
        "life": {"enabled": enabled('astrbot_plugin_fatfish_life') and bool(life.get("enabled", True)), "publish_enabled": bool(life.get("publish_enabled", False)),
                 "base": .20, "step": .20, "max": 1.0, "model_adjustment": [-.20, .20],
                 "platform_weights": {"bilibili": .45, "qzone": .45, "both": .10},
                 "reflection_time": str(life.get("reflection_time", "23:50")),
                 "requires_share_intent_and_public_evidence": True},
        "bili": {key: bili.get(key) for key in ("auto_reply", "auto_reply_owner_only", "auto_scroll_enabled",
                 "auto_scroll_comment_enabled", "auto_scroll_times", "study_enabled", "study_time", "dry_run_writes")},
        "proactive": {"enabled": enabled('astrbot_plugin_proactive_chat'),
                      "note": "Preserve disabled state; per-session rules require separate migration"},
        "receipt_policy": "reset only on confirmed delivery; no retry of uncertain writes",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-data", type=Path, default=Path("D:/Code/Apps/AstrBot/data"))
    parser.add_argument("--output", type=Path, default=ROOT / "data/dsh/behavior.json")
    parser.add_argument("--refresh", action="store_true", help="back up and refresh the local snapshot after reviewing source changes")
    args = parser.parse_args()
    if args.output.exists() and not args.refresh:
        raise SystemExit("Behavior snapshot already exists; compare changes before replacing it")
    report = snapshot(args.legacy_data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        backup = args.output.with_suffix(f'.before-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")}.json')
        backup.write_bytes(args.output.read_bytes())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(args.output), "voice": report["voice"]["base"],
                      "meme": [report["meme"][key] for key in ("base", "step", "max")],
                      "life": [report["life"][key] for key in ("base", "step", "max")]}))


if __name__ == "__main__":
    main()
