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
    # utf-8-sig: a BOM is invisible in an editor but makes json.loads throw, and
    # PowerShell 5.1 writes one by default. Tolerate it instead of silently
    # reporting "not installed".
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
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
        "accessToken": _value_after(joined, "accessToken"),
        "botQQ": _value_after(joined, "botQQ"),
    }


def can_connect(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def napcat_config() -> tuple[Path, dict] | None:
    """Find NapCat's OneBot client entry. Returns (path, client) or None.

    The reverse-WS client lives in NapCat's own config, outside this repo, so a
    missing file is a WARN rather than a failure: not every machine has NapCat.
    """
    explicit = os.environ.get("FATFISH_NAPCAT_CONFIG")
    if explicit:
        candidates = [Path(explicit)]
    else:
        roots = [Path("D:/Code/Apps/NapCat/config"), Path.home() / "AppData/Roaming/QQ/config"]
        candidates = [p for root in roots if root.is_dir() for p in sorted(root.glob("onebot11_*.json"))]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        clients = ((data.get("network") or {}).get("websocketClients")) or []
        for client in clients:
            if isinstance(client, dict) and client.get("url"):
                return path, client
    return None


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

    # NapCat 与桥必须指向同一端口、携带同一 token。不一致时两边都不会报错，
    # 只是连接被拒 —— 这正是 2026-10-29 实际卡过一次的地方，所以单独判。
    napcat = napcat_config()
    if napcat is None:
        add("NapCat 配置", False, "找不到 NapCat 的 onebot11 配置（可用 FATFISH_NAPCAT_CONFIG 指定）", warn=True)
    else:
        path, client = napcat
        url = str(client.get("url") or "").strip()
        target_port = url.rsplit(":", 1)[-1].split("/")[0] if ":" in url else ""
        add("NapCat 指向桥端口", target_port == str(port), f"{url or '(未写)'}（期望端口 {port}）")
        napcat_token = str(client.get("token") or "").strip()
        bridge_token = str(entry.get("accessToken") or "").strip()
        same = bool(bridge_token) and napcat_token == bridge_token
        add("NapCat token 一致", same,
            "一致" if same else f"桥={'(空)' if not bridge_token else '已设置'} / NapCat={'(空)' if not napcat_token else '已设置'}（不一致会被拒连且不报错）")

    # The bridge writes qq-trace.jsonl under its media dir when traceEnabled is
    # on. That file is the only durable evidence a restart actually produced a
    # live bridge and handled a message, since the desktop host's stdout is not
    # captured anywhere.
    traces = sorted(dsh_home().glob("media/**/qq-trace.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if (dsh_home() / "media").is_dir() else []
    if traces:
        newest = traces[0]
        last = ""
        for line in read_text(newest).splitlines()[-1:]:
            last = line.strip()[:120]
        add("桥追踪文件", True, f"{newest} | 最后一条: {last or '(空)'}")
    else:
        add("桥追踪文件", False, "尚无 qq-trace.jsonl：桥还没在宿主里连接过", warn=True)

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
