"""生成打好 transport provide 的 dsh-onebot-qq/lib/index.js（写到仓库 outputs，再由 shell 复制）。

沙盒里 python 子进程无权直接写 ~/.dsh/profiles/.../node_modules（ACL 只给
CodexSandboxUsers RX），所以这里只产出文件，落盘交给 ops_bash 的 cp。
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path.home() / ".dsh" / "profiles" / "desktop" / "node_modules" / "dsh-onebot-qq" / "lib" / "index.js"
OUT = Path(r"D:\Code\Projects\FatFishLife\outputs\transport\index.js")

ANCHOR = "    // Lifecycle: start the bridge and transport; unwind everything on unload."
BLOCK = """    // fatfish: 定时/主动层的最小发送面（不建会话、不占模型上下文）。
    ctx.provide('dshOnebotTransport', {
        connected: () => connection.connected === true,
        selfId: () => connection.selfId,
        sendText: (chatId, text) => bridge.sendToChat(chatId, text, { queuable: true }),
        sendSegments: (chatId, segments) => bridge.sendSegments(chatId, segments),
    });
"""

MARK = "ctx.provide('dshOnebotTransport'"


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    if MARK in source:
        print("already patched; nothing to do")
        return 2
    count = source.count(ANCHOR)
    if count != 1:
        print(f"anchor count = {count}, expected 1", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(source.replace(ANCHOR, BLOCK + ANCHOR), encoding="utf-8", newline="\n")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
