"""QQ-space publishing through the configured OneBot connection."""

from __future__ import annotations

import asyncio
import re

ACTION_TIMEOUT_SECONDS = 60


async def publish_qzone(context, text: str, platform_id: str, expected_qq_id: str) -> dict:
    """Send one plain-text post after verifying the connected account."""
    expected = str(expected_qq_id or "").strip()
    platform_id = str(platform_id or "").strip()
    if not platform_id or not expected:
        return {"ok": False, "status": "blocked", "error": {"code": "missing_account", "message": "请先配置 QQ 平台和机器人账号"}}
    if expected != "1670515707":
        return {"ok": False, "status": "blocked", "error": {"code": "account_not_authorized", "message": "说说仅允许机器人账号 1670515707 发布"}}
    content = text.strip().replace("@", "＠") if isinstance(text, str) else ""
    if not content:
        return {"ok": False, "status": "failed", "error": {"code": "invalid_argument", "message": "说说正文为空"}}
    try:
        platform = context.get_platform_inst(platform_id)
        if platform is None or platform.meta().name != "aiocqhttp":
            return {"ok": False, "status": "blocked", "error": {"code": "invalid_platform", "message": "配置的平台不是已连接的 QQ OneBot 平台"}}
        bot = platform.get_client()
        info = await asyncio.wait_for(
            bot.call_action("get_login_info", self_id=expected),
            timeout=ACTION_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return {"ok": False, "status": "blocked", "error": {"code": "identity_unavailable", "message": "无法核验机器人登录账号，未发送说说"}}
    if not isinstance(info, dict) or str(info.get("user_id") or "") != expected:
        return {"ok": False, "status": "blocked", "error": {"code": "account_mismatch", "message": "当前 QQ 登录账号与指定机器人不一致，未发送说说"}}
    try:
        result = await asyncio.wait_for(
            bot.call_action("send_qzone_msg", self_id=expected, content=content,
                            images=[], ugc_right=1, target_uins=[]),
            timeout=ACTION_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return {"ok": False, "status": "uncertain", "error": {"code": "publish_unconfirmed", "message": "说说发布调用未正常返回，请先核验是否已发出"}}
    receipt = result.get("tid") if isinstance(result, dict) else None
    tid = receipt.strip() if isinstance(receipt, str) else ""
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,128}", tid):
        return {"ok": False, "status": "uncertain", "error": {"code": "missing_receipt", "message": "说说没有返回有效 tid，请先核验是否已发出"}}
    return {"ok": True, "status": "sent", "id": tid, "url": f"https://user.qzone.qq.com/{expected}/mood/{tid}"}
