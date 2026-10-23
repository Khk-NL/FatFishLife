"""手动完成 Pixiv OAuth，换取 refresh_token。

不启动浏览器、不自动登录，避免被判定为自动化程序。

用法：
  python scripts/pixiv_token.py
按提示在已登录的浏览器里打开链接，登录后从跳转地址里复制 code 粘贴回来。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
LOGIN_CLIENT = "pixiv-android"
REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"


def build_login_url() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    query = urllib.parse.urlencode(
        {
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "client": LOGIN_CLIENT,
            "redirect_uri": REDIRECT_URI,
        }
    )
    Path(__file__).with_name(".pixiv_verifier").write_text(verifier, encoding="ascii")
    return f"https://app-api.pixiv.net/web/v1/login?{query}", verifier


def exchange(code: str, verifier: str) -> dict:
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "include_policy": "true",
        "redirect_uri": REDIRECT_URI,
    }
    body = urllib.parse.urlencode(payload).encode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
            "App-OS": "android",
            "App-OS-Version": "11",
            "App-Version": "5.0.234",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Pixiv 返回 {exc.code}：{body}") from exc


def main() -> None:
    url, verifier = build_login_url()
    print("1. 复制下面整个地址，在已经登录 Pixiv 的浏览器里打开：\n")
    print(url)
    print("\n2. 点登录，页面会跳到 pixiv.net 或显示一个空白页。")
    print("   从地址栏里找 code= 后面那一串，复制下来。\n")
    code = urllib.parse.unquote(input("3. 粘贴 code 后回车：").strip())
    if not code:
        print("没有拿到 code，退出。")
        return
    data = exchange(code, verifier)
    token = (data.get("response") or {}).get("refresh_token") or data.get("refresh_token")
    if not token:
        print("换取失败，返回内容：", data)
        return
    print("\nrefresh_token：\n")
    print(token)
    print("\n把它填到 .env 的 FATFISH_PIXIV_REFRESH_TOKEN，或者 AstrBot 的 Pixiv 插件配置里。")


if __name__ == "__main__":
    main()
