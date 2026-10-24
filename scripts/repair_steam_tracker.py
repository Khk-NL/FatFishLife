"""Install the public-store bridge while preserving Steam subscriptions/config."""
import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import shutil


def patched_source(text):
    if "FATFISH_PUBLIC_STORE_BRIDGE" in text:
        return text
    tree = ast.parse(text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SteamSaleTrackerPlugin")
    lines = text.splitlines(keepends=True)
    replacements = []
    for node in cls.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in ("get_app_list", "get_appid_by_name", "get_steam_price"):
            args, call = {
                "get_app_list": ("self", "load_cache(self)"),
                "get_appid_by_name": ("self, user_input, target_dict=None", "resolve_game(self,user_input,target_dict)"),
                "get_steam_price": ("self, appid, region='cn'", "monitor_price(self,appid,region)"),
            }[node.name]
            replacement = f"    async def {node.name}({args}):\n        return await {call}\n"
            replacements.append((node.lineno - 1, node.end_lineno, replacement))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "steamremind_command":
            body = "".join(lines[node.lineno - 1:node.end_lineno])
            start = body.index("        if not self.app_dict_all:")
            end = body.index('        region = "cn"', start)
            body = body[:start] + body[end:]
            start = body.index("            # 输入的是 appid")
            end = body.index("        else:", start)
            body = body[:start] + "            game_info_list = await self.get_appid_by_name(args[0])\n" + body[end:]
            body = body.replace('        if len(args) < 1:', '        app_name = " ".join(args)\n        if len(args) < 1:')
            replacements.append((node.lineno - 1, node.end_lineno, body))
    if len(replacements) != 4:
        raise ValueError("Unsupported SteamSaleTracker version; no files changed")
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]
    result = ("from fatfish_core.steam_monitor import load_cache,resolve_game,monitor_price\n"
              "FATFISH_PUBLIC_STORE_BRIDGE = True\n" + "".join(lines))
    compile(result, "SteamSaleTracker bridge", "exec")
    return result


def install(root, proxy):
    directory = root / "data/plugins/astrbot_plugin_SteamSaleTracker"
    path = directory / "main.py"
    previous = path.read_text(encoding="utf-8-sig")
    result = patched_source(previous)
    if result != previous:
        backup = root / "data/private-config-backups" / ("steam-tracker-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup / "main.py")
        path.write_text(result, encoding="utf-8")
    schema_path = directory / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    schema["proxy"] = {"type": "string", "description": "Steam公开商店代理，可留空直连", "default": ""}
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg_path = root / "data/config/astrbot_plugin_SteamSaleTracker_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")); cfg["proxy"] = proxy
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"patched": result != previous, "subscriptions_preserved": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--astrbot", type=Path, required=True)
    p.add_argument("--proxy", default="")
    args = p.parse_args()
    print(json.dumps(install(args.astrbot, args.proxy)))
