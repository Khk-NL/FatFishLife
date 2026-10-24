"""Verify exported media without changing or publishing the source."""
import json
from pathlib import Path
import subprocess
from fatfish_video.renderer import RenderError, find_tools, probe_media

def verify_export(video_path: str | Path, report_path: str | Path) -> dict:
    video, report = Path(video_path).resolve(), Path(report_path).resolve()
    if not video.is_file():
        raise FileNotFoundError(f"找不到导出视频：{video}")
    if report.exists():
        raise FileExistsError(f"验证报告已存在，不覆盖：{report}")
    if video == report:
        raise ValueError("验证报告不能覆盖视频源文件")
    info = probe_media(video)
    streams = info.get("streams") or []
    visual = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    duration = float((info.get("format") or {}).get("duration") or 0)
    if visual is None or duration <= 0:
        raise ValueError("导出文件没有有效视频轨或正数时长")
    ffmpeg, _ = find_tools()
    try:
        result = subprocess.run([str(ffmpeg), "-v", "error", "-xerror", "-i", str(video), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"], capture_output=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("导出视频完整解码超过 300 秒，未生成通过报告") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[-400:].strip()
        raise RenderError("导出视频无法完整解码：" + detail)
    payload = {"schema_version": 1, "status": "validated", "source": "updream_manual_export", "video": str(video), "width": visual.get("width"), "height": visual.get("height"), "frame_rate": visual.get("avg_frame_rate"), "duration": duration, "has_audio": any(stream.get("codec_type") == "audio" for stream in streams), "fully_decoded": True, "published": False, "rights_confirmed": False}
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return payload

