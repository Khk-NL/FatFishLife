"""Public video discovery from explicit subscriptions; never publishes content."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class DiscoveryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS subscriptions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target TEXT NOT NULL, "
                "UNIQUE(kind,target));"
                "CREATE TABLE IF NOT EXISTS candidates ("
                "bvid TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL, "
                "url TEXT NOT NULL, published_at TEXT NOT NULL, play INTEGER, "
                "sources TEXT NOT NULL, discovered_at TEXT NOT NULL);"
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def subscribe(self, kind: str, target: str) -> int:
        target = " ".join(str(target).split())
        if kind not in ("keyword", "up") or not target:
            raise ValueError("订阅类型应为关键词或 UP，且目标不能为空")
        if kind == "up" and not target.isdigit():
            raise ValueError("UP 订阅需要数字 UID")
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO subscriptions(kind,target) VALUES (?,?)", (kind, target))
            row = connection.execute("SELECT id FROM subscriptions WHERE kind=? AND target=?", (kind, target)).fetchone()
            return row["id"]

    def subscriptions(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT id,kind,target FROM subscriptions ORDER BY id")]

    def unsubscribe(self, subscription_id: int) -> bool:
        with self._connect() as connection:
            result = connection.execute("DELETE FROM subscriptions WHERE id=?", (subscription_id,))
            return result.rowcount > 0

    def contains(self, bvid: str) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM candidates WHERE bvid=?", (bvid,)).fetchone() is not None

    def record(self, item: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO candidates(bvid,title,author,url,published_at,play,sources,discovered_at) VALUES (?,?,?,?,?,?,?,?)",
                (item["bvid"], item["title"], item["author"], item["url"], item["published_at"], item["play"], json.dumps(item["sources"], ensure_ascii=False), datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )


def _items(payload: dict, subscription: dict) -> list[dict]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("返回数据缺少 items 列表")
    result = []
    label = ("关键词：" if subscription["kind"] == "keyword" else "UP：") + subscription["target"]
    for item in data["items"]:
        if not isinstance(item, dict):
            raise ValueError("返回的视频条目不是对象")
        bvid = str(item.get("bvid") or "")
        title = str(item.get("title") or "").strip()
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid) or not title:
            raise ValueError("返回的视频条目缺少有效 BV 号或标题")
        raw_play = item.get("play")
        try:
            play = max(0, int(str(raw_play).replace(",", "")))
        except (ValueError, TypeError):
            play = None
        author = item.get("author") or {}
        author_name = str(author.get("name") or "") if isinstance(author, dict) else str(author)
        result.append({"bvid": bvid, "title": title, "author": author_name or ("UP " + subscription["target"] if subscription["kind"] == "up" else "未知"), "url": f"https://www.bilibili.com/video/{bvid}", "published_at": str(item.get("pubdate") or ""), "play": play, "sources": [label]})
    return result


async def discover(store: DiscoveryStore, run, remember) -> dict:
    """Read latest public videos, then persist only candidates saved to public memory."""
    subscriptions = store.subscriptions()
    candidates: dict[str, dict] = {}
    errors = []
    for subscription in subscriptions:
        label = ("关键词：" if subscription["kind"] == "keyword" else "UP：") + subscription["target"]
        args = ("search", "video", subscription["target"]) if subscription["kind"] == "keyword" else ("user", "videos", subscription["target"])
        payload = await run(*args, "--order", "new", "--size", "5", timeout=90)
        if not isinstance(payload, dict) or not payload.get("ok"):
            error = (payload.get("error") or {}) if isinstance(payload, dict) else {}
            errors.append(f"{label}：{error.get('code', 'invalid_response')} {error.get('message', '视频来源未返回成功结果')}")
            continue
        try:
            items = _items(payload, subscription)
        except ValueError as exc:
            errors.append(f"{label}：{exc}")
            continue
        for item in items:
            if store.contains(item["bvid"]):
                continue
            previous = candidates.get(item["bvid"])
            if previous:
                previous["sources"].extend(source for source in item["sources"] if source not in previous["sources"])
                if item["play"] is not None and (previous["play"] is None or item["play"] > previous["play"]):
                    previous["play"] = item["play"]
            else:
                candidates[item["bvid"]] = item
    saved = []
    for item in sorted(candidates.values(), key=lambda candidate: (candidate["play"] if candidate["play"] is not None else -1), reverse=True):
        content = f"公开选题候选《{item['title']}》；UP：{item['author']}；{item['url']}；播放量参考：{item['play'] if item['play'] is not None else '未知'}"
        if not remember(content, scope="public", kind="video"):
            errors.append(f"{item['bvid']}：未能写入公开记忆，保留待下次发现重试")
            continue
        store.record(item)
        saved.append(item)
    return {"candidates": saved, "errors": errors, "sources": len(subscriptions)}
