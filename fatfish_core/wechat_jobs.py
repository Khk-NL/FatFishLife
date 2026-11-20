"""Structured WeChat desktop requests and bounded Bilibili document workflow."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
import os
from pathlib import Path
import re

from . import bili
from .wechat_memory import SENSITIVE

CHINA = timezone(timedelta(hours=8))
WORKFLOWS = {"bili-report", "bili-report-qq", "mail-today", "bili-video"}


def _desktop() -> Path:
    if os.name != "nt":
        raise OSError("desktop workflow requires Windows")
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as folder:
        value, _ = winreg.QueryValueEx(folder, "Desktop")
    path = Path(os.path.expandvars(value)).resolve(strict=True)
    if not path.is_dir():
        raise OSError("desktop directory unavailable")
    return path


def _clean(value, limit: int) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(str(value or "")))
    return " ".join(text.split())[:limit].translate(str.maketrans("[]<>", "［］＜＞"))


def _published(item: dict):
    raw = item.get("pubdate") or item.get("pub_date") or item.get("published_at") or item.get("created")
    try:
        if type(raw) is int or isinstance(raw, str) and raw.isdecimal():
            return datetime.fromtimestamp(int(raw), CHINA)
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return value.astimezone(CHINA) if value.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def report_items(items: list, today) -> list[dict]:
    selected = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        bvid = item.get("bvid")
        when = _published(item)
        views = item.get("play", item.get("view", item.get("views", 0)))
        if (not isinstance(bvid, str) or not re.fullmatch(r"BV[1-9A-Za-z][0-9A-Za-z]{9}", bvid)
                or not when or when.date() != today):
            continue
        if type(views) is int or isinstance(views, str) and views.isdecimal():
            views = int(views)
        else:
            views = 0
        selected[bvid] = {"title": _clean(item.get("title"), 100), "bvid": bvid, "views": views,
                          "at": when.isoformat(), "desc": _clean(item.get("description") or item.get("desc"), 180)}
    return sorted(selected.values(), key=lambda item: (item["views"], item["at"]), reverse=True)[:10]


def _subtitle_points(bvid: str) -> list[str]:
    try:
        result = bili.run("video", "subtitle", bvid, "--text", timeout=4)
    except bili.BiliError:
        return []
    if not isinstance(result, dict) or result.get("ok") is not True:
        return []
    data = result.get("data")
    if (not isinstance(data, dict) or data.get("bvid") != bvid
            or not isinstance(data.get("text"), str)):
        return []
    sentences = [_clean(part, 100) for part in re.split(r"[。！？\n]+", data["text"])]
    sentences = list(dict.fromkeys(part for part in sentences if len(part) >= 8))
    if len(sentences) <= 3:
        return sentences
    return [sentences[index] for index in (0, len(sentences) // 2, len(sentences) - 1)]


def _bili_report_inputs(timestamp: int) -> tuple[list[dict], str]:
    day = datetime.fromtimestamp(timestamp, CHINA).date()
    result = bili.run("search", "video", "DSH 插件", "--order", "new", "--size", "50", timeout=8)
    items = (result.get("data") or {}).get("items")
    if result.get("ok") is not True or not isinstance(items, list):
        return [], "video-search-unavailable"
    matches = report_items(items, day)
    if not matches:
        return [], "no-confirmed-today-results"
    with ThreadPoolExecutor(max_workers=4) as tasks:
        subtitles = list(tasks.map(_subtitle_points, (item["bvid"] for item in matches)))
    for item, points in zip(matches, subtitles):
        item["subtitles"] = points
    return matches, ""


def _write_bili_report(job_id: str, timestamp: int, matches: list[dict], visuals: dict) -> tuple[str, int]:
    day = datetime.fromtimestamp(timestamp, CHINA).date()
    filename = f"DSH 插件视频-{day}-{job_id}.md"
    path = _desktop() / filename
    lines = [f"# {day} DSH 插件视频", "",
             f"本次搜索结果中有 {len(matches)} 条可确认是北京时间当天发布的内容，按已知播放量排列。",
             "画面要点依据首集分镜抽样。时间链接跳到对应画面。", ""]
    watched = 0
    for item in matches:
        points = item["subtitles"]
        lines += [f"## {_clean(item['title'], 100)}", "",
                  f"[观看原视频](https://www.bilibili.com/video/{item['bvid']})",
                  f"发布时间 {_clean(item['at'], 35)}，播放量 {item['views']}",
                  _clean(item["desc"], 180) or "公开简介未返回。", ""]
        evidence = visuals.get(item["bvid"])
        if evidence:
            watched += 1
            lines.extend(["画面要点", ""])
            for point in evidence:
                seconds = point["second"]
                stamp = f"{seconds // 60:02d}:{seconds % 60:02d}"
                lines.append(f"- [{stamp}](https://www.bilibili.com/video/{item['bvid']}/?t={seconds}) "
                             + _clean(point["detail"], 120))
            lines.append("")
        else:
            lines.extend(["画面核验未完成。", ""])
        if points:
            lines.extend(["首集字幕摘录", "", *[f"- {_clean(point, 100)}" for point in points], ""])
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return filename, watched


def finish_report(store, scope: str, source: str, payload: dict) -> dict:
    rows, visuals = payload.get("videos"), payload.get("visuals")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 10 or not isinstance(visuals, dict)
            or any(not isinstance(item, dict) or not re.fullmatch(r"BV[1-9A-Za-z][0-9A-Za-z]{9}", str(item.get("bvid")))
                   or type(item.get("views")) is not int or not isinstance(item.get("subtitles"), list)
                   or len(item["subtitles"]) > 3 or not {"title", "at", "desc"} <= item.keys() for item in rows)):
        return {"ok": False, "reason": "invalid-report-inputs"}
    if any(not isinstance(points, list) or not 1 <= len(points) <= 2 or any(
            not isinstance(point, dict) or type(point.get("second")) is not int or not 0 <= point["second"] <= 300
            or not isinstance(point.get("detail"), str) or not 4 <= len(point["detail"]) <= 120 for point in points
    ) for points in visuals.values()):
        return {"ok": False, "reason": "invalid-visual-evidence"}
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _schema(conn)
        job = conn.execute("SELECT * FROM wechat_jobs WHERE scope=? AND source=?", (scope, source)).fetchone()
        if not job or job["status"] != "awaiting-visuals" or job["category"] not in ("bili-report", "bili-report-qq"):
            return {"ok": False, "reason": "report-already-handled"}
        conn.execute("UPDATE wechat_jobs SET status='saving' WHERE scope=? AND source=?", (scope, source))
    try:
        output, watched = _write_bili_report(job["id"], job["created_at"], rows, visuals)
        status = "document-ready" if job["category"] == "bili-report-qq" else "completed"
        reason = "qq-send-unavailable" if job["category"] == "bili-report-qq" else ""
    except OSError:
        output, watched, status, reason = "", 0, "blocked", "report-unconfirmed"
    with store._connect() as conn:
        conn.execute("UPDATE wechat_jobs SET status=?, output=?, reason=? WHERE scope=? AND source=?",
                     (status, output, reason, scope, source))
    return {"ok": status != "blocked", "id": job["id"], "status": status, "output": output,
            "reason": reason, "watched": watched, "total": len(rows)}


def _schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS wechat_jobs (
        scope TEXT NOT NULL, source TEXT NOT NULL, id TEXT NOT NULL, category TEXT NOT NULL,
        status TEXT NOT NULL, output TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL,
        PRIMARY KEY (scope, source))""")


def _draft_video(store, scope: str, timestamp: int, draft: dict) -> tuple[str, str, str]:
    from fatfish_story.updream import save_brief

    day = datetime.fromtimestamp(timestamp, CHINA).date().isoformat()
    base = store.path.parent / "wechat-updream-briefs"
    title, reflection, actions = draft.get("title"), draft.get("reflection"), draft.get("actions")
    if not isinstance(actions, list) or len(actions) != 3:
        raise ValueError("Expected three narrative shots")
    for value, limit in zip([title, reflection, *actions], [42, 150, 100, 100, 100]):
        if not isinstance(value, str) or not 4 <= len(value.strip()) <= limit or SENSITIVE.search(value):
            raise ValueError("Incomplete or private video draft")
    row = save_brief(base, f"{day} 鲸鲸随想", {
        "title": title,
        "logline": reflection,
        "characters": ["鲸鲸，蓝发小个子鲸鱼娘，有一条鲸尾"],
        "visual_style": "手绘动画，蓝绿色桌面灯光，三个镜头保留相同人物与桌面陈设。",
        "sound_plan": "桌面环境声、纸页和杯碟声，最后一句鲸鲸自述。配乐由审阅者确认授权。",
        "shots": [
            {"duration": 6, "action": actions[0], "dialogue": "",
             "visual_prompt": "中景建立场景，动作清楚，不露私聊、账号或设备内容。"},
            {"duration": 7, "action": actions[1], "dialogue": "",
             "visual_prompt": "转到动作近景，用可见变化推进故事，服装和道具连续。"},
            {"duration": 7, "action": actions[2], "dialogue": reflection,
             "visual_prompt": "镜头放缓，停在鲸鲸的反应，保留同一个场景和灯光。"},
        ],
    }, owner=scope, session="wechat:" + scope)
    return ("pending-review", row["id"], "updream-preview-required")


def submit(store, scope: str, source: str, category: str, timestamp: int, *, draft: dict | None = None) -> dict:
    if category not in WORKFLOWS:
        return {"ok": False, "reason": "unknown-workflow"}
    job_id = source[:12]
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _schema(conn)
        existing = conn.execute("SELECT id,category,status,output,reason FROM wechat_jobs WHERE scope=? AND source=?",
                                (scope, source)).fetchone()
        if existing:
            return {"ok": True, **dict(existing)}
        count = conn.execute("SELECT COUNT(*) FROM wechat_jobs WHERE scope=? AND created_at>=?",
                             (scope, timestamp - 86400)).fetchone()[0]
        if count >= 4:
            return {"ok": False, "reason": "daily-workflow-limit"}
        conn.execute("INSERT INTO wechat_jobs VALUES(?,?,?,?,?,?,?,?)",
                     (scope, source, job_id, category, "working", "", "", timestamp))
    if category == "mail-today":
        from dsh.service.desktop_apps import outlook_today
        inbox = outlook_today()
        status = "completed" if inbox["ok"] else "blocked"
        output, reason = "", inbox.get("reason", "")
    elif category == "bili-video":
        try:
            status, output, reason = _draft_video(store, scope, timestamp, draft or {})
        except (OSError, ValueError):
            status, output, reason = ("blocked", "", "video-brief-unconfirmed")
    else:
        try:
            videos, reason = _bili_report_inputs(timestamp)
            status, output = ("awaiting-visuals" if videos else "blocked"), ""
        except (bili.BiliError, OSError, ValueError, AttributeError):
            status, output, reason = ("blocked", "", "report-unconfirmed")
    with store._connect() as conn:
        conn.execute("UPDATE wechat_jobs SET status=?,output=?,reason=? WHERE scope=? AND source=?",
                     (status, output, reason, scope, source))
    receipt = {"ok": True, "id": job_id, "category": category, "status": status, "output": output, "reason": reason}
    if status == "awaiting-visuals":
        receipt["videos"] = videos
    if category == "mail-today" and inbox["ok"]:
        # Only this authorized reply may summarize the mail. Status queries
        # and other channels see the receipt without message contents.
        receipt.update(inbox)
    return receipt


def recent(store, scope: str) -> dict:
    with store._connect() as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wechat_jobs'").fetchone()
        rows = conn.execute("""SELECT id,category,status,output,reason FROM wechat_jobs
            WHERE scope=? ORDER BY rowid DESC LIMIT 5""", (scope,)).fetchall() if exists else []
    return {"ok": True, "jobs": [dict(row) for row in rows]}
