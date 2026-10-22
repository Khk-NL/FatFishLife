from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fatfish_video.project import ProjectError
from fatfish_video.renderer import RenderError, render_project

from .options import StoryOptions
from .pipeline import StoryError, generate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fatfish-story", description="话题生成文案分镜并合成视频")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="生成项目配置，默认继续渲染成片")
    create.add_argument("--topic", required=True, help="话题或素材摘要")
    create.add_argument("--duration", type=float, default=30.0, help="目标总时长，默认 30 秒")
    create.add_argument("--template", choices=["single", "dialogue", "news"], help="指定模板")
    create.add_argument("--character", action="append", default=[], help="指定角色 ID 或名字，可重复")
    create.add_argument("--panel", help="资讯截图路径（news 模板）")
    create.add_argument("--out", help="项目配置 JSON 路径；默认 outputs/generated/<时间>-<话题>.json")
    create.add_argument("--output", help="成片 MP4 路径；默认与配置同名")
    create.add_argument("--provider", choices=["deepseek", "mock"], help="模型提供方，默认 deepseek")
    create.add_argument("--model", default="deepseek-chat")
    create.add_argument("--tone", default="牢大式吐槽")
    create.add_argument("--no-render", action="store_true", help="只生成配置，不合成视频")
    create.add_argument("--overwrite", action="store_true", help="允许替换已有成片")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        config_path = Path(args.out).resolve() if args.out else None
        if config_path is not None and config_path.suffix.lower() != ".json":
            raise StoryError("--out 必须是 .json 文件")
        options = StoryOptions(
            topic=args.topic,
            duration=args.duration,
            template=args.template,
            characters=tuple(args.character),
            tone=args.tone,
            panel=Path(args.panel).resolve() if args.panel else None,
            config_path=config_path,
            config_dir=config_path.parent if config_path else None,
            output=Path(args.output).resolve() if args.output else None,
            provider=args.provider,
            model=args.model,
        )
        generated = generate_project(options)
        result = {
            "status": "completed",
            "config": str(generated.config_path),
            "title": generated.project.title,
            "duration": generated.project.duration,
            "metadata": generated.metadata,
        }
        if not args.no_render:
            rendered = render_project(
                generated.project,
                output=generated.project.output,
                overwrite=args.overwrite,
                progress=lambda message: print(message, file=sys.stderr),
            )
            result["render"] = rendered.as_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoryError, ProjectError, RenderError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
