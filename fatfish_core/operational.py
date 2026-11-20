"""Redacted, read-only projections of existing FatFish state."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

TASKS = {
    "consolidate-noon", "consolidate-evening", "bili-recommend-noon", "bili-recommend-evening",
    "bili-inbox", "bili-study", "bili-dynamic", "qzone-thought", "diary",
}
FAILURES = {
    "started-result-unknown", "runner-disabled", "recommendation-paused",
    "recommendation-analysis-failed", "recommendation-analysis-invalid",
    "no-storyboard-or-paused", "no-pick", "qq-account-paused", "quota",
    "background-model-budget-exhausted",
}


def _json(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            raw = file.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _utc(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r"[0-9TtZz:+.\-]+", value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def health(folder: Path, *, qq_paused: bool, now: datetime | None = None) -> dict:
    row = _json(folder / "scheduler-heartbeat.json")
    dt = _utc(row.get("at"))
    age = int(((now or datetime.now(timezone.utc)) - dt).total_seconds()) if dt else None
    readiness = (
        "unknown" if age is None or age < 0 else "stale" if age > 180 else
        "degraded" if row.get("error") else "ready"
    )
    transport = row.get("transport") if isinstance(row.get("transport"), dict) else {}
    qq = "paused" if qq_paused else (
        "online" if transport.get("online") is True else
        "offline" if transport.get("online") is False else "unknown"
    ) if readiness == "ready" else "unknown"
    return {"scheduler": readiness, "heartbeat_age_seconds": age, "qq": qq,
            "wechat": "not_probed", "bilibili": "not_probed"}


def receipts(folder: Path) -> dict:
    state = _json(folder / "schedule-state.json")
    results = state.get("results")
    rows = []
    if isinstance(results, dict):
        for name, item in results.items():
            if name not in TASKS or not isinstance(item, dict):
                continue
            dt = _utc(item.get("at"))
            reason = item.get("reason")
            status = ("unconfirmed" if reason == "started-result-unknown" else
                      "skipped" if item.get("skipped") is True or reason == "runner-disabled" else
                      "ok" if item.get("ok") is True else "failed")
            sent = item.get("sent")
            model_calls = item.get("modelCalls")
            rows.append({"task": name, "at": dt.isoformat() if dt else None, "status": status,
                         "sent_count": sent if type(sent) is int and sent >= 0 else None,
                         "model_calls": model_calls if type(model_calls) is int and model_calls >= 0 else None,
                         "reason": reason if isinstance(reason, str) and reason in FAILURES else None})
    return {"state": "available" if isinstance(results, dict) else "unavailable",
            "tasks": sorted(rows, key=lambda item: item["at"] or "", reverse=True)}


def skill_candidates(folder: Path) -> dict:
    state = _json(folder / "schedule-state.json")
    evidence = state.get("skillEvidence")
    rows = []
    names = {"bili_lookup": "B站推荐", "bili_learning": "B站公开语料学习", "diary": "本地日记"}
    if isinstance(evidence, dict):
        for capability, name in names.items():
            entries = evidence.get(capability)
            if not isinstance(entries, list):
                continue
            valid = {dt for value in entries[-3:] if (dt := _utc(value)) is not None}
            if len(valid) == 3:
                rows.append({"capability": capability, "name": name, "count": len(valid)})
    return {"status": "review_required", "candidates": rows}
