"""Expose the existing bundled decoder to community/native audio components."""

import logging
import os
from pathlib import Path
import shutil


def ensure_ffmpeg_on_path() -> Path | None:
    available = shutil.which("ffmpeg")
    if available:
        return Path(available)
    from fatfish_video.renderer import RenderError, _resolve_tool

    try:
        executable = _resolve_tool("ffmpeg")
    except RenderError:
        logging.getLogger(__name__).warning("未找到 FFmpeg，语音解码暂不可用")
        return None
    os.environ["PATH"] = str(executable.parent) + os.pathsep + os.environ.get("PATH", "")
    return executable
