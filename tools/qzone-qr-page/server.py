"""把 QQ 空间扫码登录的实时二维码挂到本地网页上，避免聊天窗口里发的是快照。

桥那边每 25 秒会换一张新码写到 qrcode.png，这个页面每 3 秒自动重新拉一次图片，
所以浏览器里看到的永远是当前有效的码。
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
from pathlib import Path

ROOT = Path(os.environ.get("QZONE_QR_DIR", r"D:\Code\tmp-qzone\test_cache"))
PORT = int(os.environ.get("QZONE_QR_PORT", "8799"))

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>QQ空间扫码登录</title>
<style>
 body{background:#0f1117;color:#e6e6e6;font-family:system-ui,sans-serif;text-align:center;padding:24px}
 img{background:#fff;padding:12px;border-radius:12px;image-rendering:pixelated;width:420px;height:420px}
 p{color:#9aa4b2;font-size:14px}
 code{color:#7ee787}
</style></head><body>
<h2>用手机 QQ 扫这个码</h2>
<img id="qr" src="/qr.png" alt="二维码">
<p>每 3 秒自动换成最新一张 · <span id="ts">-</span></p>
<p>扫完在手机上点「确认登录」，然后回 DSH 说一声。</p>
<script>
async function tick(){
  const r = await fetch('/status', {cache:'no-store'});
  const d = await r.json();
  document.getElementById('qr').src = '/qr.png?t=' + Date.now();
  document.getElementById('ts').textContent = d.mtime + (d.logged_in ? ' · 已登录！' : '');
}
tick(); setInterval(tick, 3000);
</script></body></html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # 安静点，不刷屏
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        qr = ROOT / "qrcode.png"
        if path in ("/", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/qr.png":
            if not qr.exists():
                self._send(b"no qr yet", "text/plain; charset=utf-8")
                return
            self._send(qr.read_bytes(), "image/png")
            return
        if path == "/status":
            import json
            import time

            mtime = None
            if qr.exists():
                mtime = time.strftime("%H:%M:%S", time.localtime(qr.stat().st_mtime))
            cookies = ROOT / "cookies.json"
            payload = {"mtime": mtime, "logged_in": cookies.exists()}
            self._send(json.dumps(payload).encode("utf-8"), "application/json")
            return
        self._send(b"not found", "text/plain; charset=utf-8")


def main() -> int:
    if not ROOT.is_dir():
        print(f"目录不存在: {ROOT}", file=sys.stderr)
        return 1
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"QQ空间扫码页: http://127.0.0.1:{PORT}/   （二维码目录 {ROOT}）", flush=True)
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
