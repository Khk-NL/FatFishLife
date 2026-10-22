from __future__ import annotations

import argparse
import json
import sys

from .project import ProjectError, load_project
from .renderer import RenderError, doctor, probe_media, render_project


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="fatfish-video", description="FatFishLife 本地模板视频工具")
    commands = parser.add_subparsers(dest="command", required=True)
    health = commands.add_parser("doctor", help="检查 FFmpeg、编码器和中文字体")
    health.add_argument("--ffmpeg")
    health.add_argument("--ffprobe")
    check = commands.add_parser("validate", help="检查项目配置和素材，不生成视频")
    check.add_argument("project")
    render = commands.add_parser("render", help="合成 MP4、封面、SRT 和结果报告")
    render.add_argument("project")
    render.add_argument("--output", help="覆盖项目中的输出路径；相对当前工作目录")
    render.add_argument("--overwrite", action="store_true", help="明确替换已有输出")
    render.add_argument("--ffmpeg")
    render.add_argument("--ffprobe")
    inspect = commands.add_parser("probe", help="检查成片媒体信息")
    inspect.add_argument("video")
    inspect.add_argument("--ffprobe")
    web = commands.add_parser("serve", help="启动本机 Web 角色拼贴与音乐测试页")
    web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .web_server import serve
            serve(args.port)
            return 0
        if args.command == "doctor":
            result = doctor(args.ffmpeg, args.ffprobe)
        elif args.command == "validate":
            project = load_project(args.project)
            result = {"valid": True, "title": project.title, "scenes": len(project.scenes), "duration": project.duration,
                      "frames": project.frames, "width": project.width, "height": project.height, "fps": project.fps,
                      "output": str(project.output)}
        elif args.command == "probe":
            result = probe_media(args.video, args.ffprobe)
        else:
            result = render_project(args.project, args.output, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, overwrite=args.overwrite,
                                    progress=lambda message: print(message, file=sys.stderr)).as_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProjectError, RenderError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
