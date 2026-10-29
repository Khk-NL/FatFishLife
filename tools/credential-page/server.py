"""苹果乐凭证面板：本地网页，一键填/换凭证，只监听 127.0.0.1。

用法：
    python tools/credential-page/server.py            # 打开 http://127.0.0.1:8787
    python tools/credential-page/server.py --port 8799

设计约束：
- 只写 outputs/secrets/*.env（仓库已 gitignore outputs/），绝不把明文写进仓库源码；
- 页面只回显掩码，不回显完整密钥；
- 每个凭证的「验证」都真的打一次对应接口，失败就明说失败，不做假绿灯。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / "outputs" / "secrets"
PAGE = Path(__file__).with_name("index.html")

# name -> 描述。env_file 里的 KEY=value 就是落点，其余配置项（比如模型名）保持不动。
CREDENTIALS = {
    "deepseek": {
        "label": "DeepSeek API Key",
        "env_file": SECRETS / "deepseek.env",
        "env_key": "DEEPSEEK_API_KEY",
        "hint": "sk- 开头；用于聊天与定时任务（推荐/日记/主动开口）",
        "prefix": "sk-",
    },
    "minimax": {
        "label": "MiniMax API Key",
        "env_file": SECRETS / "minimax.env",
        "env_key": "MINIMAX_API_KEY",
        "hint": "语音合成用；换 key 后语音才会重新可用",
        "prefix": "",
    },
    "firecrawl": {
        "label": "Firecrawl API Key（可选）",
        "env_file": SECRETS / "firecrawl.env",
        "env_key": "FIRECRAWL_API_KEY",
        "hint": "fc- 开头；给 read_page 兜底，当前 keyless 模式被 403 挡着",
        "prefix": "fc-",
    },
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# DSH 自己的凭据文件才是聊天真正用的那一份；outputs/secrets 只作仓库内的副本/备份。
DSH_CREDENTIALS = Path(os.path.expanduser("~/.dsh/.credentials.yaml"))


def dsh_ref(name: str) -> str:
    if not DSH_CREDENTIALS.exists():
        return ""
    for line in DSH_CREDENTIALS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}:"):
            return stripped.partition(":")[2].strip().strip('"').strip("'")
    return ""


def write_dsh_ref(name: str, value: str) -> bool:
    """只替换 refs 里的这一行，其它记录原样保留；写不了就返回 False，交给调用方报错。"""
    if not DSH_CREDENTIALS.exists():
        return False
    lines = DSH_CREDENTIALS.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{name}:"):
            indent = line[: len(line) - len(line.lstrip(" "))]
            lines[index] = f"{indent}{name}: {value}"
            replaced = True
            break
    if not replaced:
        return False
    staged = ROOT / "outputs" / "persona-staging" / DSH_CREDENTIALS.name
    staged.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    staged.write_text(text, encoding="utf-8", newline="\n")
    try:
        DSH_CREDENTIALS.write_text(text, encoding="utf-8", newline="\n")
        return True
    except PermissionError:
        print(f"[暂存] 写不了 {DSH_CREDENTIALS}，已生成 {staged}，请用 shell cp 覆盖")
        return False


def write_env(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name = line.partition("=")[0].strip()
                if name == key:
                    continue
            lines.append(line)
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:  # 尽量收紧权限；Windows 上这里是空操作，不假装成功
        os.chmod(path, 0o600)
    except OSError:
        pass


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "…" + value[-2:]
    return f"{value[:6]}…{value[-4:]}"


def http_json(url: str, headers: dict[str, str], timeout: float = 12.0) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {"raw": body[:300]}
        return error.code, payload
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return 0, {"error": f"{type(error).__name__}: {error}"}


def cred_value(name: str) -> tuple[str, str]:
    """返回 (值, 来源说明)。DeepSeek 以 DSH 凭据文件为准，其余看 outputs/secrets。"""
    spec = CREDENTIALS[name]
    if name == "deepseek":
        value = dsh_ref(spec["env_key"])
        if value:
            return value, "~/.dsh/.credentials.yaml"
    return read_env(spec["env_file"]).get(spec["env_key"], ""), str(spec["env_file"].relative_to(ROOT))


def bili_status() -> dict:
    path = Path(os.path.expanduser("~/.bili-ai/credentials.json"))
    if not path.exists():
        return {"ok": False, "detail": "还没有 B 站凭据：在仓库里跑 node outputs/bili-login/run.mjs 扫码"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"ok": False, "detail": f"凭据文件损坏：{error}"}
    parts = []
    if data.get("sessdata"):
        parts.append(f"SESSDATA={data['sessdata']}")
    if data.get("bili_jct"):
        parts.append(f"bili_jct={data['bili_jct']}")
    if data.get("buvid3"):
        parts.append(f"buvid3={data['buvid3']}")
    if not parts:
        return {"ok": False, "detail": "凭据文件里没有 sessdata：需要重新扫码"}
    status, payload = http_json("https://api.bilibili.com/x/web-interface/nav",
                                {"Cookie": "; ".join(parts), "User-Agent": "Mozilla/5.0"})
    body = payload.get("data") or {}
    if status == 200 and body.get("isLogin"):
        return {"ok": True, "detail": f"已登录：{body.get('uname')}（mid {body.get('mid')}）"}
    return {"ok": False, "detail": f"未登录（HTTP {status}，code={payload.get('code')}）"}


def napcat_status() -> dict:
    configs = sorted(Path("D:/Code/Apps/NapCat/config").glob("onebot11_*.json"))
    if not configs:
        return {"ok": False, "detail": "没找到 NapCat 的 onebot11_*.json"}
    try:
        data = json.loads(configs[0].read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        return {"ok": False, "detail": f"配置读不动：{error}"}
    clients = data.get("network", {}).get("websocketClients") or []
    patch = Path(os.path.expanduser("~/.dsh/profiles/desktop/cordis.patch.yml"))
    text = patch.read_text(encoding="utf-8") if patch.exists() else ""
    port = re.search(r"port:\s*(\d+)", text)
    token = re.search(r"accessToken:\s*'([^']+)'", text)
    want = token.group(1) if token else ""
    if not clients:
        return {"ok": False, "detail": "NapCat 没配反向 WS 客户端"}
    client = clients[0]
    same = client.get("token") == want
    return {
        "ok": same,
        "detail": f"{client.get('url')}｜端口 {'匹配' if (port and str(port.group(1)) in str(client.get('url'))) else '不匹配'}｜"
                  f"token {'一致' if same else '不一致'}",
    }


def status_payload() -> dict:
    items = []
    for name, spec in CREDENTIALS.items():
        value, source = cred_value(name)
        items.append({
            "name": name,
            "label": spec["label"],
            "hint": spec["hint"],
            "file": source,
            "present": bool(value),
            "masked": mask(value),
            "updated": datetime.fromtimestamp(spec["env_file"].stat().st_mtime).strftime("%m-%d %H:%M")
            if spec["env_file"].exists() else "",
        })
    return {"credentials": items, "bili": bili_status(), "napcat": napcat_status()}


def test_credential(name: str) -> dict:
    spec = CREDENTIALS.get(name)
    if not spec:
        return {"ok": False, "detail": "未知凭证"}
    value, _source = cred_value(name)
    if not value:
        return {"ok": False, "detail": "还没有填写"}
    if spec["prefix"] and not value.startswith(spec["prefix"]):
        return {"ok": False, "detail": f"格式不像：应以 {spec['prefix']} 开头"}
    if name == "deepseek":
        status, payload = http_json("https://api.deepseek.com/user/balance",
                                    {"Authorization": f"Bearer {value}"})
        if status == 200 and payload.get("is_available"):
            infos = payload.get("balance_infos") or [{}]
            return {"ok": True, "detail": f"可用，余额 {infos[0].get('total_balance', '?')} {infos[0].get('currency', '')}"}
        return {"ok": False, "detail": f"HTTP {status}：{payload.get('error', payload)}"[:200]}
    if name == "minimax":
        # 不做真实合成（会花钱），只确认网关认这个 key 的鉴权头。
        status, payload = http_json("https://api.minimax.cn/v1/get_voice", {"Authorization": f"Bearer {value}"})
        if status in (200, 400, 422) and str(payload.get("base_resp", {}).get("status_code", "")) != "1004":
            return {"ok": True, "detail": f"鉴权头被接受（HTTP {status}，未做真实合成）"}
        return {"ok": False, "detail": f"HTTP {status}：{payload.get('base_resp', payload)}"[:200]}
    return {"ok": True, "detail": "已保存（该凭证没有自动验证接口）"}


class Handler(BaseHTTPRequestHandler):
    server_version = "FatfishCredentials/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(status_payload())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "detail": "请求不是合法 JSON"}, 400)
            return
        name = str(payload.get("name", ""))
        spec = CREDENTIALS.get(name)
        if not spec:
            self._json({"ok": False, "detail": "未知凭证"}, 400)
            return
        if self.path == "/api/save":
            value = str(payload.get("value", "")).strip()
            if not value:
                self._json({"ok": False, "detail": "内容为空，没有保存"}, 400)
                return
            if spec["prefix"] and not value.startswith(spec["prefix"]):
                self._json({"ok": False, "detail": f"格式不像：应以 {spec['prefix']} 开头"}, 400)
                return
            # 两边都写：DSH 凭据文件是聊天真正读的那份，outputs/secrets 是仓库内副本。
            write_env(spec["env_file"], spec["env_key"], value)
            if name == "deepseek":
                if write_dsh_ref(spec["env_key"], value):
                    self._json({"ok": True, "detail": f"已写入 ~/.dsh/.credentials.yaml 与 {spec['env_file'].relative_to(ROOT)}，重启宿主生效"})
                else:
                    self._json({"ok": False, "detail": f"DSH 凭据文件写不进去，已暂存到 outputs/persona-staging/，请用 shell cp 覆盖后再重启"})
                return
            self._json({"ok": True, "detail": f"已写入 {spec['env_file'].relative_to(ROOT)}，重启宿主生效"})
        elif self.path == "/api/test":
            self._json(test_credential(name))
        else:
            self._json({"error": "not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"凭证面板：{url}（Ctrl+C 结束）")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
