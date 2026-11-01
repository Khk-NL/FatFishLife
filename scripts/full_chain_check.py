"""全功能联动检测：把她的每条能力都实际打一遍，输出 PASS/FAIL 表。

用法（仓库根目录）：
    ./.tools/dsh-python/Scripts/python.exe scripts/full_chain_check.py          # 只读，不花钱
    ./.tools/dsh-python/Scripts/python.exe scripts/full_chain_check.py --live   # 连真网/真模型

设计原则：
- 不打印密钥、Cookie 内容，只报结果；
- 每条检查独立 try/except，一条失败不影响其它；
- --live 才碰网络与模型（会有费用）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("USERPROFILE") or Path.home())
DATA = ROOT / "data" / "dsh"
MEMORY_DB = Path(os.environ.get("FATFISH_MEMORY_DB") or Path("D:/Code/Apps/AstrBot/data/plugin_data/astrbot_plugin_fatfish_memory/memory.db"))
QZONE_BASE = os.environ.get("QZONE_API_BASE", "http://127.0.0.1:5700")
QZONE_TOKEN = os.environ.get("QZONE_API_TOKEN", "fatfishqzone20261031")
BILI = Path("D:/Code/Apps/bili-venv/Scripts/bili.exe")

results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    start = time.time()
    try:
        detail = fn() or "ok"
        results.append((name, True, f"{detail} ({time.time() - start:.1f}s)"))
    except Exception as error:  # noqa: BLE001 - 检测脚本要吞掉所有异常继续跑
        results.append((name, False, f"{type(error).__name__}: {error}"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.5)
        return sock.connect_ex((host, port)) == 0


def http_json(url: str, payload: dict | None = None, timeout: float = 10.0):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"content-type": "application/json", "authorization": f"Bearer {QZONE_TOKEN}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---- 各项能力 -------------------------------------------------------------


def check_scheduler():
    beat = read_json(DATA / "scheduler-heartbeat.json")
    stamp = datetime.datetime.strptime(beat["at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    age = (datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds() * 1000
    if not beat.get("tasks"):
        raise AssertionError("心跳里没有任务")
    return f"任务 {beat['tasks']} 条，心跳 {age / 60000:.1f} 分钟前"


def check_control_mount():
    mount = read_json(DATA / "control-mount.json")
    if mount.get("stage") != "done":
        raise AssertionError(f"控制层未挂载：{mount}")
    return f"stage=done，tasks={mount.get('tasks')}"


def check_policy_modes():
    policy = read_json(ROOT / "dsh" / "policy.json")
    modes = policy.get("groupModes") or {}
    return f"默认 {policy.get('groupDefaultMode')}，单独设置 {len(modes)} 个群"


def check_memory():
    sys.path.insert(0, str(ROOT))
    from fatfish_core import memory as memory_api  # noqa: PLC0415

    store = memory_api.MemoryStore(MEMORY_DB)
    hits = store.search("B站", limit=3)
    return f"检索命中 {len(hits)} 条"


def check_mood():
    sys.path.insert(0, str(ROOT))
    from fatfish_core import hub  # noqa: PLC0415

    mood = hub.mood_get()
    return f"{mood['value']} ({mood.get('source')})"


def check_growth():
    sys.path.insert(0, str(ROOT))
    from fatfish_core import growth, memory as memory_api  # noqa: PLC0415

    store = memory_api.MemoryStore(MEMORY_DB)
    rows = store.recent(scopes=("public", "private"), limit=200, kinds=("capability",))
    summary = growth.capability_summary(rows)
    return f"能力经历 {len(rows)} 条、聚合 {len(summary)} 项"


def check_kb():
    db = HOME / ".dsh" / "knowledge-base" / "kb.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        count = con.execute("select count(*) from kb").fetchone()[0]
    finally:
        con.close()
    return f"知识库 {count} 条"


def check_obsidian():
    journal = Path("D:/obsidian/vaults/SCSldr/Journal")
    files = sorted(journal.glob("*.md"))
    if not files:
        raise AssertionError("日记目录是空的")
    latest = files[-1]
    return f"最近日记 {latest.name}（{latest.stat().st_size} 字节）"


def check_qq_bridge():
    if not port_open(8645):
        raise AssertionError("8645 没有监听")
    trace = next((HOME / ".dsh" / "media" / "onebot").glob("*/qq-trace.jsonl"), None)
    if trace is None:
        raise AssertionError("找不到 qq-trace.jsonl")
    last = trace.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-1]
    row = json.loads(last)
    return f"8645 通，最后一条 trace：{row.get('stage')}/{row.get('ok')}"


def check_qzone():
    if not port_open(5700):
        raise AssertionError("QQ空间桥 5700 没起")
    info = http_json(f"{QZONE_BASE}/get_login_info")
    return f"QQ空间已登录：{info['data']['nickname']}"


def check_wallet():
    wallet = read_json(DATA / "wallet.json")
    return f"余额档位 {wallet.get('level')}（{wallet.get('cny')} 元，{wallet.get('at')}）"


def check_autonomy():
    path = DATA / "autonomy.json"
    if not path.exists():
        return "今天还没用过自主额度"
    state = read_json(path)
    return f"{state.get('day')} 计数 {state.get('counts')}"


def check_stickers():
    os.environ.setdefault("FATFISH_MEME_ROOT", str(ROOT / "data" / "memes"))
    sys.path.insert(0, str(ROOT))
    from fatfish_core import gallery  # noqa: PLC0415

    hits = gallery.find("鲸鱼娘", limit=3)
    return f"表情命中 {len(hits)} 张"


def check_sticker_pack():
    root = HOME / ".dsh" / "nekowhale-stickers"
    packs = list((root / "packs").glob("*")) if (root / "packs").exists() else []
    if not packs:
        raise AssertionError("nekowhale 表情包还没下载")
    return f"{len(packs)} 个包"


def check_tts_config():
    sys.path.insert(0, str(ROOT))
    from fatfish_core import tts  # noqa: PLC0415

    status = tts.status() if hasattr(tts, "status") else {}
    provider = status.get("provider") if isinstance(status, dict) else None
    return f"provider={provider or 'minimax'}，配置就绪={bool(status) if status else 'unknown'}"


def check_live_bili():
    if not BILI.exists():
        raise AssertionError("bili CLI 不存在")
    out = subprocess.run([str(BILI), "feed", "recommend", "-n", "5"], capture_output=True, text=True, encoding="utf-8", timeout=60)
    payload = json.loads(out.stdout)
    if not payload.get("ok"):
        raise AssertionError(f"bili 返回 ok=false：{payload}")
    items = payload["data"]["items"]
    return f"推荐源返回 {len(items)} 条"


def check_live_llm():
    # llm.mjs 是 ESM，用 node 直接跑一次真实对话。
    script = (
        "const { chat } = await import('file:///' + process.argv[1].replace(/\\\\/g, '/') + '/dsh/control/llm.mjs');"
        "const text = await chat([{ role: 'user', content: '用一句话说你现在心情怎么样' }]);"
        "console.log(JSON.stringify({ ok: true, text }));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(ROOT)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    lines = [line for line in out.stdout.strip().splitlines() if line.startswith("{")]
    if not lines:
        raise AssertionError(f"node 没有输出：{out.stderr[-160:]}")
    payload = json.loads(lines[-1])
    return f"DeepSeek 回复 {len(payload['text'])} 字：{payload['text'][:24]}…"


def check_live_image():
    sys.path.insert(0, str(ROOT))
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("mcp", ROOT / "dsh" / "service" / "fatfish_memory_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = json.loads(module.image_generate("chubby whale girl sticker, white background"))
    if not payload.get("ok"):
        raise AssertionError(payload)
    return f"{payload['bytes']} 字节 → {Path(payload['path']).name}"


def check_live_consolidate():
    script = ROOT / "scripts" / "consolidate_peak.py"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", FATFISH_HUB_WRITE="1")
    out = subprocess.run([sys.executable, str(script), "--dry-run"], capture_output=True, text=True, encoding="utf-8", timeout=180, env=env)
    lines = [line for line in out.stdout.strip().splitlines() if line.strip().startswith("{")]
    if not lines:
        return f"队列为空（脚本无输出，exit={out.returncode}）"
    payload = json.loads(lines[-1])
    return f"dry-run items={payload.get('items')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="连真网/真模型")
    args = parser.parse_args()

    check("定时器心跳", check_scheduler)
    check("控制层挂载", check_control_mount)
    check("群模式配置", check_policy_modes)
    check("记忆检索", check_memory)
    check("心情（feiyu 真源）", check_mood)
    check("成长记录", check_growth)
    check("知识库", check_kb)
    check("日记文件", check_obsidian)
    check("QQ 桥", check_qq_bridge)
    check("QQ空间桥", check_qzone)
    check("钱包快照", check_wallet)
    check("自主额度", check_autonomy)
    check("表情库（本地）", check_stickers)
    check("表情包（nekowhale）", check_sticker_pack)
    check("语音配置", check_tts_config)
    if args.live:
        check("B站推荐源", check_live_bili)
        check("DeepSeek 对话", check_live_llm)
        check("生图", check_live_image)
        check("峰时汇总 dry-run", check_live_consolidate)

    width = max(len(name) for name, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    print(f"\n{len(results) - failed}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
