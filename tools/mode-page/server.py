"""群模式面板：点几下就把每个群设成“既听又说/只听不说/只回@/只回老大/完全不理”。

设计成只碰两个文件：
- 读：`data/dsh/../..` 里的 `dsh/policy.json`（groupModes/groupDefaultMode）
- 读：`~/.dsh/media/onebot/*/qq-trace.jsonl`（挖出实际出现过的群号与最后活动时间）
- 写：`dsh/policy.json` 的 `groupModes`（原子写：临时文件 + os.replace）

`dsh/runtime-adapter.mjs` 的 `loadPolicy()` 每轮都会重读 policy.json，所以改完下一句就生效，
不用重启宿主。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "dsh" / "policy.json"
MEDIA = Path.home() / ".dsh" / "media" / "onebot"

MODES = [
    ("talk", "既听又说", "正常聊天，聊到就回"),
    ("listen", "只听不说", "只看不吭声，攒着当记忆"),
    ("mention", "只回@或叫名字", "只有 @ 她或叫名字才开口"),
    ("owner", "只回老大", "群里只回应你，其他人一概不理"),
    ("quiet", "完全不理", "这个群彻底静音"),
]
MODE_KEYS = {mode for mode, _, _ in MODES}
CHAT_KEY = re.compile(r'"chatId":"(group:\d+)"')


def read_policy() -> dict:
    try:
        return json.loads(POLICY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_policy(data: dict) -> None:
    tmp = POLICY.with_name(POLICY.name + ".mode-tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, POLICY)


def scan_groups() -> dict[str, dict]:
    """从 trace 里数出出现过的群：最后活动时间 + 最近一条消息片段。"""
    found: dict[str, dict] = {}
    if not MEDIA.is_dir():
        return found
    for path in MEDIA.glob("*/qq-trace.jsonl"):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = CHAT_KEY.search(line)
                    if not match:
                        continue
                    chat = match.group(1)
                    try:
                        row = json.loads(line)
                    except Exception:
                        row = {}
                    entry = found.setdefault(chat.replace("group:", ""), {"seen": 0, "last": ""})
                    stamp = row.get("ts")
                    if isinstance(stamp, (int, float)) and stamp > 0:
                        text = time.strftime("%m-%d %H:%M", time.localtime(stamp / 1000))
                        if text > entry["last"]:
                            entry["last"] = text
                    entry["seen"] += 1
        except OSError:
            continue
    return found


def state() -> dict:
    policy = read_policy()
    modes = policy.get("groupModes") or {}
    default = policy.get("groupDefaultMode") or "talk"
    groups = []
    for gid, info in scan_groups().items():
        groups.append({
            "id": gid,
            "mode": modes.get(gid, "default"),
            "seen": info["seen"],
            "last": info["last"],
        })
    for gid in modes:
        if not any(row["id"] == gid for row in groups):
            groups.append({"id": gid, "mode": modes[gid], "seen": 0, "last": ""})
    groups.sort(key=lambda row: row["last"], reverse=True)
    return {
        "policy": str(POLICY),
        "default": default,
        "groups": groups,
        "modes": [{"key": key, "label": label, "hint": hint} for key, label, hint in MODES],
        "owner": policy.get("ownerId", ""),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "FatFishModePanel/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 不往控制台刷访问日志
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, (ROOT / "tools" / "mode-page" / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send(200, json.dumps(state(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/mode":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, b'{"ok":false,"error":"bad json"}', "application/json")
            return
        group = str(payload.get("group", "")).strip()
        mode = str(payload.get("mode", "")).strip()
        if not re.fullmatch(r"\d{5,12}", group):
            self._send(400, b'{"ok":false,"error":"group must be a number"}', "application/json")
            return
        if mode not in MODE_KEYS and mode != "default":
            self._send(400, b'{"ok":false,"error":"unknown mode"}', "application/json")
            return
        policy = read_policy()
        modes = dict(policy.get("groupModes") or {})
        if mode == "default":
            modes.pop(group, None)
        else:
            modes[group] = mode
        policy["groupModes"] = modes
        policy.setdefault("groupDefaultMode", "talk")
        write_policy(policy)
        self._send(200, json.dumps({"ok": True, "group": group, "mode": mode}, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"群模式面板: http://{args.host}:{args.port}/  (policy: {POLICY})")
    server.serve_forever()


if __name__ == "__main__":
    main()
