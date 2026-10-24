"""Read-only AstrBot cost self-check; no model or external service calls."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fatfish_core.costs import BEIJING, format_cost_report, read_cost_report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True)
    span = p.add_mutually_exclusive_group()
    span.add_argument("--hours", type=float, default=24)
    span.add_argument("--today", action="store_true", help="Beijing calendar day so far")
    span.add_argument("--day", help="Complete Beijing calendar day, YYYY-MM-DD")
    p.add_argument("--local-provider", action="append", default=[], help="Explicit provider ID whose requests run locally; repeatable")
    p.add_argument("--warning-cny", type=float, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--output", type=Path, help="Write one JSON snapshot; parent directories are created")
    args = p.parse_args()
    end = datetime.now(timezone.utc)
    if args.day:
        start = datetime.strptime(args.day, "%Y-%m-%d").replace(tzinfo=BEIJING)
        end = start + timedelta(days=1)
    elif args.today:
        start = end.astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        if args.hours <= 0:
            p.error("--hours must be positive")
        start = end - timedelta(hours=args.hours)
    report = read_cost_report(args.db, start, end, local_provider_ids=args.local_provider, warning_cny=args.warning_cny)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_cost_report(report))
    return 0 if report["available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
