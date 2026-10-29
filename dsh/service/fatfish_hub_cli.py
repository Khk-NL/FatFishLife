"""FatFish 中枢命令行：给 node 插件调用，stdout 只输出 UTF-8 JSON。

用法（在仓库根目录）：
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py mood-get --scope global
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py mood-nudge --delta 0.2 --reason "被夸了"
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py lore-search --query 能天使 --limit 5
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py lore-context --query 能天使 --max-chars 1200
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py journal-write --day 2026-10-30 --content "..." --source diary
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py journal-recent --days 7
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py day-digest --day 2026-10-30
    ./.tools/dsh-python/Scripts/python.exe dsh/service/fatfish_hub_cli.py style-terms --days 7 --limit 12

成功时 stdout 打印 ``ensure_ascii=False`` 的 JSON、退出码 0；失败时 stderr 打错误、
退出码 1（若 hub 返回带 ``error`` 的降级结果，JSON 仍会打印到 stdout）。

写入权限守卫 ``FATFISH_HUB_WRITE`` 在 MCP 工具层与命令行入口都校验；
方便 node 侧做显式授权的写操作。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fatfish_core import hub  # noqa: E402


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK，强制 UTF-8 避免中文 JSON 乱码或编码崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fatfish_hub_cli", description="FatFish 中枢 JSON 命令行入口")
    sub = parser.add_subparsers(dest="command", required=True)

    item = sub.add_parser("mood-get", help="读当前心情")
    item.add_argument("--scope", default="global")

    item = sub.add_parser("mood-nudge", help="调整当前心情")
    item.add_argument("--delta", type=float, required=True)
    item.add_argument("--reason", default="")
    item.add_argument("--scope", default="global")

    item = sub.add_parser("lore-search", help="检索知识图谱")
    item.add_argument("--query", required=True)
    item.add_argument("--limit", type=int, default=5)

    item = sub.add_parser("lore-context", help="取知识图谱证据文本")
    item.add_argument("--query", required=True)
    item.add_argument("--max-chars", type=int, default=1200, dest="max_chars")

    item = sub.add_parser("journal-write", help="写日记")
    item.add_argument("--day", required=True)
    item.add_argument("--content", required=True)
    item.add_argument("--source", default="dsh")

    item = sub.add_parser("journal-recent", help="读最近几天的日记")
    item.add_argument("--days", type=int, default=7)

    item = sub.add_parser("day-digest", help="统计某天的事件")
    item.add_argument("--day", required=True)

    item = sub.add_parser("style-terms", help="抽取最近的高频说法")
    item.add_argument("--days", type=int, default=7)
    item.add_argument("--limit", type=int, default=12)
    return parser


WRITE_COMMANDS = {"mood-nudge", "journal-write"}


def _require_write_permission() -> None:
    """写命令必须显式授权：环境变量 FATFISH_HUB_WRITE=1。

    node 插件调用写操作时会带上这个变量；人手动在终端跑读命令不受影响。
    这样即使某个调用方忘了检查，也不会悄悄改掉真实记忆库。
    """
    if os.environ.get("FATFISH_HUB_WRITE") != "1":
        raise PermissionError("中枢写入未开启（FATFISH_HUB_WRITE=1 才允许）")


def _run(args: argparse.Namespace) -> dict:
    if args.command in WRITE_COMMANDS:
        _require_write_permission()
    commands = {
        "mood-get": lambda: hub.mood_get(args.scope),
        "mood-nudge": lambda: hub.mood_nudge(args.delta, args.reason, args.scope),
        "lore-search": lambda: hub.lore_search(args.query, args.limit),
        "lore-context": lambda: hub.lore_context(args.query, args.max_chars),
        "journal-write": lambda: hub.journal_write(args.day, args.content, args.source),
        "journal-recent": lambda: hub.journal_recent(args.days),
        "day-digest": lambda: hub.day_digest(args.day),
        "style-terms": lambda: hub.style_terms(args.days, args.limit),
    }
    return commands[args.command]()


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    try:
        payload = _run(args)
    except Exception as error:  # noqa: BLE001 - CLI 边界：错误只走 stderr + 退出码
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    if isinstance(payload, dict) and payload.get("error"):
        print(str(payload["error"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
