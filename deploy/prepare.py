"""Inspect the deployment inputs; write fresh plugin defaults only with --write."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
PLUGINS = tuple("astrbot_plugin_fatfish_" + name for name in (
    "memory", "bili", "offline", "lore", "life", "story", "obsidian", "steam", "voice", "style",
))
PACKAGES = ("fatfish_core", "fatfish_video", "fatfish_story", "fatfish_bili")


def prepare(*, state_dir: Path | None = None, write: bool = False) -> dict:
    state_dir = (state_dir or DEPLOY / "state").resolve()
    templates = sorted((DEPLOY / "config").glob("*.json.example"))
    configs = {path.name.removesuffix(".example"): json.loads(path.read_text(encoding="utf-8")) for path in templates}
    bili = configs["astrbot_plugin_fatfish_bili_config.json"]
    if not bili.get("dry_run_writes") or bili.get("enable_inbox_poll") or bili.get("auto_reply"):
        raise ValueError("部署初始配置必须关闭自动回复和轮询，并保留 dry_run_writes")
    offline = configs["astrbot_plugin_fatfish_offline_config.json"]
    if offline.get("local_model_enabled"):
        raise ValueError("服务器初始配置不应启用本地模型；先验证远程 PC 服务或服务器内存")
    life = configs["astrbot_plugin_fatfish_life_config.json"]
    if life.get("publish_enabled"):
        raise ValueError("部署初始配置必须关闭生活动态发布")
    obsidian = configs["astrbot_plugin_fatfish_obsidian_config.json"]
    if obsidian.get("enabled") or obsidian.get("vault_path"):
        raise ValueError("部署初始配置必须关闭知识库同步，等待主人提供 vault 路径")
    story = configs["astrbot_plugin_fatfish_story_config.json"]
    if story.get("zone") or story.get("tid") or story.get("owner_qq"):
        raise ValueError("部署初始配置必须等待主人填写视频投稿分区和审阅账号")
    required = [ROOT / "pyproject.toml", ROOT / "assets", ROOT / "examples", ROOT / "docs/persona/apple-le-full.md"]
    required.extend(ROOT / package for package in PACKAGES)
    required.extend(ROOT / "bots" / plugin / "main.py" for plugin in PLUGINS)
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
        for name in ("outputs", "qq", "napcat", "napcat-plugins", "astrbot/plugins"):
            (state_dir / name).mkdir(parents=True, exist_ok=True)
    return {
        "status": "prepared" if write else "checked", "state_dir": str(state_dir),
        "templates": len(configs), "written": written, "preserved": preserved,
        "plugins": list(PLUGINS), "default_services": ["astrbot", "napcat"],
        "local_model_enabled": False, "docker_available": shutil.which("docker") is not None,
        "services_started": False,
        "pending": ["服务器内存容量与 Docker Compose 运行验证", "社区 meme_manager、proactive_chat 的安装与数据迁移", "主人身份、模型及账号登录",
                    "视频主人看片、明确分区与投稿审核", "Obsidian vault 只读挂载与独立私人检索", "Steam 商店连接与代理、语音及表情语义实测"],
    }


def bundle(destination: Path) -> dict:
    """Create a source-only bundle from known inputs; never visit runtime data."""
    destination = destination.resolve()
    files = [ROOT / "pyproject.toml", DEPLOY / "Dockerfile", DEPLOY / "Dockerfile.dockerignore",
             DEPLOY / "compose.yaml", DEPLOY / "prepare.py", DEPLOY / "README.md", DEPLOY / ".env.example"]
    directories = [*(ROOT / package for package in PACKAGES), *(ROOT / "bots" / plugin for plugin in PLUGINS),
                   ROOT / "assets", ROOT / "examples", ROOT / "docs/persona", DEPLOY / "config"]
    for directory in directories:
        for path in directory.rglob("*"):
            relative = path.relative_to(ROOT)
            if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT)
                    or any(part in ("__pycache__", ".git", "state", ".web-data", "node_modules") for part in relative.parts)
                    or any(part.startswith(".") for part in relative.parts)
                    or path.suffix in (".pyc", ".db", ".sqlite", ".sqlite3", ".log")
                    or directory == DEPLOY / "config" and not path.name.endswith(".json.example")):
                continue
            files.append(path)
    manifest = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(set(files)):
                relative = path.relative_to(ROOT).as_posix()
                archive.write(path, relative)
                manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.writestr("deploy/bundle-manifest.json", json.dumps({"sha256": manifest}, ensure_ascii=False, indent=2))
    except BaseException:
        # Preserve any pre-existing archive; discard only this call's partial file.
        if manifest:
            destination.unlink(missing_ok=True)
        raise
    return {"path": str(destination), "files": len(manifest), "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "runtime_data_included": False}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查部署材料；默认不写入、不启动服务")
    parser.add_argument("--write", action="store_true", help="仅创建缺失的状态目录和初始插件配置")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--bundle", type=Path, help="另存源码与素材 ZIP，不含凭据、数据库、日志或运行状态")
    args = parser.parse_args(argv)
    try:
        result = prepare(state_dir=args.state_dir, write=args.write)
        if args.bundle:
            result["bundle"] = bundle(args.bundle)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"错误：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
