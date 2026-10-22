from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .publisher import PublishError, PublishMeta, _read_json, get_status, publish


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="fatfish-bili", description="审阅成片投稿草稿，明确确认后才上传")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("publish", help="默认只生成本地投稿草稿")
    create.add_argument("video", type=Path)
    create.add_argument("--meta", required=True, type=Path, help="明确提供标题、简介、标签、zone 和 tid 的 JSON")
    create.add_argument("--report", type=Path, help="默认使用同名 .result.json 渲染报告")
    create.add_argument("--draft", type=Path, help="草稿 JSON 路径")
    create.add_argument("--confirm", action="store_true", help="明确确认上传成片并提交稿件")
    status = commands.add_parser("status", help="查询已提交稿件的审核状态")
    status.add_argument("bvid")
    for command in (create, status):
        command.add_argument("--bili", default="bili", help="bili-cli 可执行文件")
        command.add_argument("--bili-home", type=Path, help="使用已登录的独立 bili-cli 配置目录")
    try:
        args = parser.parse_args(argv)
        if args.command == "publish":
            result = publish(args.video, PublishMeta.from_dict(_read_json(args.meta, "投稿元数据")),
                             report=args.report, draft=args.draft, dry_run=not args.confirm,
                             bili_exe=args.bili, bili_home=args.bili_home).as_dict()
        else:
            result = get_status(args.bvid, bili_exe=args.bili, bili_home=args.bili_home)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PublishError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
