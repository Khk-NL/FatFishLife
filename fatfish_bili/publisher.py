from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishMeta:
    title: str
    description: str
    tags: tuple[str, ...]
    zone: int
    tid: int
    ai_declare: bool = True
    private: bool = False

    def __post_init__(self):
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 80:
            raise PublishError("标题需为 1～80 字")
        if not isinstance(self.description, str) or len(self.description) > 2000:
            raise PublishError("简介必须明确提供，最多 2000 字")
        if not isinstance(self.tags, (list, tuple)) or not 1 <= len(self.tags) <= 10:
            raise PublishError("标签需为包含 1～10 个标签的数组")
        if any(not isinstance(tag, str) or not tag.strip() or "," in tag for tag in self.tags):
            raise PublishError("标签不能为空，单个标签不能含英文逗号")
        for name in ("zone", "tid"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise PublishError(f"{name} 必须明确提供正整数分区 ID")
        if type(self.ai_declare) is not bool or type(self.private) is not bool:
            raise PublishError("ai_declare 和 private 必须为布尔值")
        object.__setattr__(self, "tags", tuple(tag.strip() for tag in self.tags))

    @classmethod
    def from_dict(cls, value: dict) -> PublishMeta:
        if not isinstance(value, dict):
            raise PublishError("投稿元数据必须是 JSON 对象")
        try:
            return cls(**value)
        except TypeError as exc:
            raise PublishError("投稿元数据需包含 title、description、tags、zone、tid，且不能有未知字段") from exc

    def as_dict(self) -> dict:
        result = asdict(self)
        result["tags"] = list(self.tags)
        return result


@dataclass(frozen=True)
class PublishResult:
    status: str
    draft: Path
    video: Path
    cover: Path
    metadata: dict
    command: tuple[str, ...]
    bvid: str | None = None
    aid: int | None = None
    url: str | None = None
    receipt: Path | None = None

    def as_dict(self) -> dict:
        result = asdict(self)
        for key in ("draft", "video", "cover", "receipt"):
            if result[key] is not None:
                result[key] = str(result[key])
        result["command"] = list(self.command)
        return result


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PublishError(f"无法读取{label}：{path}") from exc
    if not isinstance(value, dict):
        raise PublishError(f"{label}必须是 JSON 对象")
    return value


def _artifact(report: Path, value, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PublishError(f"渲染报告缺少{label}路径")
    path = Path(value)
    return (path if path.is_absolute() else report.parent / path).resolve()


def _checked_outputs(video: Path, report: Path) -> Path:
    data = _read_json(report, "渲染报告")
    if data.get("schema_version") != 1 or data.get("status") != "completed":
        raise PublishError("只接受 schema_version=1 且 status=completed 的渲染报告")
    if _artifact(report, data.get("video"), "视频") != video:
        raise PublishError("所选视频与渲染报告不匹配")
    if _artifact(report, data.get("report"), "报告") != report:
        raise PublishError("渲染报告的自身路径与所选报告不匹配")
    cover = _artifact(report, data.get("cover"), "封面")
    for path, label in ((video, "视频"), (cover, "封面")):
        if not path.is_file() or not path.stat().st_size:
            raise PublishError(f"{label}文件不存在或为空：{path}")
    return cover


def _call(command: list[str], *, bili_home: str | Path | None, timeout: float) -> dict:
    env = os.environ.copy()
    if bili_home is not None:
        env["BILI_CLI_HOME"] = str(Path(bili_home).resolve())
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PublishError("bili-cli 超时，远端状态尚未确认；请先检查稿件状态再决定是否重试") from exc
    except OSError as exc:
        raise PublishError("无法启动 bili-cli，请检查 --bili 路径") from exc
    try:
        response = json.loads(process.stdout)
    except ValueError as exc:
        raise PublishError(f"bili-cli 未返回有效 JSON（退出码 {process.returncode}）") from exc
    if not isinstance(response, dict) or process.returncode != 0 or response.get("ok") is not True:
        error = response.get("error", {}) if isinstance(response, dict) else {}
        if not isinstance(error, dict):
            error = {}
        message = str(error.get("message") or "命令失败")[:400]
        code = str(error.get("code") or process.returncode)
        raise PublishError(f"bili-cli 失败 [{code}]：{message}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise PublishError("bili-cli 成功响应缺少有效 data")
    return data


def publish(
    video: str | Path,
    meta: PublishMeta,
    *,
    report: str | Path | None = None,
    draft: str | Path | None = None,
    dry_run: bool = True,
    bili_exe: str | Path = "bili",
    bili_home: str | Path | None = None,
    timeout: float = 1800,
) -> PublishResult:
    """Save a local draft by default; only dry_run=False invokes an upload."""
    if type(dry_run) is not bool:
        raise PublishError("dry_run 必须明确使用 True 或 False")
    if not isinstance(meta, PublishMeta):
        raise PublishError("meta 必须是已校验的 PublishMeta")
    video = Path(video).resolve()
    report = Path(report).resolve() if report is not None else video.with_suffix(".result.json")
    cover = _checked_outputs(video, report)
    draft = Path(draft).resolve() if draft is not None else video.with_suffix(".publish-draft.json")
    receipt = draft.with_name(draft.stem + ".result.json")
    if draft.suffix.lower() != ".json" or draft in (video, cover, report) or receipt in (video, cover, report):
        raise PublishError("草稿和回执必须使用独立的 JSON 路径，不能覆盖渲染产物")
    command = [str(bili_exe), "upload", "video", str(video), "--title", meta.title,
               "--desc", meta.description, "--cover", str(cover), "--zone", str(meta.zone), "--tid", str(meta.tid)]
    for tag in meta.tags:
        command.extend(("--tag", tag))
    command.append("--ai-declare" if meta.ai_declare else "--no-ai-declare")
    if meta.private:
        command.append("--private")
    result = PublishResult("draft", draft, video, cover, meta.as_dict(), tuple(command))
    payload = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
               "render_report": str(report), "dry_run": True, **result.as_dict()}
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if dry_run:
        return result
    data = _call(command, bili_home=bili_home, timeout=timeout)
    bvid = data.get("bvid")
    if data.get("dry_run") or not isinstance(bvid, str) or not bvid.startswith("BV") or not bvid.isalnum():
        raise PublishError("bili-cli 没有返回已提交稿件的 BV 号，不能确认投稿成功")
    result = PublishResult("submitted", draft, video, cover, meta.as_dict(), tuple(command), bvid,
                           data.get("aid"), f"https://www.bilibili.com/video/{bvid}", receipt)
    receipt.write_text(json.dumps({"schema_version": 1, "submitted_at": datetime.now(timezone.utc).isoformat(),
                                   "render_report": str(report), "dry_run": False, "review_status": "pending",
                                   **result.as_dict()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def get_status(bvid: str, *, bili_exe: str | Path = "bili", bili_home: str | Path | None = None, timeout: float = 60) -> dict:
    """Read the server's current review state; submission alone is not publication."""
    if not isinstance(bvid, str) or not bvid.startswith("BV") or not bvid.isalnum():
        raise PublishError("请提供稿件 BV 号")
    return _call([str(bili_exe), "upload", "status", bvid], bili_home=bili_home, timeout=timeout)
