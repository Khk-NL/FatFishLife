from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots"))

from astrbot_plugin_fatfish_life import publishers  # noqa: E402


class QzonePublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = Mock()
        self.bot.call_action = AsyncMock(side_effect=[
            {"user_id": 1670515707}, {"tid": "abc123_456-def"},
        ])
        self.platform = Mock()
        self.platform.meta.return_value = Mock(name="QQ")
        self.platform.meta.return_value.name = "aiocqhttp"
        self.platform.get_client.return_value = self.bot
        self.context = Mock()
        self.context.get_platform_inst.return_value = self.platform

    async def publish(self, text="今天遇到了有趣的事。", platform="napcat", account="1670515707"):
        return await publishers.publish_qzone(self.context, text, platform, account)

    async def test_authorized_account_is_checked_before_publish_and_both_calls_are_locked(self):
        result = await self.publish(" 今天 @老板 讲了个笑话。 ")

        self.context.get_platform_inst.assert_called_once_with("napcat")
        self.platform.get_client.assert_called_once_with()
        self.assertEqual(self.bot.call_action.await_args_list, [
            call("get_login_info", self_id="1670515707"),
            call("send_qzone_msg", self_id="1670515707",
                 content="今天 ＠老板 讲了个笑话。", images=[], ugc_right=1,
                 target_uins=[]),
        ])
        self.assertEqual(result, {
            "ok": True, "status": "sent", "id": "abc123_456-def",
            "url": "https://user.qzone.qq.com/1670515707/mood/abc123_456-def",
        })

    async def test_connected_human_account_does_not_publish(self):
        self.bot.call_action.side_effect = [{"user_id": 3124904460}]
        result = await self.publish()

        self.assertEqual(result["error"]["code"], "account_mismatch")
        self.assertEqual(result["status"], "blocked")
        self.bot.call_action.assert_awaited_once_with("get_login_info", self_id="1670515707")

    async def test_other_expected_account_is_rejected_without_accessing_a_connection(self):
        result = await self.publish(account="3124904460")

        self.assertEqual(result["error"]["code"], "account_not_authorized")
        self.context.get_platform_inst.assert_not_called()
        self.bot.call_action.assert_not_called()

    async def test_missing_configuration_does_not_access_a_connection(self):
        for platform, account in (("", "1670515707"), ("napcat", "")):
            with self.subTest(platform=platform, account=account):
                result = await self.publish(platform=platform, account=account)
                self.assertEqual(result["error"]["code"], "missing_account")
        self.context.get_platform_inst.assert_not_called()

    async def test_empty_or_nontext_body_does_not_access_a_connection(self):
        for text in (" \n ", None, ["body"]):
            with self.subTest(text=text):
                result = await self.publish(text=text)
                self.assertEqual(result["error"]["code"], "invalid_argument")
        self.context.get_platform_inst.assert_not_called()

    async def test_missing_platform_does_not_call_onebot(self):
        self.context.get_platform_inst.return_value = None
        result = await self.publish()

        self.assertEqual(result["error"]["code"], "invalid_platform")
        self.bot.call_action.assert_not_called()

    async def test_other_platform_type_does_not_get_client(self):
        self.platform.meta.return_value.name = "qq_official"
        result = await self.publish()

        self.assertEqual(result["error"]["code"], "invalid_platform")
        self.platform.get_client.assert_not_called()

    async def test_identity_failure_does_not_publish_or_expose_exception(self):
        self.bot.call_action.side_effect = RuntimeError("secret login response")
        result = await self.publish()

        self.assertEqual(result["error"]["code"], "identity_unavailable")
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("secret", str(result))
        self.bot.call_action.assert_awaited_once_with("get_login_info", self_id="1670515707")

    async def test_bad_identity_response_does_not_publish(self):
        for info in (None, {}, {"data": {"user_id": 1670515707}}, {"user_id": "other"}):
            with self.subTest(info=info):
                self.bot.call_action.reset_mock()
                self.bot.call_action.side_effect = [info]
                result = await self.publish()
                self.assertEqual(result["error"]["code"], "account_mismatch")
                self.bot.call_action.assert_awaited_once_with("get_login_info", self_id="1670515707")

    async def test_publish_failure_is_uncertain_and_not_retried(self):
        self.bot.call_action.side_effect = [
            {"user_id": "1670515707"}, RuntimeError("secret send response"),
        ]
        result = await self.publish()

        self.assertEqual(result["error"]["code"], "publish_unconfirmed")
        self.assertEqual(result["status"], "uncertain")
        self.assertNotIn("secret", str(result))
        self.assertEqual(self.bot.call_action.await_count, 2)

    async def test_only_a_valid_tid_confirms_delivery(self):
        for response in (None, {}, {"tid": ""}, {"tid": True}, {"tid": 123},
                         {"tid": "../bad"}, {"tid": "a" * 129},
                         {"data": {"tid": "abc123"}}):
            with self.subTest(response=response):
                self.bot.call_action.reset_mock()
                self.bot.call_action.side_effect = [{"user_id": 1670515707}, response]
                result = await self.publish()
                self.assertEqual(result["status"], "uncertain")
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "missing_receipt")
                self.assertEqual(self.bot.call_action.await_count, 2)

    async def test_cancel_during_identity_check_propagates_without_sending(self):
        self.bot.call_action.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.publish()
        self.bot.call_action.assert_awaited_once_with("get_login_info", self_id="1670515707")

    async def test_cancel_during_publish_propagates_without_retry(self):
        self.bot.call_action.side_effect = [{"user_id": 1670515707}, asyncio.CancelledError]
        with self.assertRaises(asyncio.CancelledError):
            await self.publish()
        self.assertEqual(self.bot.call_action.await_count, 2)

    async def test_identity_timeout_is_bounded_and_does_not_publish(self):
        async def delayed(*args, **kwargs):
            await asyncio.sleep(30)

        self.bot.call_action.side_effect = delayed
        with patch.object(publishers, "ACTION_TIMEOUT_SECONDS", 0.001):
            result = await self.publish()
        self.assertEqual(result["error"]["code"], "identity_unavailable")
        self.bot.call_action.assert_awaited_once_with("get_login_info", self_id="1670515707")

    async def test_publish_timeout_is_bounded_and_uncertain_without_retry(self):
        async def delayed(action, **kwargs):
            if action == "get_login_info":
                return {"user_id": 1670515707}
            await asyncio.sleep(30)

        self.bot.call_action.side_effect = delayed
        with patch.object(publishers, "ACTION_TIMEOUT_SECONDS", 0.001):
            result = await self.publish()
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["error"]["code"], "publish_unconfirmed")
        self.assertEqual(self.bot.call_action.await_count, 2)


if __name__ == "__main__":
    unittest.main()
