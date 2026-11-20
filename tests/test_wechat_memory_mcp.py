import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fatfish_core.memory import MemoryStore
from fatfish_core import wechat_memory

ROOT = Path(__file__).resolve().parents[1]


class WechatMemoryTest(unittest.TestCase):
    def test_queued_preferences_wait_until_china_deadline_and_catch_up_once(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            scope, turn = "a" * 64, "b" * 64
            at = 1_800_000_000
            due = wechat_memory.due_at(at)
            self.assertGreater(due, at)
            self.assertEqual(due % 86_400, 15 * 3600 + 30 * 60)
            memo = "我喜欢雨天"
            self.assertEqual(wechat_memory.save(store, scope, turn, memo, pending_until=due)["status"], "staged")
            self.assertEqual(wechat_memory.find(store, scope, "")["notes"], [])
            self.assertEqual(wechat_memory.flush(store, due - 1)["committed"], 0)
            self.assertEqual(wechat_memory.flush(store, due + 86_400)["committed"], 1)
            self.assertEqual(wechat_memory.flush(store, due + 86_400)["committed"], 0)
            self.assertEqual(wechat_memory.find(store, scope, "雨天")["notes"][0]["text"], memo)
            self.assertTrue(wechat_memory.claim_open(store, scope, turn, at))
            self.assertFalse(wechat_memory.claim_open(store, scope, turn, at + 1))

    def test_idempotent_bounded_append_does_not_enter_event_recall(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.db")
            scope, turn = "a" * 64, "b" * 64
            with ThreadPoolExecutor(max_workers=4) as tasks:
                replies = list(tasks.map(lambda _: wechat_memory.save(store, scope, turn, "我喜欢南瓜"), range(6)))
            self.assertEqual(sum(reply.get("status") == "saved" for reply in replies), 1)
            self.assertEqual(wechat_memory.save(store, scope, turn, "我喜欢面包")["reason"], "source-conflict")
            self.assertFalse(wechat_memory.save(store, scope, "c" * 64, "记住密码 0000")["ok"])
            for number in range(11):
                self.assertTrue(wechat_memory.save(store, scope, f"{number:064x}", f"合成测试备注 {number}")["ok"])
            self.assertEqual(wechat_memory.save(store, scope, "c" * 64, "超过当日额度")["reason"], "daily-memory-limit")
            self.assertEqual(wechat_memory.find(store, "c" * 64, "")["notes"], [])
            self.assertEqual(len(wechat_memory.find(store, scope, "")["notes"]), 3)
            self.assertEqual(store.recall("南瓜", scopes=("private",)), [])

    def test_official_mcp_client_requires_current_bridge_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            key = bytes(range(32))
            (folder / "wechat-capability.key").write_bytes(key)
            db = folder / "memory.db"
            MemoryStore(db)
            env = {**os.environ, "FATFISH_DSH_DATA": str(folder), "FATFISH_MEMORY_DB": str(db),
                   "FATFISH_SERVICE_READONLY": "1"}
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "dsh/service/fatfish_memory_mcp.py")],
                                           env=env, cwd=str(ROOT))

            def args(op, value, *, scope="a", at=None):
                body = json.dumps({"scope": scope * 64, "turn": "b" * 64, "op": op, "value": value,
                                   "time": at if at is not None else int(time.time())})
                return {"body": body, "mac": hmac.new(key, body.encode(), sha256).hexdigest()}

            async def probe():
                async with asyncio.timeout(12), stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tool = "wechat_capability_internal"
                        denied = await session.call_tool(tool, {"body": "{}", "mac": "a" * 64})
                        self.assertTrue(denied.is_error)
                        expired = await session.call_tool(tool, args("save", "已过期内容", at=int(time.time()) - 40))
                        self.assertTrue(expired.is_error)
                        saved = await session.call_tool(tool, args("save", "我特别喜欢桂花"))
                        self.assertEqual(saved.structured_content, {"ok": True, "status": "saved"})
                        own = await session.call_tool(tool, args("find", "桂花"))
                        self.assertEqual(own.structured_content["notes"][0]["text"], "我特别喜欢桂花")
                        other = await session.call_tool(tool, args("find", "桂花", scope="c"))
                        self.assertEqual(other.structured_content["notes"], [])
                        arbitrary_app = await session.call_tool(tool, args("open", "C:/unexpected.exe"))
                        self.assertTrue(arbitrary_app.is_error)
                        (folder / "wechat-capability.key").unlink()
                        disabled = await session.call_tool(tool, args("save", "撤回后的内容"))
                        self.assertTrue(disabled.is_error)

            asyncio.run(probe())
