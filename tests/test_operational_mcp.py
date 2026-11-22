import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fatfish_core import operational

ROOT = Path(__file__).resolve().parents[1]


class OperationalMcpTest(unittest.TestCase):
    def test_heartbeat_does_not_infer_transport_or_return_errors(self):
        now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            heartbeat = directory / "scheduler-heartbeat.json"
            self.assertEqual(operational.health(directory, qq_paused=False, now=now)["scheduler"], "unknown")
            for at, error, expected in [
                ("2026-11-20T11:59:50Z", "", "ready"),
                ("2026-11-20T11:59:50Z", "private details", "degraded"),
                ("2026-11-20T11:00:00Z", "", "stale"),
                ("2026-11-20T12:30:00Z", "", "unknown"),
            ]:
                heartbeat.write_text(json.dumps({"at": at, "transport": {"online": True}, "error": error}))
                row = operational.health(directory, qq_paused=True, now=now)
                self.assertEqual(row["scheduler"], expected)
                self.assertEqual(row["qq"], "paused")
                self.assertEqual(row["wechat"], "not_probed")
                self.assertNotIn("private details", json.dumps(row))
                self.assertEqual(operational.health(directory, qq_paused=False, now=now)["qq"],
                                 "online" if expected == "ready" else "unknown")

    def test_sdk_client_permissions_receipts_and_review(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "schedule-state.json"
            path.write_text(json.dumps({"results": {
                "bili-recommend-noon": {"at": "2026-11-20T04:30:00Z", "ok": False,
                                       "reason": "started-result-unknown", "greeting": "PRIVATE_DATA"},
                "bili-recommend-evening": {"ok": False, "skipped": True,
                    "reason": "recommendation-no-grounded-result",
                    "selection": {"candidates": 8, "shortlisted": 2, "withStoryboard": 2, "grounded": 0,
                                  "titles": "PRIVATE_DATA"},
                    "modelReceipt": {"requestedModel": "deepseek-flash", "actualModel": "C:/PRIVATE_DATA",
                                     "status": "completed", "tokens": {"inputTokens": 100, "outputTokens": 12,
                                                                       "cacheHitTokens": 0, "extra": "PRIVATE_DATA"}}},
                "bili-study": {"at": "2026-11-20T13:00:00Z", "ok": True, "modelCalls": 0,
                               "skipped": True, "reason": "PRIVATE_DATA"},
                "bili-dynamic": {"ok": True, "sent": 1, "modelCalls": 1, "dynamicId": "PRIVATE_DATA"},
                "PRIVATE_DATA": {"ok": True},
            }, "skillEvidence": {
                "bili_lookup": ["2026-11-20T04:30:00Z", "2026-11-20T12:30:00Z", "2026-11-21T04:30:00Z"],
                "diary": ["2026-11-20T15:50:00Z"] * 3,
            }}))
            database = directory / "memory.sqlite"
            frozen = directory / "paused"
            frozen.touch()
            params = StdioServerParameters(
                command=sys.executable, args=[str(ROOT / "dsh/service/fatfish_memory_mcp.py")],
                cwd=str(ROOT), env={**os.environ, "FATFISH_MEMORY_DB": str(database),
                                    "FATFISH_DSH_DATA": folder, "FATFISH_QQ_PAUSE_FILE": str(frozen),
                                    "FATFISH_HUB_WRITE": "0", "FATFISH_SERVICE_READONLY": "1"},
            )

            async def verify():
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        init = await session.initialize()
                        self.assertEqual(init.protocol_version, "2025-11-25")
                        result = await session.list_tools()
                        tool = next(item for item in result.tools if item.name == "operations_overview")
                        self.assertTrue(tool.annotations.read_only_hint)
                        self.assertEqual(tool.input_schema["type"], "object")
                        self.assertIsNotNone(tool.output_schema)
                        receipts = await session.call_tool(tool.name, {"view": "receipts"})
                        self.assertFalse(receipts.is_error)
                        tasks = {item["task"]: item for item in receipts.structured_content["tasks"]}
                        self.assertEqual(len(tasks), 4)
                        self.assertEqual(tasks["bili-recommend-noon"]["status"], "unconfirmed")
                        self.assertEqual(tasks["bili-study"]["status"], "skipped")
                        recommend = tasks["bili-recommend-evening"]
                        self.assertEqual(recommend["reason"], "recommendation-no-grounded-result")
                        self.assertEqual(recommend["selection"]["grounded"], 0)
                        self.assertEqual(recommend["model_receipt"], {"requestedModel": "deepseek-flash",
                            "status": "completed", "tokens": {"inputTokens": 100, "outputTokens": 12, "cacheHitTokens": 0}})
                        self.assertNotIn("model_receipt", tasks["bili-study"])
                        self.assertEqual(tasks["bili-dynamic"]["model_calls"], 1)
                        self.assertNotIn("PRIVATE_DATA", receipts.model_dump_json())
                        skills = await session.call_tool(tool.name, {"view": "skills"})
                        self.assertEqual(skills.structured_content["status"], "review_required")
                        self.assertEqual([row["capability"] for row in skills.structured_content["candidates"]],
                                         ["bili_lookup"])
                        self.assertEqual(skills.structured_content["candidates"][0]["verified_slots"], [
                            "2026-11-20T04:30:00+00:00", "2026-11-20T12:30:00+00:00",
                            "2026-11-21T04:30:00+00:00",
                        ])
                        self.assertTrue((await session.call_tool(tool.name, {"view": "unexpected"})).is_error)
                        growth = await session.call_tool("growth_record", {"capability": "bili_lookup"})
                        self.assertTrue(growth.is_error)

            asyncio.run(verify())
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
