"""Inspect the deployment inputs; write fresh plugin defaults only with --write."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"


def prepare(*, state_dir: Path | None = None, write: bool = False) -> dict:
    state_dir = (state_dir or DEPLOY / "state").resolve()
    templates = sorted((DEPLOY / "config").glob("*.json.example"))
    configs = {path.name.removesuffix(".example"): json.loads(path.read_text(encoding="utf-8")) for path in templates}
    bili = configs["astrbot_plugin_fatfish_bili_config.json"]
    if not bili.get("dry_run_writes") or bili.get("enable_inbox_poll") or bili.get("auto_reply"):
        raise ValueError("部署初始配置必须关闭自动回复和轮询，并保留 dry_run_writes")
    required = [ROOT / "pyproject.toml", ROOT / "fatfish_video", ROOT / "fatfish_story", ROOT / "fatfish_bili", ROOT / "assets", ROOT / "docs/persona/apple-le-full.md"]
    required.extend(ROOT / "bots" / ("astrbot_plugin_fatfish_" + name) / "main.py" for name in ("memory", "bili", "offline", "lore", "stickers"))
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise ValueError("缺少部署输入：" + ", ".join(missing))
    written, preserved = [], []
    for name, data in configs.items():
        target = state_dir / "astrbot/config" / name
        if target.exists():
            preserved.append(name)
        elif write:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            written.append(name)
    if write:
        for name in ("outputs", "qq", "napcat", "napcat-plugins"):
            (state_dir / name).mkdir(parents=True, exist_ok=True)
    return {"status": "prepared" if write else "checked", "state_dir": str(state_dir), "templates": len(configs), "written": written, "preserved": preserved, "docker_available": shutil.which("docker") is not None, "services_started": False, "pending": ["服务器位置和 Docker Compose 运行验证", "主人身份、模型及账号登录", "Updream 创建、导出与平台条款验证", "确认后再启用真实评论、私信或投稿"]}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查部署材料；默认不写入、不启动服务")
    parser.add_argument("--write", action="store_true", help="仅创建缺失的状态目录和初始插件配置")
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = prepare(state_dir=args.state_dir, write=args.write)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
