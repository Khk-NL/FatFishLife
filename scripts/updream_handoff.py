"""Local storyboard handoff and exported-media verification; no Updream API calls."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fatfish_video.project import ProjectError, load_project
from fatfish_video.renderer import RenderError, find_tools, probe_media


def export_storyboard(project_path: str | Path, destination: str | Path) -> dict:
    project = load_project(project_path)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"交接目录已存在，不覆盖：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=destination.name + "-", dir=destination.parent) as scratch:
        temporary = Path(scratch)
        (temporary / "assets").mkdir()
        assets = {}
        for index, (key, asset) in enumerate(project.assets.items(), 1):
            relative = "assets/" + f"{index:03d}-" + asset.path.name
            shutil.copyfile(asset.path, temporary / relative)
            assets[key] = {"path": relative, "crop": asset.crop}
        if project.music:
            relative = "assets/music-" + project.music.path.name
            shutil.copyfile(project.music.path, temporary / relative)
            music = {"path": relative, "speed": project.music.speed, "pitch": project.music.pitch}
        else:
            music = None
        scenes = []
        lines = [f"# {project.title}", "", "请按以下分镜顺序制作；保留角色身份、字幕内容和画面比例。", "素材授权、平台生成参数与导出效果由创作者确认。本文件不会上传任何内容。", "", f"目标：{project.width}×{project.height}，{project.fps} fps，{project.duration:g} 秒。", ""]
        start = 0.0
        for index, scene in enumerate(project.scenes, 1):
            duration = scene.frames / project.fps
            captions = [{"start": caption.start, "end": caption.end, "text": caption.text} for caption in scene.captions]
            scenes.append({"index": index, "start": start, "duration": duration, "template": scene.template, "roles": [role.asset for role in scene.roles], "panel": scene.panel.asset if scene.panel else None, "captions": captions})
            lines.extend([f"## 镜头 {index}（{start:g}—{start + duration:g} 秒）", "", "角色素材：" + "、".join(role.asset for role in scene.roles), "配图素材：" + (scene.panel.asset if scene.panel else "无"), "字幕："])
            lines.extend(f"- {caption.start:g}—{caption.end:g} 秒：{caption.text}" for caption in scene.captions)
            lines.append("")
            start += duration
        manifest = {"schema_version": 1, "status": "prepared_for_updream", "title": project.title, "width": project.width, "height": project.height, "fps": project.fps, "duration": project.duration, "assets": assets, "music": music, "scenes": scenes, "rights_confirmed": False, "uploaded": False}
        (temporary / "storyboard.md").write_text("\n".join(lines), encoding="utf-8")
        (temporary / "handoff.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Publishing by copying also works when Windows denies renaming a
        # recently populated directory. copytree still refuses an existing target.
        shutil.copytree(temporary, destination)
    return {"status": manifest["status"], "directory": str(destination), "storyboard": str(destination / "storyboard.md"), "manifest": str(destination / "handoff.json"), "uploaded": False}


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


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Updream 本地交接，不登录、不上传、不发布")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="从已校验项目生成分镜和素材交接包")
    export.add_argument("project")
    export.add_argument("destination")
    verify = commands.add_parser("verify-export", help="完整解码检查手动导出的视频")
    verify.add_argument("video")
    verify.add_argument("report")
    args = parser.parse_args(argv)
    try:
        payload = export_storyboard(args.project, args.destination) if args.command == "export" else verify_export(args.video, args.report)
    except (OSError, ValueError, ProjectError, RenderError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
