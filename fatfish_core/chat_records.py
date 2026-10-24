"""Sender-free chat migration and Markdown export, isolated by conversation."""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3

from .chat_text import collapse_chat_repeats, recorded_chat_text


EXPORT_MARKER = "<!-- fatfish-chat-memory:v1 -->"


def migrate_chat_records(db_path: Path, *, apply=False) -> dict:
    """Remove sender fields and transport text from chat rows, without raw backups.

    Notes, permission bindings and other non-chat events are unaffected. A
    dry-run opens SQLite read-only; apply changes all selected rows atomically.
    """
    db_path = Path(db_path).resolve()
    report = {"applied": apply, "checked": 0, "changed": 0, "senders_removed": 0,
              "metadata_cleared": 0, "text_cleaned": 0, "empty_removed": 0}
    mode = "rw" if apply else "ro"
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=" + mode, uri=True)) as db:
        db.row_factory = sqlite3.Row
        if apply:
            db.execute("BEGIN IMMEDIATE")
        try:
            rows = list(db.execute("SELECT id,content,actor,meta,scope FROM events WHERE kind='message'"))
            report["checked"] = len(rows)
            for row in rows:
                text = recorded_chat_text(dict(row))
                if row["scope"] == "public" and row["actor"] and row["actor"] != "bot":
                    text = text.replace(str(row["actor"]), "某人")
                sender = row["actor"] is not None
                metadata = row["meta"] not in (None, "", "{}")
                changed = not text or sender or metadata or text != row["content"]
                if not changed:
                    continue
                report["changed"] += 1
                report["senders_removed"] += int(sender)
                report["metadata_cleared"] += int(metadata)
                report["text_cleaned"] += int(text != row["content"])
                if not text:
                    report["empty_removed"] += 1
                if apply:
                    if text:
                        kind = "reply" if row["actor"] == "bot" else "message"
                        db.execute("UPDATE events SET content=?,actor=NULL,meta='{}',kind=? WHERE id=?", (text, kind, row["id"]))
                    else:
                        db.execute("DELETE FROM events WHERE id=?", (row["id"],))
            if apply:
                db.commit()
        except BaseException:
            if apply:
                db.rollback()
            raise
    return report


def _markdown_text(value) -> str:
    escaped = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()!|])", r"\\\1", escaped)


def conversation_markdown(rows, code: str, *, scope: str) -> str:
    """Render factual message text/time/counts only, never authors or relations."""
    rows = list(rows)
    folded = collapse_chat_repeats(rows)
    lines = [EXPORT_MARKER, "# 对话记忆", "", "- 会话代号：" + code,
             "- 范围：" + ("私人" if scope == "private" else "公开"),
             "- 原记录数：" + str(len(rows)),
             "- 每份仅属于一个平台和一个会话，不作为全局或跨会话资料使用。",
             "- 相邻且五分钟内相同正文合并计数；不推断人物、观点或关系。", "",
             "## 消息记录", "", "| 时间 | 正文 |", "| --- | --- |"]
    for row in folded:
        text = recorded_chat_text(row)
        if not text:
            continue
        count = row.get("repeat_count", 1)
        if count > 1:
            text += " × " + str(count)
        timestamp = row["created_at"]
        if row.get("first_at"):
            timestamp = row["first_at"] + " ～ " + timestamp
        lines.append("| " + _markdown_text(timestamp) + " | " + _markdown_text(text) + " |")
    return "\n".join(lines) + "\n"


def _local_export_directory(directory: Path) -> Path:
    directory = Path(directory).resolve()
    parents = (directory, *directory.parents)
    if not any(path.name == "outputs" or path.name == "plugin_data" and path.parent.name == "data" for path in parents):
        raise ValueError("Chat Markdown must stay under outputs or data/plugin_data")
    return directory


def export_chat_records(db_path: Path, output_dir: Path) -> dict:
    """Write a separate hashed Markdown file for each platform/UMO/scope tuple."""
    output_dir = _local_export_directory(output_dir)
    groups = defaultdict(list)
    skipped = 0
    skipped_empty = 0
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        for raw in db.execute("SELECT id,platform,scope,kind,session,content,created_at,meta "
                              "FROM events WHERE kind IN ('message','reply') ORDER BY id"):
            row = dict(raw)
            # Accept full native UMOs and Bili's explicitly bound session keys.
            # Ambiguous legacy numeric sessions stay in SQLite for migration.
            session = str(row["session"] or "")
            bound = re.fullmatch(r"[^:]+:(?:GroupMessage|FriendMessage):.+", session)
            if row["platform"] == "bilibili":
                bound = bound or re.fullmatch(r"dm:\d+|comment:BV[A-Za-z0-9]+", session)
            if not row["platform"] or row["scope"] not in {"public", "private"} or not bound:
                skipped += 1
                continue
            if not recorded_chat_text(row):
                skipped_empty += 1
                continue
            groups[(row["platform"], session, row["scope"])].append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = set()
    counts = {"conversations": 0, "records": 0, "skipped_unscoped": skipped, "skipped_empty": skipped_empty,
              "written": 0, "unchanged": 0, "removed": 0}
    for key, rows in sorted(groups.items()):
        code = hashlib.sha256(json.dumps(key, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        target = output_dir / ("conversation-" + code + ".md")
        expected.add(target.name)
        content = conversation_markdown(rows, code, scope=key[2])
        counts["conversations"] += 1
        counts["records"] += len(rows)
        if target.is_file() and target.read_text(encoding="utf-8") == content:
            counts["unchanged"] += 1
            continue
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        counts["written"] += 1
    for path in output_dir.glob("conversation-*.md"):
        if path.name in expected or not re.fullmatch(r"conversation-[0-9a-f]{64}\.md", path.name):
            continue
        if path.resolve().parent != output_dir:
            continue
        with path.open(encoding="utf-8") as source:
            generated = source.readline().strip() == EXPORT_MARKER
        if generated:
            path.unlink()
            counts["removed"] += 1
    return counts
