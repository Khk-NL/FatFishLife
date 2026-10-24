"""Backfill existing group corpus and verify the actual hook/model path; no sends."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    os.environ["ASTRBOT_ROOT"] = str(args.astrbot.resolve())
    sys.path.insert(0, str(args.astrbot))
    from astrbot.core import db_helper
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    from fatfish_core import MemoryStore, RuntimeStore, resolve_shared_db
    spec = importlib.util.spec_from_file_location("_style_acceptance", ROOT / "bots/astrbot_plugin_fatfish_style/main.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    cfg = json.loads((args.astrbot / "data/cmd_config.json").read_text(encoding="utf-8-sig"))
    model = next(p for p in cfg["provider"] if p["id"] == "deepseek/deepseek-flash")
    source = next(p for p in cfg["provider_sources"] if p["id"] == model["provider_source_id"])
    provider = ProviderOpenAIOfficial({**source, **model, "custom_extra_body": {"thinking": {"type": "disabled"}}}, cfg.get("provider_settings", {}))
    life = json.loads((args.astrbot / "data/config/astrbot_plugin_fatfish_life_config.json").read_text(encoding="utf-8-sig"))
    async def get_provider(umo=None): return provider
    plugin = module.Main.__new__(module.Main)
    plugin.context = SimpleNamespace(get_using_provider_async=get_provider, get_db=lambda: db_helper)
    plugin.config = {"enabled": True, "min_messages": 10}
    plugin.bot = str(life["qq_bot_id"])
    plugin.source = args.astrbot / "data/plugin_data/astrbot_plugin_self_learning/messages.db"
    db_path = resolve_shared_db(args.astrbot / "data")
    plugin.runtime, plugin.store = RuntimeStore(db_path), MemoryStore(db_path)
    plugin._jobs, plugin._semaphore = {}, asyncio.Semaphore(1)
    with sqlite3.connect(plugin.source.resolve().as_uri() + "?mode=ro", uri=True) as db:
        groups = [args.group] if args.group else [r[0] for r in db.execute("SELECT DISTINCT group_id FROM style_learning_reviews")]
    report = {"message_sent": False, "groups": [], "style_hook_verified": False}
    try:
        for group in groups:
            added = await plugin.refresh(group)
            state = plugin._style(group).load()
            entry = {"added": added, "messages": state["messages"], "patterns": len(state["patterns"])}
            if state["patterns"] and not report["style_hook_verified"]:
                extra = {}
                query = "老板，今天在忙什么呀？"
                event = SimpleNamespace(get_platform_name=lambda: "aiocqhttp", is_private_chat=lambda: False,
                    get_self_id=lambda: plugin.bot, get_group_id=lambda: group, get_sender_id=lambda: "operator-local-replay",
                    get_extra=lambda key: extra.get(key), set_extra=lambda key, value: extra.update({key: value}),
                    unified_msg_origin="napcat:GroupMessage:" + group, message_str=query)
                req = ProviderRequest(prompt=query, system_prompt="你是苹果乐，以能天使为基础，短句自然，称呼老板。")
                await plugin.inject_style(event, req)
                entry["reference_added"] = bool(req.extra_user_content_parts)
                if req.extra_user_content_parts:
                    result = await provider.text_chat(prompt=req.prompt, system_prompt=req.system_prompt,
                                                      extra_user_content_parts=req.extra_user_content_parts)
                    entry["model_response"] = result.completion_text
                    report["style_hook_verified"] = bool(result.completion_text)
            report["groups"].append(entry)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"message_sent": False, "groups": len(groups), "patterns": sum(r["patterns"] for r in report["groups"]),
                          "style_hook_verified": report["style_hook_verified"]}))
    finally:
        await plugin.terminate()
        await provider.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--astrbot", type=Path, required=True)
    p.add_argument("--group")
    p.add_argument("--output", type=Path, default=ROOT / "outputs/group-style-acceptance.json")
    asyncio.run(run(p.parse_args()))
