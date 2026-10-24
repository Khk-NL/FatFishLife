"""Read-only usage and transparent cost ranges from AstrBot provider counters."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
PRICE_CHECKED = "2026-10-24"
# CNY per million tokens: uncached input, cached input, output.
RATES = {
    "deepseek-flash": ((1.0, .02, 4.0), (2.0, .04, 8.0)),
    "deepseek-v4-flash": ((1.0, .02, 4.0), (2.0, .04, 8.0)),
    "deepseek-v4-flash-vision-exp": ((1.0, .02, 4.0), (2.0, .04, 8.0)),
    "deepseek-v4-pro": ((4.5, .15, 13.5), (9.0, .30, 27.0)),
}
TOKEN_COLUMNS = ("token_input_other", "token_input_cached", "token_output")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Usage windows require timezone-aware datetimes")
    return value.astimezone(timezone.utc)


def _bucket() -> dict:
    return {"calls": 0, "failed_calls": 0, "missing_usage_calls": 0,
            "unpriced_calls": 0, "local_calls": 0,
            "input_uncached": 0, "input_cached": 0, "output": 0,
            "known_cost_cny_low": 0.0, "known_cost_cny_high": 0.0}


def _finish(bucket: dict) -> dict:
    result = dict(bucket)
    inputs = result["input_uncached"] + result["input_cached"]
    result.update(input_tokens=inputs, total_tokens=inputs + result["output"],
                  cache_hit_ratio=round(result["input_cached"] / inputs, 6) if inputs else None,
                  estimate_complete=not (result["unpriced_calls"] or result["missing_usage_calls"]))
    for key in ("known_cost_cny_low", "known_cost_cny_high"):
        result[key] = round(result[key], 6)
    result["estimate_cny"] = ({"low": result["known_cost_cny_low"], "high": result["known_cost_cny_high"]}
                              if result["estimate_complete"] else None)
    return result


def read_cost_report(db_path: str | Path, start: datetime, end: datetime, *,
                     local_provider_ids=(), warning_cny: float = 5.0) -> dict:
    """Aggregate recorded calls; never read UMO, conversations or credentials.

    Cost bounds apply idle/peak rates to all recorded tokens rather than guessing
    holidays or the provider's billing calendar. Unpriced or absent counters stay
    explicitly incomplete. This is not an account bill or a claim of full capture.
    """
    start, end = _aware(start), _aware(end)
    if end <= start:
        raise ValueError("End must be after start")
    if not math.isfinite(warning_cny) or warning_cny <= 0:
        raise ValueError("warning_cny must be positive")
    report = {"schema_version": 1, "available": False, "has_statistics": False,
              "window": {"start": start.astimezone(BEIJING).isoformat(),
                         "end": end.astimezone(BEIJING).isoformat(), "timezone": "Asia/Shanghai"},
              "pricing": {"currency": "CNY", "checked": PRICE_CHECKED, "source": PRICE_SOURCE,
                          "method": "idle_to_peak_range", "is_bill": False},
              "coverage": "recorded_provider_stats_only", "totals": _finish(_bucket()),
              "by_model": [], "by_hour": [], "alerts": []}
    report["totals"].update(estimate_complete=False, estimate_cny=None)
    path = Path(db_path)
    if not path.is_file():
        report["unavailable_reason"] = "database_missing"
        return report
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(provider_stats)")}
        required = {"created_at", "provider_id", "provider_model", "agent_type", *TOKEN_COLUMNS}
        if not required <= columns:
            report["unavailable_reason"] = "provider_stats_schema_missing"
            return report
        valid = " AND ".join(f"typeof({name})='integer' AND {name}>=0" for name in TOKEN_COLUMNS)
        sums = ",".join(f"COALESCE(SUM(CASE WHEN {valid} THEN {name} ELSE 0 END),0)" for name in TOKEN_COLUMNS)
        errors = "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)" if "status" in columns else "0"
        rows = db.execute(
            "SELECT strftime('%Y-%m-%dT%H:00:00',created_at), "
            "COALESCE(provider_id,''),COALESCE(provider_model,''),COALESCE(agent_type,''),"
            f"COUNT(*),{errors},SUM(CASE WHEN {valid} THEN 0 ELSE 1 END),{sums} "
            "FROM provider_stats WHERE julianday(created_at)>=julianday(?) "
            "AND julianday(created_at)<julianday(?) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4",
            (start.replace(tzinfo=None).isoformat(), end.replace(tzinfo=None).isoformat()),
        ).fetchall()
    report["available"] = True
    report["has_statistics"] = bool(rows)
    total, models, hours = _bucket(), {}, {}
    local_ids = set(local_provider_ids)
    for hour, provider, model, agent, calls, errors, missing, uncached, cached, output in rows:
        delta = _bucket()
        delta.update(calls=int(calls), failed_calls=int(errors), missing_usage_calls=int(missing),
                     input_uncached=int(uncached), input_cached=int(cached), output=int(output))
        if provider in local_ids:
            delta["local_calls"] = int(calls)
        elif model in RATES:
            for key, prices in zip(("known_cost_cny_low", "known_cost_cny_high"), RATES[model]):
                delta[key] = sum(tokens * price for tokens, price in zip((uncached, cached, output), prices)) / 1_000_000
        else:
            delta["unpriced_calls"] = int(calls)
        hour_label = datetime.fromisoformat(hour).replace(tzinfo=timezone.utc).astimezone(BEIJING).isoformat()
        targets = (total, models.setdefault((provider, model, agent), _bucket()), hours.setdefault(hour_label, _bucket()))
        for target in targets:
            for key, value in delta.items():
                target[key] += value
    report["totals"] = _finish(total)
    if not rows:
        report["totals"].update(estimate_complete=False, estimate_cny=None)
    report["by_model"] = [{"provider_id": p, "model": m, "agent_type": a, **_finish(bucket)}
                          for (p, m, a), bucket in models.items()]
    report["by_hour"] = [{"hour": hour, **_finish(bucket)} for hour, bucket in hours.items()]
    if total["known_cost_cny_low"] >= warning_cny:
        report["alerts"].append({"code": "recorded_cost_above_threshold", "threshold_cny": warning_cny})
    elif total["known_cost_cny_high"] >= warning_cny:
        report["alerts"].append({"code": "recorded_cost_may_exceed_threshold", "threshold_cny": warning_cny})
    if total["unpriced_calls"] or total["missing_usage_calls"]:
        report["alerts"].append({"code": "incomplete_cost_coverage"})
    return report


def format_cost_report(report: dict) -> str:
    if not report["available"]:
        return "成本统计暂不可用：" + report["unavailable_reason"] + "；不能当作零消费。"
    if not report["has_statistics"]:
        return "当前窗口没有调用统计；不代表账户没有消费。"
    t = report["totals"]
    hit = f"{t['cache_hit_ratio']:.1%}" if t["cache_hit_ratio"] is not None else "暂无输入统计"
    lines = [f"已记录 {t['calls']} 次调用，{t['total_tokens']:,} tokens；输入缓存命中 {hit}。"]
    if t["estimate_cny"] is None and not t["known_cost_cny_high"]:
        lines.append("本窗口暂不能给出费用估算，存在未定价模型或缺失用量。")
    else:
        lines.append(f"已定价调用估算 ¥{t['known_cost_cny_low']:.3f}～¥{t['known_cost_cny_high']:.3f}（非账单）。")
    if t["local_calls"]:
        lines.append(f"其中明确配置的本地提供商 {t['local_calls']} 次，API费用记为0；本机资源消耗未计价。")
    if not t["estimate_complete"]:
        lines.append(f"另有 {t['unpriced_calls']} 次未定价、{t['missing_usage_calls']} 次用量缺失；估算不完整。")
    if report["alerts"]:
        lines.append("需关注：" + "、".join(item["code"] for item in report["alerts"]) + "。")
    lines.append("仅覆盖已写入 provider_stats 的调用；价格按峰谷区间估算，未猜测节假日。")
    return "\n".join(lines)
