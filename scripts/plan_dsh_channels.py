"""Create a fresh DSH Web profile containing only the selected FatFish channels."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {
    "wechat": ("dsh-wechat", "dsh-wechat"),
    "qqbot": ("dsh-onebot-qq", "dsh-onebot"),
    "snowluma": ("dsh-onebot-qq", "dsh-onebot"),
    "napcat": ("dsh-onebot-qq", "dsh-onebot"),
    "bilibili": ("dsh-bili-whale", "dsh-bili-whale"),
}
QQ_CHANNELS = {"qqbot", "snowluma", "napcat"}


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def channel_plan(channels: list[str]) -> dict:
    if len(channels) != len(set(channels)) or any(name not in CHANNELS for name in channels):
        raise ValueError("渠道不存在或重复。")
    if len(QQ_CHANNELS.intersection(channels)) > 1:
        raise ValueError("一个 profile 只使用一种 QQ 传输。")
    return {name: {"bundle": CHANNELS[name][0], "plugin": CHANNELS[name][1],
                   **({"requires": ["dsh-fatfish-life"]} if name in QQ_CHANNELS else {})}
            for name in channels}


def archive_for(spec: str) -> tuple[str, Path]:
    channel, separator, name = spec.partition("=")
    path = Path(name)
    expected = "dsh-fatfish-life" if channel == "control" else CHANNELS.get(channel, (None,))[0]
    if not separator or not expected or path.suffix != ".tgz":
        raise ValueError("安装包参数格式为 渠道=本机归档.tgz。")
    path = path.resolve(strict=True)
    with tarfile.open(path, "r:gz") as tar:
        member = tar.getmember("package/package.json")
        if member.size > 256 * 1024 or not member.isfile():
            raise ValueError("安装包清单无效。")
        with tar.extractfile(member) as handle:
            if json.load(handle).get("name") != expected:
                raise ValueError(f"安装包和 {channel} 的声明不符。")
        members = set(tar.getnames())
        if channel == "qqbot" and not any(name.endswith("/official-qq.mjs") for name in members):
            raise ValueError("官方 QQ 需使用包含 Tencent SDK 适配的 FatFish 归档。")
        if channel in {"snowluma", "napcat"} and not any(name.endswith("/runtime-adapter.mjs") for name in members):
            raise ValueError("OneBot 需使用包含 FatFish 权限适配的归档。")
        if channel == "wechat" and not {
            "package/lib/fatfish-wechat-turn-budget.mjs", "package/lib/persona/model.mjs",
        }.issubset(members):
            raise ValueError("微信需使用包含权限、限额与按需上下文的 FatFish 归档。")
    return channel, path


def initialize(home: Path, plan: dict, *, mcp_python: Path | None = None, memory_db: Path | None = None) -> Path:
    profile = home / "profiles" / "web"
    home.mkdir(parents=True, exist_ok=False)
    profile.mkdir(parents=True)
    write_json(profile / "package.json", {
        "name": "fatfish-portable-profile", "private": True, "dependencies": {},
        "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]}},
    })
    (profile / "pnpm-workspace.yaml").write_text("autoInstallPeers: false\n", encoding="utf-8")
    patch = []
    if QQ_CHANNELS.intersection(plan):
        patch.append({"id": "fatfish-control", "disabled": True, "config": {
            "dataDirectory": (home / "control").as_posix(),
            "reply": {"silent": True}, "runner": {"enabled": False},
            "tasks": [], "proactive": {"enabled": False},
        }})
    for channel, spec in plan.items():
        row = {"id": spec["plugin"], "disabled": True}
        if channel == "qqbot":
            account = home / "official-qq.json"
            account.write_bytes((ROOT / "dsh/templates/official-qq.example.json").read_bytes())
            row["config"] = {"officialAccountFile": account.as_posix(), "agentPreset": "whale-qq"}
        elif channel in {"snowluma", "napcat"}:
            row["config"] = {"host": "127.0.0.1", "mode": "reverse", "agentPreset": "whale-qq"}
        elif channel == "wechat":
            row["config"] = {
                "enabled": False, "autoLogin": False, "stateDir": (home / "wechat").as_posix(),
                "workspace": (home / "workspace").as_posix(), "accessPolicy": "allowlist",
                "allowedUserIds": [], "agentPreset": "whale-social", "media": {"enabled": False},
            }
        patch.append(row)
    (home / "workspace").mkdir()
    card = home / "persona.json"
    card.write_bytes((ROOT / "dsh/persona/whale.json").read_bytes())
    def preset(preset_id: str, label: str, channel: str) -> dict:
        return {"id": preset_id, "name": "@deepseek-ai/dsh-agent-preset",
                "config": {"id": preset_id, "name": label, "plugins": [{
                    "id": "fatfish-persona", "name": (ROOT / "dsh/persona/runtime.mjs").as_uri(),
                    "config": {"cardFile": card.as_posix(), "channel": channel},
                }]}}
    presets = [preset("whale-local", "小鱼 · 本机", "desktop")]
    if mcp_python:
        presets[0]["config"]["plugins"].append({
            "id": "fatfish-memory", "name": "@deepseek-ai/dsh-mcp-client", "config": {
                "serverName": "fatfish", "transport": "stdio", "command": mcp_python.as_posix(),
                "args": [(ROOT / "dsh/service/fatfish_memory_mcp.py").as_posix()],
                "cwd": ROOT.as_posix(), "env": {
                    "FATFISH_MEMORY_DB": (memory_db or home / "memory.sqlite").as_posix(),
                    "FATFISH_SERVICE_READONLY": "1",
                },
            },
        })
    if "wechat" in plan:
        presets.append(preset("whale-social", "小鱼 · 微信", "wechat"))
    if QQ_CHANNELS.intersection(plan):
        presets.append(preset("whale-qq", "小鱼 · QQ", "qq"))
    patch.append({"insert": presets})
    write_json(profile / "cordis.patch.yml", patch)
    write_json(home / "fatfish-channels.json", {"version": 1, "channels": plan})
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", nargs="*", choices=CHANNELS, default=[])
    parser.add_argument("--home", type=Path, help="仅接受全新目录。省略时只预览。")
    parser.add_argument("--archive", action="append", default=[], metavar="CHANNEL=LOCAL_TGZ")
    parser.add_argument("--control-archive", type=Path, help="安装 QQ 时使用已有 FatFish 控制层归档。")
    parser.add_argument("--cli", type=Path, help="提供 DSH CLI 后安装已选归档。渠道保持关闭。")
    parser.add_argument("--store-dir", type=Path)
    parser.add_argument("--mcp-python", type=Path, help="已有 MCP Python，只挂载到本机人设。")
    parser.add_argument("--memory-db", type=Path, help="可选已有记忆库，默认使用新目录内的数据库。")
    args = parser.parse_args()
    try:
        plan = channel_plan(args.channels)
        if args.cli and not args.home:
            raise ValueError("安装需要指定新的 --home。")
        if args.archive and not args.cli:
            raise ValueError("提供归档时也需指定 DSH CLI。")
        if (args.mcp_python and not args.home) or (args.memory_db and not args.mcp_python):
            raise ValueError("配置本机 MCP 需要 --home；使用已有记忆库还需 --mcp-python。")
        archives = dict(archive_for(spec) for spec in args.archive)
        if args.cli and (set(archives) != set(plan) or len(archives) != len(args.archive)):
            raise ValueError("每个选中的渠道需提供恰好一个本机归档。")
        needs_control = bool(QQ_CHANNELS.intersection(plan))
        if bool(args.control_archive) != bool(args.cli and needs_control):
            raise ValueError("安装 QQ 时需要 --control-archive；其他渠道无需提供。")
        dependencies = []
        if args.control_archive:
            dependencies.append(archive_for(f"control={args.control_archive}")[1])
        cli = args.cli.resolve(strict=True) if args.cli else None
        if args.home:
            home = args.home.resolve()
            profile = initialize(home, plan, mcp_python=args.mcp_python.resolve(strict=True) if args.mcp_python else None,
                                 memory_db=args.memory_db.resolve(strict=True) if args.memory_db else None)
            for artifact in [*dependencies, *archives.values()]:
                command = [str(cli), "plugin", "--profile", "web", "add",
                           f"file:{artifact.as_posix()}", "--ignore-scripts"]
                if args.store_dir:
                    command += ["--store-dir", str(args.store_dir.resolve())]
                with (home / "install.log").open("ab") as log:
                    subprocess.run(command, env={**os.environ, "DSH_HOME": str(home), "DSH_PROFILE": "web"},
                                   cwd=profile, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
            print(json.dumps({"profile": str(profile), "selected": plan, "installed": bool(archives),
                              "channels_enabled": False}, ensure_ascii=False))
        else:
            print(json.dumps({"selected": plan, "channels_enabled": False}, ensure_ascii=False))
    except (ValueError, OSError, tarfile.TarError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
