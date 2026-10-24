"""Small public Steam Store queries; no Web API key or full app catalog."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class SteamError(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None):
        self.code, self.http_status = code, http_status
        super().__init__("Steam 商店查询未完成" + (f"（HTTP {http_status}）" if http_status else ""))


def app_id(value: str) -> str | None:
    text = str(value).strip()
    if re.fullmatch(r"[1-9]\d{0,9}", text):
        return text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme in {"http", "https"} and parsed.hostname == "store.steampowered.com":
        match = re.fullmatch(r"/app/([1-9]\d{0,9})(?:/.*)?", parsed.path)
        if match:
            return match.group(1)
    return None


def _json(url: str, proxy: str, timeout: float):
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    request = urllib.request.Request(url, headers={"User-Agent": "FatFishLife/0.1", "Accept": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise SteamError("service_error")
        return json.loads(data)
    except urllib.error.HTTPError as exc:
        raise SteamError("service_error", http_status=exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SteamError("network") from None
    except (ValueError, UnicodeDecodeError):
        raise SteamError("service_error") from None


class SteamStore:
    def __init__(self, *, country="cn", proxy="", timeout=20, fetch=None):
        country = str(country).lower().strip()
        if not re.fullmatch(r"[a-z]{2}", country):
            raise ValueError("Steam 区域需要是两位国家代码，如 cn")
        self.country, self.proxy, self.timeout = country, str(proxy).strip(), timeout
        self.fetch = fetch or _json

    def _request(self, path: str, **params):
        params.update({"cc": self.country, "l": "schinese"})
        url = "https://store.steampowered.com" + path + "?" + urllib.parse.urlencode(params)
        return self.fetch(url, self.proxy, self.timeout)

    def search(self, query: str) -> list[dict]:
        query = str(query).strip()
        if not query or len(query) > 120:
            raise ValueError("请输入1到120字的游戏名或 appid")
        data = self._request("/api/storesearch/", term=query)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise SteamError("service_error")
        candidates = []
        for item in data["items"][:10]:
            if not isinstance(item, dict) or not app_id(str(item.get("id", ""))) or not str(item.get("name") or "").strip():
                continue
            candidates.append({"appid": str(item["id"]), "name": str(item["name"])[:200],
                               "url": f"https://store.steampowered.com/app/{item['id']}/"})
        return candidates

    def price(self, identifier: str) -> dict:
        identifier = app_id(identifier)
        if identifier is None:
            raise ValueError("价格查询需要有效 appid 或 Steam 商店 app 链接")
        data = self._request("/api/appdetails", appids=identifier, filters="basic,price_overview")
        entry = data.get(identifier) if isinstance(data, dict) else None
        if not isinstance(entry, dict) or entry.get("success") is not True or not isinstance(entry.get("data"), dict):
            raise SteamError("no_result")
        details = entry["data"]
        result = {"appid": identifier, "name": str(details.get("name") or f"Steam {identifier}")[:200],
                  "country": self.country, "url": f"https://store.steampowered.com/app/{identifier}/",
                  "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "is_free": details.get("is_free") is True, "price_available": False}
        price = details.get("price_overview")
        if isinstance(price, dict):
            initial, final = price.get("initial"), price.get("final")
            if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (initial, final)):
                result.update({"price_available": True, "currency": str(price.get("currency") or ""),
                               "initial": initial, "final": final,
                               "initial_formatted": str(price.get("initial_formatted") or ""),
                               "final_formatted": str(price.get("final_formatted") or ""),
                               "discount_percent": price.get("discount_percent", 0)})
        return result

    def lookup(self, query: str) -> dict:
        identifier = app_id(query)
        if identifier:
            return {"kind": "price", "game": self.price(identifier)}
        candidates = self.search(query)
        exact = [item for item in candidates if item["name"].casefold() == query.strip().casefold()]
        if len(exact) == 1:
            return {"kind": "price", "game": self.price(exact[0]["appid"])}
        return {"kind": "candidates", "items": candidates[:5]}


def format_result(result: dict) -> str:
    if result["kind"] == "candidates":
        candidates = result["items"]
        return "未找到匹配的 Steam 游戏。" if not candidates else "请选 appid 再查询价格：\n" + "\n".join(
            f"{item['name']}：{item['appid']}" for item in candidates)
    game = result["game"]
    heading = f"{game['name']}（{game['appid']}，{game['country'].upper()}区）"
    if game["is_free"]:
        price = "免费游玩"
    elif game["price_available"]:
        price = game["final_formatted"] or f"{game['currency']} {game['final'] / 100:.2f}"
        if game.get("discount_percent"):
            price += f"，优惠 {game['discount_percent']}%"
    else:
        price = "当前区域没有可用价格；可能尚未发售、停售或需要查看购买套餐"
    return heading + "\n" + price + "\n" + game["url"]
