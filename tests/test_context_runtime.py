import importlib.util
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin
from scripts.repair_chat_history import repair

PLUGIN = load_plugin("astrbot_plugin_fatfish_memory")
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

    async def test_cost_command_uses_existing_owner_boundary(self):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.store = types.SimpleNamespace(is_owner=lambda platform, uid: platform == 'qq' and uid == 'owner')
        plugin.report = Mock(return_value={'available': True, 'totals': {
            'calls': 3, 'total_tokens': 100, 'cache_hit_ratio': .5, 'estimate_cny': {'low': 1, 'high': 2}}})
        for platform, private, uid in [('aiocqhttp', False, 'owner'), ('aiocqhttp', True, 'other'), ('webchat', True, 'owner')]:
            event = types.SimpleNamespace(get_platform_name=lambda: platform, is_private_chat=lambda: private,
                                          get_sender_id=lambda: uid, plain_result=lambda text: text)
            result = [row async for row in plugin.costs(event)]
            self.assertEqual(result, ['成本统计请由老大私聊查看。'])
        plugin.report.assert_not_called()
        event = types.SimpleNamespace(get_platform_name=lambda: 'aiocqhttp', is_private_chat=lambda: True,
                                      get_sender_id=lambda: 'owner', plain_result=lambda text: text)
        result = [row async for row in plugin.costs(event)]
        self.assertIn('近24小时 3 次', result[0])

    async def test_existing_plugin_creates_one_store_and_cancels_monitor_on_unload(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data'
            tools = types.SimpleNamespace(get_data_dir=lambda _: data / 'plugin_data/astrbot_plugin_fatfish_memory')
            original_store = PLUGIN.MemoryStore
            with patch.object(PLUGIN.Star, '__init__', lambda self, context: None), patch.object(PLUGIN, 'StarTools', tools), \
                 patch.object(PLUGIN, 'MemoryStore', wraps=original_store) as constructor:
                plugin = PLUGIN.Main(types.SimpleNamespace())
                self.assertEqual(constructor.call_count, 1)
                self.assertEqual(plugin.directory, data / 'plugin_data/astrbot_plugin_fatfish_context')
                task = plugin._cost_monitor_task
                await plugin.terminate()
                self.assertTrue(task.cancelled())
                disabled = PLUGIN.Main(types.SimpleNamespace(), {'cost_monitor_enabled': False, 'structured_memory_export_enabled':False})
                self.assertIsNone(disabled._cost_monitor_task)
                await disabled.terminate()
        await PLUGIN.Main.__new__(PLUGIN.Main).terminate()

    async def test_conversation_documents_update_when_cost_monitor_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin = PLUGIN.Main.__new__(PLUGIN.Main)
            plugin.data = Path(temp) / 'data'
            plugin.config = {'cost_monitor_enabled':False}
            plugin.store = PLUGIN.MemoryStore(plugin.data / 'memory.db')
            plugin.store.remember('当前会话事实',platform='qq',scope='private',session='napcat:FriendMessage:123')
            await plugin._maintenance_once()
            files = list((plugin.data/'plugin_data/astrbot_plugin_fatfish_memory/conversations').glob('*.md'))
            self.assertEqual(len(files),1)
            text = files[0].read_text(encoding='utf-8')
            self.assertIn('当前会话事实',text)
            self.assertNotIn('123',text)

    async def test_shared_local_api_uses_auth_and_leaves_idle_unload_to_server(self):
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
