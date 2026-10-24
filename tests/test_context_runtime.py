import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import AsyncMock

from plugin_support import load_plugin
from scripts.repair_chat_history import repair

PLUGIN = load_plugin("astrbot_plugin_fatfish_context")
path = Path(__file__).resolve().parents[1] / "bots/astrbot_plugin_fatfish_offline/local_model.py"
spec = importlib.util.spec_from_file_location("local_model_runtime_test", path)
LOCAL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LOCAL)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_limits_images_without_changing_system_or_other_sessions(self):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {"max_current_images": 2}
        req = types.SimpleNamespace(contexts=[], image_urls=["a", "b", "c"],
                                    extra_user_content_parts=[], system_prompt="stable")
        await plugin.bounded_history(None, req)
        self.assertEqual(req.image_urls, ["a", "b"])
        self.assertEqual(req.system_prompt, "stable")
        self.assertIn("3张", req.extra_user_content_parts[0].text)

    async def test_shared_local_api_uses_auth_and_is_never_unloaded(self):
        model = LOCAL.LocalModel("http://127.0.0.1:6193/v1", "fatfish-context", api_key="local-test")
        await model._client.aclose()
        response = types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                    json=lambda: {"choices": [{"message": {"content": "短回复"}}]})
        model._client = types.SimpleNamespace(get=AsyncMock(return_value=response), post=AsyncMock(return_value=response), aclose=AsyncMock())
        self.assertTrue(await model.available())
        self.assertEqual(await model.chat("system", "user"), "短回复")
        call = model._client.post.call_args
        self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer local-test"})
        self.assertNotIn("keep_alive", call.kwargs["json"])
        await model.unload()
        self.assertEqual(model._client.post.await_count, 1)
        await model.close()


class HistoryRepairTests(unittest.TestCase):
    def test_repair_backs_up_original_and_is_idempotent_without_merging_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db_path = root / "data.db"; backup = root / "backups"
            polluted = json.dumps([{"role": "user", "content": "（系统自检：请报告当前情感状态）"},
                                   {"role": "user", "content": "当前群的事实"}], ensure_ascii=False)
            safe = json.dumps([{"role": "user", "content": "另一个群的事实"}], ensure_ascii=False)
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute("CREATE TABLE conversations(inner_conversation_id TEXT,content TEXT)")
                db.executemany("INSERT INTO conversations VALUES (?,?)", [("group-a", polluted), ("group-b", safe)])
            self.assertEqual(repair(db_path, backup, apply=True)["changed"], 1)
            self.assertEqual((backup / "group-a.json").read_text(encoding="utf-8"), polluted)
            self.assertEqual(repair(db_path, backup, apply=True)["changed"], 0)
            with closing(sqlite3.connect(db_path)) as db:
                rows = dict(db.execute("SELECT * FROM conversations"))
            self.assertEqual(rows["group-b"], safe)
            self.assertNotIn("另一个群", rows["group-a"])
