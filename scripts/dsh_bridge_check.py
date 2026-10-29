"""Verify the DSH QQ bridge is actually installed, configured and listening.

Installing the package is not the same as a working bridge: the bundle can be
present while its patch never applied, and `botQQ` can silently stay empty.
This script reports those separately so a switch cannot be declared done on
"the package is there" alone.

Usage:
    python -X utf8 scripts/dsh_bridge_check.py [--profile desktop] [--port 8643] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

BRIDGE_PACKAGE = "dsh-onebot-qq"


def dsh_home() -> Path:
    explicit = os.environ.get("DSH_HOME")
    return Path(explicit) if explicit else Path.home() / ".dsh"


def profile_dir(profile: str) -> Path:
    return dsh_home() / "profiles" / profile


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _value_after(text: str, key: str) -> str:
    """Return the raw value for `key:` on the dsh-onebot entry, if present."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            return stripped.split(":", 1)[1].strip().strip("'\"")
    return ""


def onebot_entry(text: str) -> dict:
    """Extract mode/host/port/botQQ from the top-level dsh-onebot patch entry."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        # A top-level list entry starts at column 0. An id nested inside an
        # `insert:` block is indented and must not be mistaken for the override.
        if line.startswith("- id: dsh-onebot") or line == "id: dsh-onebot":
            start = index
            break
    if start is None:
        return {}
    block = []
    for line in lines[start + 1:]:
        if line.startswith("- ") or (line and not line.startswith((" ", "\t"))):
            break
        block.append(line)
    joined = "\n".join(block)
    return {
        "mode": _value_after(joined, "mode"),
        "host": _value_after(joined, "host"),
        "port": _value_after(joined, "port"),
        "botQQ": _value_after(joined, "botQQ"),
    }


def can_connect(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(profile: str = "desktop", port: int = 8643, host: str = "127.0.0.1") -> int:
    root = profile_dir(profile)
    items: list[dict] = []

    def add(name: str, ok: bool, detail: str, warn: bool = False) -> None:
        items.append({"name": name, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "detail": detail})

    add("profile 目录", root.is_dir(), str(root))

    manifest = read_json(root / "package.json")
    deps = manifest.get("dependencies") or {}
    bundles = (((manifest.get("dsh") or {}).get("profile") or {}).get("bundles")) or []
    installed = BRIDGE_PACKAGE in deps
    add("桥已安装", installed, f"{BRIDGE_PACKAGE} {'在' if installed else '不在'} dependencies")
    in_bundles = BRIDGE_PACKAGE in bundles
    add("桥进入 bundles", in_bundles, "bundles 含桥" if in_bundles else "bundles 未含桥，patch 不会生效")

    patch = read_text(root / "cordis.patch.yml")
    entry = onebot_entry(patch)
    add("patch 有 dsh-onebot 段", bool(entry), "找到顶层 dsh-onebot 条目" if entry else "没找到顶层 dsh-onebot 条目")

    bot_qq = str(entry.get("botQQ") or "").strip()
    add("botQQ 已填写", bool(bot_qq), f"botQQ={bot_qq or '(空)'}", warn=not bot_qq)

    configured_port = str(entry.get("port") or "").strip()
    port_ok = configured_port == str(port)
    add("端口一致", port_ok, f"配置 port={configured_port or '(未写)'}，期望 {port}")

    listening = can_connect(host, port)
    add(
        "端口在监听",
        listening,
        f"{host}:{port} {'可连接' if listening else '连不上（DSH 未运行或桥未挂载）'}",
    )

    failed = [item for item in items if item["status"] == "FAIL"]
    print(json.dumps({"ok": not failed, "items": items}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the DSH QQ bridge installation")
    parser.add_argument("--profile", default="desktop")
    parser.add_argument("--port", type=int, default=8643)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    return run(profile=args.profile, port=args.port, host=args.host)


if __name__ == "__main__":
    sys.exit(main())
