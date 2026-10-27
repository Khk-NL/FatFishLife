"""B 站业务：把 bili-cli 的调用从 AstrBot 插件里抽出来。

原则：
- 只封装「跑 CLI + 解析 JSON」，不碰 AstrBot 事件和消息类。
- 读操作默认开放；写操作（发评论/私信/三连）必须显式开启并带 dry_run 语义。
- CLI 路径、凭据目录走环境变量，不写死。
- 所有返回值都是 bili-cli 的原始 JSON，出错时带 code/message，便于上层判断。

环境变量：
    FATFISH_BILI_EXE    bili 可执行文件，默认 bili
    FATFISH_BILI_HOME   凭据目录，默认 %APPDATA%/bili-cli
    FATFISH_BILI_WRITE  1 才允许写操作，默认 0
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 180


class BiliError(RuntimeError):
    pass


def _exe() -> str:
    return os.environ.get("FATFISH_BILI_EXE", "bili").strip() or "bili"


def _home() -> str:
    value = os.environ.get("FATFISH_BILI_HOME", "").strip()
    if value:
        return value
    appdata = os.environ.get("APPDATA", "")
    return str(Path(appdata) / "bili-cli") if appdata else ""


def writes_allowed() -> bool:
    return os.environ.get("FATFISH_BILI_WRITE", "0").strip() == "1"


def run(*args: str, timeout: float = DEFAULT_TIMEOUT, dry_run: bool = False) -> dict:
    """跑一条 bili-cli 命令，返回解析后的 JSON。"""
    command = [_exe()]
    if dry_run:
        command.append("--dry-run")
    command.extend(str(a) for a in args)

    env = os.environ.copy()
    home = _home()
    if home:
        env["BILI_CLI_HOME"] = home

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise BiliError(f"找不到 bili-cli：{_exe()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BiliError(f"bili-cli 超过 {timeout:.0f} 秒未返回") from exc

    text = (completed.stdout or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        tail = (completed.stderr or text)[-300:].strip()
        raise BiliError(f"bili-cli 没有返回 JSON：{tail}") from None


def _require_writes(action: str) -> None:
    if not writes_allowed():
        raise BiliError(f"{action} 属于写操作，需 FATFISH_BILI_WRITE=1 才允许")


# ---------- 读 ----------

def account_status() -> dict:
    return run("auth", "status")


def search(keyword: str, *, size: int = 10) -> dict:
    if not str(keyword or "").strip():
        raise BiliError("关键词为空")
    return run("search", "video", str(keyword).strip(), "--size", str(max(1, min(50, size))))


def video_info(bvid: str) -> dict:
    if not str(bvid or "").strip():
        raise BiliError("BV 号为空")
    return run("video", "info", str(bvid).strip())


def video_transcript(bvid: str) -> dict:
    """读视频字幕/AI 总结，用于把攻略类视频转成文字。"""
    return run("video", "watch", str(bvid).strip(), timeout=240)


def feed_recommend(*, count: int = 10, unseen: bool = True) -> dict:
    args = ["feed", "recommend", "-n", str(max(1, min(30, count)))]
    if unseen:
        args.append("--unseen")
    return run(*args, timeout=120)


def comments(bvid: str, *, sort: str = "hot") -> dict:
    args = ["comment", "list", str(bvid).strip()]
    if sort:
        args += ["--sort", sort]
    return run(*args, timeout=120)


def dynamics(*, count: int = 10) -> dict:
    return run("dynamic", "list", "-n", str(max(1, min(30, count))))


def inbox() -> dict:
    return run("inbox", "list", timeout=120)


# ---------- 写（默认关闭） ----------

def post_comment(bvid: str, text: str, *, dry_run: bool = True) -> dict:
    _require_writes("发评论")
    body = str(text or "").strip()
    if not body:
        raise BiliError("评论内容为空")
    return run("comment", "post", str(bvid).strip(), body, timeout=120, dry_run=dry_run)


def reply_comment(bvid: str, rpid: str, text: str, *, dry_run: bool = True) -> dict:
    _require_writes("回复评论")
    body = str(text or "").strip()
    if not body:
        raise BiliError("回复内容为空")
    return run("comment", "reply", str(bvid).strip(), str(rpid), body, timeout=120, dry_run=dry_run)


def send_dm(uid: str, text: str, *, dry_run: bool = True) -> dict:
    _require_writes("发私信")
    body = str(text or "").strip()
    if not body:
        raise BiliError("私信内容为空")
    return run("dm", "send", str(uid).strip(), body, timeout=120, dry_run=dry_run)


def probe() -> dict:
    """连通性与登录态检查。"""
    try:
        who = account_status()
        return {"ok": bool(who.get("ok")), "exe": _exe(), "home": _home(), "writes": writes_allowed(), "who": who}
    except BiliError as exc:
        return {"ok": False, "exe": _exe(), "error": str(exc)}
