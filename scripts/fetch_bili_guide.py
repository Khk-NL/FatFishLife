"""把 B 站视频的字幕和 AI 总结整理成攻略文档。

依赖 bili-cli 的 `video watch`（已登录），只读取，不互动。
用法：python scripts/fetch_bili_guide.py BV1VA8a6xE93 BV1n9uq6NEWu
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BILI = "D:/Code/Apps/bili-venv/Scripts/bili.exe"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "guides"
HOME = "C:/Users/kongb/AppData/Roaming/bili-cli"


def watch(bvid: str) -> dict:
    env = __import__("os").environ.copy()
    env["BILI_CLI_HOME"] = HOME
    result = subprocess.run(
        [BILI, "video", "watch", bvid],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=300,
    )
    data = json.loads(result.stdout)
    if not data.get("ok"):
        raise RuntimeError(data.get("error"))
    return data["data"]


def transcript_text(payload: dict) -> str:
    transcript = payload.get("transcript") or {}
    if isinstance(transcript, str):
        return transcript
    segments = transcript.get("segments") or transcript.get("items") or []
    if isinstance(segments, list):
        return "\n".join(str(seg.get("text") or "").strip() for seg in segments if seg.get("text"))
    return str(transcript)


def save(bvid: str) -> Path:
    data = watch(bvid)
    title = str(data.get("title") or bvid)
    body = [
        f"# {title}",
        "",
        f"- 视频：https://www.bilibili.com/video/{bvid}",
        f"- UP 主：{(data.get('owner') or {}).get('name', '')}",
        f"- 发布：{data.get('pubdate', '')}",
        f"- 时长：{data.get('duration', 0)} 秒",
        "",
        "## AI 总结",
        "",
        str(data.get("ai_summary") or "（无）"),
        "",
        "## 字幕",
        "",
    ]
    body.append(transcript_text(data) or "（没有字幕）")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|]", "_", title)[:80]
    path = OUT_DIR / f"视频-{safe}.md"
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def main() -> None:
    for bvid in sys.argv[1:]:
        try:
            path = save(bvid)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {bvid}: {exc}")
            continue
        print(f"[ok] {bvid} -> {path}")


if __name__ == "__main__":
    main()
