"""Structured WeChat desktop requests and bounded Bilibili document workflow."""

from datetime import datetime, timedelta, timezone
import html
import os
from pathlib import Path
import re

from . import bili

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


def _write_bili_report(job_id: str, timestamp: int) -> tuple[str, str, str]:
    day = datetime.fromtimestamp(timestamp, CHINA).date()
    result = bili.run("search", "video", "DSH 插件", "--order", "new", "--size", "50", timeout=8)
    items = (result.get("data") or {}).get("items")
    if result.get("ok") is not True or not isinstance(items, list):
        return ("blocked", "", "video-search-unavailable")
    matches = report_items(items, day)
    if not matches:
        return ("blocked", "", "no-confirmed-today-results")
    filename = f"DSH 插件视频-{day}-{job_id}.md"
    path = _desktop() / filename
    lines = [f"# {day} DSH 插件视频", "",
             f"本次搜索结果中有 {len(matches)} 条可确认是北京时间当天发布的内容，按已知播放量排列。",
             "摘要依据视频公开简介。", ""]
    for item in matches:
        lines += [f"## {item['title']}", "",
                  f"[观看原视频](https://www.bilibili.com/video/{item['bvid']})",
                  f"发布时间 {item['at']}，播放量 {item['views']}",
                  item["desc"] or "公开简介未返回。", ""]
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return ("completed", filename, "")


def _schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS wechat_jobs (
        scope TEXT NOT NULL, source TEXT NOT NULL, id TEXT NOT NULL, category TEXT NOT NULL,
        status TEXT NOT NULL, output TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL,
        PRIMARY KEY (scope, source))""")


def _draft_video(store, scope: str, timestamp: int) -> tuple[str, str, str]:
    from fatfish_story.updream import save_brief

    day = datetime.fromtimestamp(timestamp, CHINA).date().isoformat()
    base = store.path.parent / "wechat-updream-briefs"
    row = save_brief(base, f"{day} 鲸鲸随想", {
        "title": "小鲸鱼的随想：想明白再开口",
        "logline": "鲸鲸正想飞快发出一句感想，却在最后一刻发现没有核对来源。",
        "characters": ["鲸鲸，蓝发小个子鲸鱼娘，有一条鲸尾"],
        "visual_style": "手绘动画，蓝绿色桌面灯光，三个镜头保留相同人物与桌面陈设。",
        "sound_plan": "桌面环境声、纸页和杯碟声，最后一句鲸鲸自述。配乐由审阅者确认授权。",
        "shots": [
            {"duration": 6, "action": "鲸鲸写下几行想法，手悬在发送键前。",
             "dialogue": "本鱼差点又要抢答。", "visual_prompt": "近景跟随手和草稿移动，尾巴轻拍椅背。"},
            {"duration": 7, "action": "她把可查来源的纸条和自己的猜想摊成两摞。",
             "dialogue": "", "visual_prompt": "俯拍纸条被推开，画面只保留抽象记号，无真实聊天或账号内容。"},
            {"duration": 7, "action": "她删掉一句太肯定的评论，把留下的想法读了一遍。",
             "dialogue": "查得到的认真讲，猜的就留给明天。", "visual_prompt": "从桌面慢慢拉远，停在鲸鲸和手边的杯子。"},
        ],
    }, owner=scope, session="wechat:" + scope)
    return ("pending-review", row["id"], "updream-preview-required")


def submit(store, scope: str, source: str, category: str, timestamp: int) -> dict:
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
            status, output, reason = _draft_video(store, scope, timestamp)
        except (OSError, ValueError):
            status, output, reason = ("blocked", "", "video-brief-unconfirmed")
    else:
        try:
            status, output, reason = _write_bili_report(job_id, timestamp)
        except (bili.BiliError, OSError, ValueError, AttributeError):
            status, output, reason = ("blocked", "", "report-unconfirmed")
        if status == "completed" and category == "bili-report-qq":
            status, reason = "document-ready", "qq-send-unavailable"
    with store._connect() as conn:
        conn.execute("UPDATE wechat_jobs SET status=?,output=?,reason=? WHERE scope=? AND source=?",
                     (status, output, reason, scope, source))
    receipt = {"ok": True, "id": job_id, "category": category, "status": status, "output": output, "reason": reason}
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
