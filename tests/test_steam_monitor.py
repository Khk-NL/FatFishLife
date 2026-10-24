import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fatfish_core.steam_monitor import load_cache, monitor_price, resolve_game


class SteamMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_bootstrap_keeps_cache_and_never_calls_key_only_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json";path.write_text(json.dumps({"Portal 2": "620"}))
            obj = SimpleNamespace(json1_path=path)
            with patch("fatfish_core.steam_monitor.SteamStore") as store:
                await load_cache(obj)
                store.assert_not_called()
            self.assertEqual(obj.app_dict_all_reverse[620], "Portal 2")

    async def test_ambiguous_name_never_subscribes_a_first_candidate(self):
        event = asyncio.Event();event.set()
        obj = SimpleNamespace(data_initialized=event,config={},app_dict_all={},app_dict_all_reverse={})
        store = Mock();store.lookup.return_value = {"kind": "candidates", "items": [{"appid": "620"}]}
        with patch("fatfish_core.steam_monitor.SteamStore",return_value=store):
            self.assertIsNone(await resolve_game(obj,"Portal"))
        self.assertFalse(obj.app_dict_all)

    async def test_monitor_preserves_currency_cents_and_proxy(self):
        store = Mock();store.price.return_value={"is_free":False,"price_available":True,"final":3500,"initial":7000,"discount_percent":50,"currency":"CNY"}
        with patch("fatfish_core.steam_monitor.SteamStore",return_value=store) as factory:
            row=await monitor_price(SimpleNamespace(config={"proxy":"http://127.0.0.1:7890"}),620)
            factory.assert_called_once_with(country="cn",proxy="http://127.0.0.1:7890")
        self.assertEqual((row["current_price"],row["original_price"],row["discount"]),(35,70,50))


if __name__ == "__main__":unittest.main()
