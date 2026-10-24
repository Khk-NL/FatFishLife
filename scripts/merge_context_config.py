"""Move retired context settings into the existing memory plugin; preview first."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


FIELD_MAPPING = {
    "enabled": "context_hygiene_enabled",
    "image_history_turns": "image_history_turns",
    "max_current_images": "max_current_images",
    "monitor_interval_seconds": "monitor_interval_seconds",
    "cost_warning_cny": "cost_warning_cny",
}


def merge_context_config(data_dir: Path, *, apply=False) -> dict:
    data_dir = Path(data_dir)
    source = data_dir / "config/astrbot_plugin_fatfish_context_config.json"
    target = data_dir / "config/astrbot_plugin_fatfish_memory_config.json"
    result = {"applied": apply, "legacy_found": source.is_file(), "changed": False,
              "mapped_fields": [], "preserved_fields": [], "backup_created": False}
    if not source.is_file():
        return result
    legacy = json.loads(source.read_text(encoding="utf-8-sig"))
    current = json.loads(target.read_text(encoding="utf-8-sig")) if target.is_file() else {}
    updated = dict(current)
    for old, new in FIELD_MAPPING.items():
        if old not in legacy:
            continue
        if new in current:
            result["preserved_fields"].append(new)
        else:
            updated[new] = legacy[old]
            result["mapped_fields"].append(new)
    # Monitoring ran unconditionally in the retired plugin; preserve that
    # behavior unless the memory configuration already explicitly disabled it.
    updated.setdefault("cost_monitor_enabled", True)
    result["changed"] = updated != current
    if apply and result["changed"]:
        if target.is_file():
            backup = data_dir / "private-config-backups" / datetime.now().strftime("%Y%m%d-context-merge-%H%M%S-%f")
            backup.mkdir(parents=True, exist_ok=False)
            shutil.copy2(target, backup / target.name)
            result["backup_created"] = True
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".merge.tmp")
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        if json.loads(target.read_text(encoding="utf-8")) != updated:
            raise RuntimeError("Memory configuration readback mismatch")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(merge_context_config(args.data_dir, apply=args.apply)))
