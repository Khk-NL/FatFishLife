"""Public-store adapter for the installed SteamSaleTracker subscription plugin."""
import asyncio
import json

from .steam import SteamStore


async def load_cache(plugin):
    """Initialize existing subscriptions without calling a key-only catalog API."""
    plugin.app_dict_all = json.loads(plugin.json1_path.read_text(encoding="utf-8-sig")) if plugin.json1_path.exists() else {}
    plugin.app_dict_all_reverse = {int(v): k for k, v in plugin.app_dict_all.items()}


async def resolve_game(plugin, user_input, target_dict=None):
    await plugin.data_initialized.wait()
    if target_dict:
        exact = next(((name, appid) for name, appid in target_dict.items() if name.casefold() == str(user_input).casefold()), None)
        if exact:
            return [exact[1], exact[0]]
    store = SteamStore(proxy=str(plugin.config.get("proxy") or ""))
    result = await asyncio.to_thread(store.lookup, str(user_input))
    if result["kind"] != "price":
        return None  # Ambiguous names must not silently subscribe the first game.
    game = result["game"]
    plugin.app_dict_all[game["name"]] = game["appid"]
    plugin.app_dict_all_reverse[int(game["appid"])] = game["name"]
    return [game["appid"], game["name"]]


async def monitor_price(plugin, appid, region="cn"):
    store = SteamStore(country=region, proxy=str(plugin.config.get("proxy") or ""))
    data = await asyncio.to_thread(store.price, str(appid))
    if data["is_free"]:
        return {"is_free": True, "current_price": 0, "original_price": 0, "discount": 100, "currency": "FREE"}
    if not data["price_available"]:
        return None
    return {"is_free": False, "current_price": data["final"] / 100, "original_price": data["initial"] / 100,
            "discount": data["discount_percent"], "currency": data["currency"]}
