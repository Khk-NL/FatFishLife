"""Native read-only replay, called by an existing AstrBot acceptance helper.

    from scripts.verify_public_lookup import verify_public_lookup
    await verify_public_lookup(context, Path('data/temp/public-lookup-replay.json'))

This uses a synthetic event and never sends a QQ message. It verifies native
AnySearch execution, per-chat reuse and final summaries; it is not live inbox
acceptance. Only the public test questions/answers and usage are saved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import time


async def verify_public_lookup(context, output: Path, *, provider_id=None, include_affection=False):
    from astrbot.core.agent.tool import ToolSet
    from astrbot.core.message.components import Plain
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.entities import ProviderRequest
    from fatfish_core.query_evidence import format_reply_parts, public_urls
    from fatfish_core.usage import record_usage

    class NoSendEvent(AstrMessageEvent):
        async def send(self, *args, **kwargs):
            raise RuntimeError("Verification cannot send platform messages")

    def make_event(prompt):
        message = AstrBotMessage()
        message.type = MessageType.FRIEND_MESSAGE
        message.self_id = "synthetic-bot"
        message.sender = MessageMember(user_id="synthetic-user", nickname="verification")
        message.message = [Plain(prompt)]
        message.message_str = prompt
        message.message_id = "verification-" + str(time.monotonic_ns())
        message.raw_message = {}
        return NoSendEvent(prompt, message,
                           PlatformMetadata(name="verification", description="No-send public query replay", id="fatfish-verification"),
                           "public-lookup")

    metadata = context.get_registered_star("astrbot_plugin_fatfish_memory")
    if not metadata or not metadata.activated or metadata.star_cls is None:
        raise RuntimeError("Memory plugin is not active")
    plugin = metadata.star_cls
    manager = context.get_llm_tool_manager()
    whitelist = [tool for name in ("anysearch_search", "anysearch_extract")
                 if (tool := manager.get_func(name)) is not None and tool.active]
    if not any(tool.name == "anysearch_search" for tool in whitelist):
        raise RuntimeError("AnySearch read-only search is unavailable")
    provider_id = provider_id or await context.get_current_chat_provider_id("fatfish-verification:FriendMessage:public-lookup")
    provider = context.get_provider_by_id(provider_id)
    persona = Path(__file__).resolve().parents[1] / "docs/persona/apple-le-core.md"
    prompts = ["明日方舟前瞻刚刚讲什么了", "怎么不理我"]
    if include_affection:
        prompts.append("宝宝，陪我玩一会儿嘛")
    history, rows = [], []
    for prompt in prompts:
        event = make_event(prompt)
        req = ProviderRequest(prompt=prompt, contexts=list(history), func_tool=ToolSet(list(whitelist)))
        await plugin.prepare_public_lookup(event, req)
        state = plugin._query_state(event)
        # The preflight already executed the one allowed external search. The
        # native agent now produces one grounded summary, with no write tools.
        response = await context.tool_loop_agent(
            event=event, chat_provider_id=provider_id, prompt=prompt,
            tools=ToolSet(), contexts=list(history),
            extra_user_content_parts=req.extra_user_content_parts,
            system_prompt=persona.read_text(encoding="utf-8") + "\n当前合成对话对象称老大；这不是平台入站消息，不执行任何平台写操作。",
            max_steps=2, request_max_retries=1, tool_schema_mode="full", stream=False,
        )
        await record_usage(context, provider, response, umo="fatfish:Internal:public_lookup_acceptance",
                           agent_type="fatfish_verification")
        await plugin.grounded_lookup_response(event, response)
        text = format_reply_parts([response.completion_text], active_lookup=bool(state.get("goal")))
        evidence_text = "\n".join(str(getattr(part, "text", "")) for part in req.extra_user_content_parts)
        source_urls = public_urls(evidence_text)
        answer_urls = public_urls(text)
        checks = {
            "goal_retained": prompt != "怎么不理我" or state.get("goal") == prompts[0],
            "no_reasking_target": not any(term in text for term in ("查什么", "查啥", "什么前瞻", "哪个服", "哪场")),
            "no_unsupported_source_url": all(url in source_urls for url in answer_urls),
            "no_empty_progress": not any(term in text for term in ("我去查", "我再去查", "等等，我")),
            "sources_found": bool(state.get("found")),
            "source_when_citing_fact": bool(answer_urls) or not re.search(r"通讯#|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2}", text),
            "complaint_resolved_as_task": prompt != "怎么不理我" or not any(term in text for term in ("没不理你", "一直在回", "这不在回")),
        }
        rows.append({"prompt":prompt,"answer":text,"actual_search_calls":state.get("started",0),
                     "cache_used":bool(state.get("cached")),"source_urls":source_urls,"checks":checks})
        history += [{"role":"user","content":prompt},{"role":"assistant","content":text}]
    report = {"synthetic_no_platform_send":True,"provider_id":provider_id,
              "search_calls":sum(row["actual_search_calls"] for row in rows),"turns":rows}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
