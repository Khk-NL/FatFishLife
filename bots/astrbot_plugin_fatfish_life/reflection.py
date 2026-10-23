"""Daily decisions and receipts, independent of AstrBot and network APIs."""

from __future__ import annotations

import json
import math
import os
import random
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULT_WEIGHTS = {"bilibili": 45.0, "qzone": 45.0, "both": 10.0}


def json_object(text: str) -> dict:
    text = str(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("模型结果必须是 JSON 对象")
    return result


def number(value, default=0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def public_facts(rows: list[dict]) -> list[dict]:
    """Keep public experiences; do not expose session IDs or other people's IDs."""
    facts = []
    for row in rows:
        if row.get("scope") != "public" or row.get("kind") not in {"message", "reply", "video", "interaction"}:
            continue
        text = str(row.get("content") or "").strip()
        if not text or text.startswith(("发现视频候选", "发现了视频候选", "公开选题候选")):
            continue
        for identifier in (row.get("actor"), row.get("session")):
            if identifier and identifier != "bot":
                text = text.replace(str(identifier), "某人")
        text = re.sub(r"\[CQ:[^\]]*\]|https?://\S+|www\.\S+|[\w.+-]+@[\w.-]+", "[已隐去]", text)
        text = re.sub(r"[＠@][^\s，。！？:：,!?]{1,40}|\d{5,}", "某人", text)
        timestamp = str(row.get("created_at") or "")
        try:
            moment = datetime.fromisoformat(timestamp)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            day = moment.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        except ValueError:
            day = timestamp[:10]
        facts.append({
            "id": str(row["id"]), "day": day,
            "platform": row.get("platform", "unknown"),
            "role": "我" if row.get("actor") == "bot" else "公开互动",
            "kind": row.get("kind"), "text": text[:240],
        })
    return facts


class DailyLifeState:
    def __init__(self, path: str | Path, rng=None):
        self.path = Path(path)
        self.rng = rng or random.Random()
        # A damaged state must not silently authorize sending the same post again.
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {
            "days": {}, "next_probability": 20, "paused": {},
        }
        changed = False
        for record in self.data.get("days", {}).values():
            for platform, receipt in record.get("results", {}).items():
                if receipt.get("status") == "sending":
                    receipt["status"] = "uncertain"
                    self.data.setdefault("paused", {})[platform] = "上次发布中断，请先核验是否已发出"
                    changed = True
        if changed:
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".life-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def begin(self, day: str) -> dict:
        date.fromisoformat(day)
        days = self.data.setdefault("days", {})
        if day not in days:
            last = self.data.get("last_evaluated_day")
            if last and day < last:
                raise ValueError("不能重新处理过去的日期")
            gap = max(0, (date.fromisoformat(day) - date.fromisoformat(last)).days - 1) if last else 0
            base = min(100, number(self.data.get("next_probability"), 20) + gap * 20)
            days[day] = {"day": day, "base_probability": base, "status": "thinking", "results": {}}
            self.data["days"] = dict(sorted(days.items())[-31:])
            self.save()
        return self.data["days"][day]

    def decide(self, day: str, proposal: dict, facts: list[dict]) -> dict:
        record = self.begin(day)
        if "targets" in record:
            return record
        adjustment = max(-20, min(20, number(proposal.get("probability_adjustment"))))
        probability = max(0, min(100, record["base_probability"] + adjustment))
        raw_weights = proposal.get("platform_weights")
        weights = {key: max(0, min(100, number(raw_weights.get(key)))) for key in DEFAULT_WEIGHTS} if isinstance(raw_weights, dict) else dict(DEFAULT_WEIGHTS)
        total = sum(weights.values())
        weights = {key: value / total * 100 for key, value in weights.items()} if total else dict(DEFAULT_WEIGHTS)
        text = " ".join(str(proposal.get("text") or "").split()).strip('"“”')
        ids = proposal.get("evidence_ids")
        evidence = {str(value) for value in ids} if isinstance(ids, list) else set()
        valid_ids = {str(fact["id"]) for fact in facts}
        safe = bool(text and len(text) <= 160 and evidence and evidence <= valid_ids)
        safe = safe and not re.search(r"https?://|www\.|[＠@]|\d{5,}", text)
        wants = proposal.get("wants_to_share") is True
        draw = self.rng.random() * 100
        targets = []
        route = None
        if safe and wants and draw < probability:
            value = self.rng.random() * 100
            cumulative = 0.0
            for route, weight in weights.items():
                cumulative += weight
                if value < cumulative:
                    break
            targets = ["bilibili", "qzone"] if route == "both" else [route]
        record.update({
            "probability_adjustment": adjustment, "probability": probability, "draw": draw,
            "platform_weights": weights, "wants_to_share": wants, "draft_safe": bool(safe),
            "reason": str(proposal.get("reason") or "")[:240], "text": text,
            "evidence_ids": sorted(evidence), "targets": targets, "route": route,
            "status": "ready" if targets else "skipped",
        })
        self.save()
        return record

    def claim(self, day: str, platform: str) -> bool:
        record = self.data["days"][day]
        if record.get("status") == "complete" or day < self.data.get("last_evaluated_day", day):
            return False
        if platform not in record.get("targets", []) or platform in record["results"]:
            return False
        if platform in self.data.get("paused", {}):
            self.result(day, platform, {"status": "blocked", "error": {"code": "paused"}})
            return False
        record["results"][platform] = {"status": "sending"}
        self.save()
        return True

    def result(self, day: str, platform: str, receipt: dict):
        self.data["days"][day]["results"][platform] = receipt
        code = (receipt.get("error") or {}).get("code")
        if receipt.get("status") == "uncertain" or code in {"not_logged_in", "auth_expired", "risk_control", "captcha_required"}:
            self.data.setdefault("paused", {})[platform] = code or "publish_unconfirmed"
        self.save()

    def finish(self, day: str):
        record = self.data["days"][day]
        sent = any(value.get("status") == "sent" for value in record["results"].values())
        self.data["next_probability"] = 20 if sent else min(100, record["base_probability"] + 20)
        self.data["last_evaluated_day"] = day
        if sent:
            self.data["last_success_day"] = day
        record["status"] = "complete"
        self.save()

    def resume(self, platform: str):
        self.data.setdefault("paused", {}).pop(platform, None)
        self.save()
