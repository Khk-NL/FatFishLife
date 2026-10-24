"""Owner-reviewed video submissions, bound to the exact files shown in preview."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from fatfish_bili.publisher import PublishError, PublishMeta, _checked_outputs, publish


class ReviewError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _fingerprint(row: dict) -> str:
    material = {
        "files": {key: _digest(Path(row[key])) for key in ("video", "cover", "report")},
        "metadata": row["metadata"],
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class ReviewQueue:
    """Persist before uploading; unknown remote outcomes never become retryable."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, review_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", review_id):
            raise ReviewError("请提供预览消息中的 12 位审阅编号")
        return self.directory / f"{review_id}.json"

    def _save(self, row: dict):
        target = self._path(row["id"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, suffix=".tmp", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(row, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get(self, review_id: str, *, owner: str, session: str) -> dict:
        try:
            row = json.loads(self._path(review_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReviewError("找不到这个审阅编号") from exc
        if row.get("owner") != str(owner) or row.get("session") != str(session):
            raise ReviewError("请由收到预览的老板在同一私聊中操作")
        return row

    def create(self, video: str | Path, metadata: dict, *, owner: str, session: str, topic: str, report: str | Path | None = None) -> dict:
        video = Path(video).resolve()
        report = Path(report).resolve() if report is not None else video.with_suffix(".result.json")
        cover = _checked_outputs(video, report)
        row = {
            "id": secrets.token_hex(6), "owner": str(owner), "session": str(session),
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "pending_preview",
            "topic": topic, "video": str(video), "cover": str(cover), "report": str(report),
            "metadata": dict(metadata),
        }
        # An unfinished partition configuration still allows local generation and preview.
        try:
            PublishMeta.from_dict(metadata)
        except PublishError as exc:
            row["metadata_error"] = str(exc)
        row["fingerprint"] = _fingerprint(row)
        with self._lock:
            self._save(row)
        return row

    def mark_preview(self, review_id: str, *, owner: str, session: str) -> dict:
        with self._lock:
            row = self.get(review_id, owner=owner, session=session)
            if row["status"] not in ("pending_preview", "awaiting_approval"):
                raise ReviewError("此稿件已经处理，不能再次等待批准")
            if _fingerprint(row) != row["fingerprint"]:
                raise ReviewError("预览文件已经变化，请重新制作预览")
            row["status"] = "awaiting_approval"
            row["previewed_at"] = datetime.now(timezone.utc).isoformat()
            self._save(row)
            return row

    def revise(self, review_id: str, metadata: dict, *, owner: str, session: str) -> dict:
        """Changed metadata requires a new preview and a new confirmation identifier."""
        with self._lock:
            previous = self.get(review_id, owner=owner, session=session)
            if previous["status"] not in ("pending_preview", "awaiting_approval"):
                raise ReviewError("已提交或状态未确认的稿件不能生成重复投稿入口")
            if previous["metadata"] == metadata:
                return previous
            row = self.create(previous["video"], metadata, owner=owner, session=session,
                              topic=previous["topic"], report=previous["report"])
            previous["status"] = "superseded"
            previous["replaced_by"] = row["id"]
            self._save(previous)
            return row

    def submit(self, review_id: str, *, owner: str, session: str, bili_exe="bili", bili_home=None) -> dict:
        with self._lock:
            row = self.get(review_id, owner=owner, session=session)
            if row["status"] != "awaiting_approval":
                raise ReviewError("此稿件尚未成功发送预览，或已提交/取消/状态未确认；不会重复投稿")
            try:
                unchanged = _fingerprint(row) == row["fingerprint"]
            except OSError as exc:
                raise ReviewError("预览产物已丢失，请重新制作") from exc
            if not unchanged:
                raise ReviewError("视频、封面、报告或投稿信息已变化，请重新制作并预览")
            meta = PublishMeta.from_dict(row["metadata"])
            row["status"] = "submitting"
            row["approved_at"] = datetime.now(timezone.utc).isoformat()
            self._save(row)
            try:
                result = publish(row["video"], meta, report=row["report"],
                                 draft=self.directory / f"{review_id}.publish-draft.json",
                                 dry_run=False, bili_exe=bili_exe, bili_home=bili_home)
            except BaseException as exc:
                row["status"] = "uncertain"
                row["error_code"] = type(exc).__name__
                self._save(row)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ReviewError("投稿结果未确认，已停止重复提交；请先核查 B 站稿件列表") from exc
            row["status"] = "submitted"
            row["result"] = result.as_dict()
            self._save(row)
            return row

    def cancel(self, review_id: str, *, owner: str, session: str) -> dict:
        with self._lock:
            row = self.get(review_id, owner=owner, session=session)
            if row["status"] not in ("pending_preview", "awaiting_approval"):
                raise ReviewError("已经提交或状态未确认，取消本地审批不能撤回远端稿件")
            row["status"] = "cancelled"
            self._save(row)
            return row
