"""迁移完成度自检：一条命令看到哪些通了、哪些还差。

检查项分三档：
    PASS  有运行时证据，可以直接用
    WARN  能跑但有已知限制
    FAIL  缺失或阻塞

用法：
    python scripts/dsh_selfcheck.py
    python scripts/dsh_selfcheck.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV_FILE = ROOT / ".env"
MEMORY_DB = ROOT / "data" / "memory.db"
MEME_ROOT = ROOT / "data" / "memes"
KB_DB = Path("C:/Users/kongb/.dsh/knowledge-base/kb.sqlite")
PROFILE = Path("C:/Users/kongb/.dsh/profiles/desktop")

results: list[dict] = []


def load_env() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def check(name: str, status: str, detail: str) -> None:
    results.append({"name": name, "status": status, "detail": detail})


def check_memory() -> None:
    if not MEMORY_DB.is_file():
        check("memory.db", "FAIL", f"缺失：{MEMORY_DB}")
        return
    try:
        conn = sqlite3.connect(MEMORY_DB)
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        cands = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='candidate'").fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='verified'").fetchone()[0]
        blocks = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        check("memory.db", "FAIL", f"读取失败：{exc}")
        return
    status = "PASS" if blocks >= 1 else "WARN"
    check("memory.db", status, f"events {events} / 候选 {cands} / 已确认 {verified} / blocks {blocks}")


def check_gallery() -> None:
    try:
        from fatfish_core import gallery

        st = gallery.stats()
    except Exception as exc:  # noqa: BLE001
        check("图库", "FAIL", str(exc))
        return
    status = "PASS" if st["total"] > 0 and st["broken"] == 0 else "WARN"
    check("图库", status, f"{st['total']} 张，分类 {st['categories']}，损坏 {st['broken']}")


def check_kb() -> None:
    if not KB_DB.is_file():
        check("DSH 知识库", "FAIL", "插件未建库")
        return
    try:
        conn = sqlite3.connect(KB_DB)
        total = conn.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        check("DSH 知识库", "FAIL", str(exc))
        return
    check("DSH 知识库", "PASS" if total else "WARN", f"{total} 条记录")


def check_plugins() -> None:
    pkg = PROFILE / "package.json"
    if not pkg.is_file():
        check("DSH 插件", "FAIL", "profile 不存在")
        return
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        bundles = (data.get("dsh") or {}).get("profile", {}).get("bundles", [])
    except ValueError as exc:
        check("DSH 插件", "FAIL", str(exc))
        return
    community = [b for b in bundles if not b.startswith("@deepseek-ai/")]
    check("DSH 插件", "PASS" if community else "WARN", f"社区插件 {community}")


def check_preset() -> None:
    patch = PROFILE / "cordis.patch.yml"
    if not patch.is_file():
        check("人格 preset", "FAIL", "profile patch 缺失")
        return
    text = patch.read_text(encoding="utf-8-sig", errors="replace")
    has_preset = "preset-apple-le" in text
    has_mcp = "mcp-fatfish-memory" in text
    detail = f"preset={'有' if has_preset else '缺'}，MCP={'有' if has_mcp else '缺'}"
    check("人格 preset", "PASS" if has_preset and has_mcp else "WARN", detail)


def check_mcp_tools() -> None:
    """用官方 MCP 客户端列一次工具，等价于 DSH 的接入方式。"""
    script = ROOT / "dsh" / "service" / "fatfish_memory_mcp.py"
    python = ROOT / ".tools" / "dsh-python" / "Scripts" / "python.exe"
    if not script.is_file() or not python.is_file():
        check("MCP 工具", "FAIL", "服务脚本或独立 Python 缺失")
        return
    code = (
        "import asyncio,sys\n"
        "from mcp import ClientSession, StdioServerParameters\n"
        "from mcp.client.stdio import stdio_client\n"
        "async def m():\n"
        "    p=StdioServerParameters(command=sys.executable,args=['dsh/service/fatfish_memory_mcp.py'])\n"
        "    async with stdio_client(p) as (r,w):\n"
        "        async with ClientSession(r,w) as s:\n"
        "            await s.initialize()\n"
        "            print(len((await s.list_tools()).tools))\n"
        "asyncio.run(m())\n"
    )
    try:
        out = subprocess.run(
            [str(python), "-c", code],
            cwd=str(ROOT), capture_output=True, text=True, timeout=90,
        )
        count = int((out.stdout or "0").strip().splitlines()[-1])
    except (subprocess.SubprocessError, ValueError, IndexError):
        check("MCP 工具", "FAIL", "客户端握手失败")
        return
    check("MCP 工具", "PASS" if count >= 20 else "WARN", f"{count} 个工具")


def check_local_llm() -> None:
    try:
        from fatfish_core import local_llm

        backends = local_llm.probe()
    except Exception as exc:  # noqa: BLE001
        check("本地模型", "FAIL", str(exc))
        return
    ok = [k for k, v in backends.items() if v.get("ok")]
    check("本地模型", "PASS" if ok else "FAIL", f"可用后端 {ok}")


def check_tts() -> None:
    try:
        from fatfish_core.tts import TTSConfig, probe
    except Exception as exc:  # noqa: BLE001
        check("TTS", "FAIL", str(exc))
        return
    try:
        info = probe(TTSConfig.from_env())
    except Exception as exc:  # noqa: BLE001
        check("TTS", "FAIL", str(exc)[:80])
        return
    check("TTS", "PASS" if info.get("riff") else "WARN", f"{info.get('bytes')} 字节，RIFF={info.get('riff')}")


def check_bili() -> None:
    try:
        from fatfish_core import bili

        data = bili.probe()
    except Exception as exc:  # noqa: BLE001
        check("B 站", "FAIL", str(exc)[:80])
        return
    status = "PASS" if data.get("ok") else "WARN"
    check("B 站", status, f"exe={Path(str(data.get('exe'))).name}，写操作={'开' if data.get('writes') else '关'}")


def check_qq_bridge() -> None:
    """QQ 桥是当前已知阻塞项，独立报状态。"""
    has_pkg = (PROFILE / "node_modules" / "dsh-onebot-qq").is_dir()
    listening = False
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            listening = sock.connect_ex(("127.0.0.1", 8643)) == 0
    except OSError:
        pass
    if listening:
        check("QQ 桥", "PASS", "8643 在监听")
    elif has_pkg:
        check("QQ 桥", "WARN", "包在但未监听（peer 依赖阻塞）")
    else:
        check("QQ 桥", "FAIL", "未安装；QQ 仍由 AstrBot 承担")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    load_env()
    for fn in (
        check_memory, check_gallery, check_kb, check_plugins, check_preset,
        check_mcp_tools, check_local_llm, check_tts, check_bili, check_qq_bridge,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(fn.__name__, "FAIL", f"检查本身出错：{type(exc).__name__}")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    icon = {"PASS": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    for row in results:
        print(f"{icon.get(row['status'], '[?]')} {row['name']:<12} {row['detail']}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
