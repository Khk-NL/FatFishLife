from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from plugin_support import load_plugin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fatfish_core import MemoryStore
from fatfish_core.steam import SteamError, SteamStore, app_id, format_result

PLUGIN = load_plugin("astrbot_plugin_fatfish_steam")


def details(identifier="620", **kwargs):
    game = {"name": "Portal 2", "is_free": False, "price_overview": {"currency": "CNY", "initial": 3500, "final": 700,
            "discount_percent": 80, "initial_formatted": "", "final_formatted": "¥ 7.00"}, **kwargs}
    return {identifier: {"success": True, "data": game}}


class SteamTests(unittest.TestCase):
    def test_only_valid_appids_or_actual_store_app_links_are_identifiers(self):
        for value in ("620", "https://store.steampowered.com/app/620/Portal_2/?l=schinese"):
            self.assertEqual(app_id(value), "620")
        for value in ("0", "1,2", "https://evil.example/app/620/", "https://store.steampowered.com@evil.example/app/620", "Portal 2"):
            self.assertIsNone(app_id(value))

    def test_paid_price_country_and_proxy_are_preserved_without_api_key(self):
        fetch = Mock(return_value=details())
        store = SteamStore(country="CN", proxy="http://127.0.0.1:7890", fetch=fetch)
        result = store.lookup("620")
        game = result["game"]
        self.assertEqual((game["final"], game["currency"], game["discount_percent"]), (700, "CNY", 80))
        self.assertIn("¥ 7.00，优惠 80%", format_result(result))
        url, proxy, _ = fetch.call_args.args
        self.assertIn("cc=cn", url)
        self.assertIn("filters=basic%2Cprice_overview", url)
        self.assertNotIn("key=", url)
        self.assertEqual(proxy, "http://127.0.0.1:7890")

    def test_missing_price_is_unavailable_unless_explicitly_free(self):
        for free in (True, False):
            store = SteamStore(fetch=Mock(return_value=details(is_free=free, price_overview=None)))
            result = store.lookup("620")
            self.assertFalse(result["game"]["price_available"])
            self.assertIn("免费游玩" if free else "当前区域没有可用价格", format_result(result))

    def test_failure_and_malformed_price_never_become_zero_price(self):
        for payload in ({"620": {"success": False}}, [], {"620": {"success": True, "data": None}}):
            with self.assertRaises(SteamError):
                SteamStore(fetch=Mock(return_value=payload)).price("620")
        malformed = details(price_overview={"initial": 3500, "final": None})
        result = SteamStore(fetch=Mock(return_value=malformed)).lookup("620")
        self.assertFalse(result["game"]["price_available"])
        self.assertNotIn("免费", format_result(result))

    def test_search_ambiguity_does_not_choose_first_candidate(self):
        fetch = Mock(return_value={"items": [{"id": 620, "name": "Portal 2"}, {"id": 400, "name": "Portal"}]})
        result = SteamStore(fetch=fetch).lookup("Portal games")
        self.assertEqual(result["kind"], "candidates")
        self.assertIn("400", format_result(result))
        self.assertEqual(fetch.call_count, 1)

    def test_unique_exact_match_fetches_correct_game_not_first_search_result(self):
        fetch = Mock(side_effect=[{"items": [{"id": 620, "name": "Portal 2"}, {"id": 400, "name": "Portal"}]}, details("400", name="Portal")])
        result = SteamStore(fetch=fetch).lookup("portal")
        self.assertEqual(result["game"]["appid"], "400")
        self.assertIn("appids=400", fetch.call_args.args[0])

    def test_empty_result_invalid_query_and_country_are_explicit(self):
        store = SteamStore(fetch=Mock(return_value={"items": []}))
        self.assertEqual(format_result(store.lookup("not found")), "未找到匹配的 Steam 游戏。")
        with self.assertRaises(ValueError):
            store.lookup("")
        with self.assertRaises(ValueError):
            SteamStore(country="cn&key=secret")


class SteamPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.store = MemoryStore(Path(directory.name) / "memory.db")
        self.plugin.client = SteamStore(fetch=Mock(return_value=details()))
        self.event = types.SimpleNamespace(plain_result=lambda text: text)

    async def test_command_and_tool_work_without_background_monitoring(self):
        replies = [item async for item in self.plugin.steam(self.event, "价格 620")]
        self.assertIn("Portal 2", replies[0])
        self.assertIn("Portal 2", await self.plugin.price_tool(self.event, "620"))
        self.assertFalse(hasattr(self.plugin, "_task"))
        rows = self.plugin.store.recent(scopes=("private",), kinds=("capability",))
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.plugin.store.recent(scopes=("public",)), [])

    async def test_failure_growth_contains_no_query_or_transport_credentials(self):
        self.plugin.client.lookup = Mock(side_effect=SteamError("network"))
        result = await self.plugin.price_tool(self.event, "PRIVATE_QUERY")
        self.assertIn("未完成", result)
        rows = self.plugin.store.recent(scopes=("private",), kinds=("capability",))
        self.assertEqual(len(rows), 1)
        self.assertIn("失败", rows[0]["content"])
        self.assertNotIn("PRIVATE_QUERY", str(rows))

    async def test_help_and_invalid_input_make_no_growth_success(self):
        replies = [item async for item in self.plugin.steam(self.event)]
        self.assertIn("/steam", replies[0])
        await self.plugin.price_tool(self.event, "")
        self.assertEqual(self.plugin.store.recent(scopes=("private",), kinds=("capability",)), [])


if __name__ == "__main__":
    unittest.main()
