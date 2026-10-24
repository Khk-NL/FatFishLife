"""One-shot native QQ voice delivery to the explicitly authorized test group.

Call verify(context, tts_receipt, output) from the existing disabled acceptance
helper. This never synthesizes speech, calls an LLM or sends outside that group.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.prepare_minimax_voice import save_receipt


async def verify(context, tts_receipt: Path, output: Path):
    from astrbot.core.message.components import Plain, Record
    from astrbot.core.message.message_event_result import MessageChain
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
    from fatfish_video.renderer import _resolve_tool

    if output.exists():
        return json.loads(output.read_text(encoding="utf-8-sig"))
    state = {"target_group_name":"苹果乐乐乐", "expected_bot_id":"1670515707",
             "synthesis_calls":0, "client_playback_checked":False}
    # Readiness checks are read-only and bounded. Never resend after an uncertain send.
    bot = None
    for _ in range(120):
        platform = context.get_platform_inst("napcat")
        if platform is not None:
            bot = platform.get_client()
            try:
                login = await asyncio.wait_for(bot.call_action("get_login_info"), timeout=3)
                if str(login.get("user_id")) == state["expected_bot_id"]:
                    break
                raise ValueError("QQ account mismatch")
            except ValueError:
                raise
            except Exception as exc:
                state["last_readiness_error"] = type(exc).__name__
        await asyncio.sleep(2)
    else:
        raise RuntimeError("QQ connection did not become ready")
    offline = context.get_registered_star("astrbot_plugin_fatfish_offline").star_cls
    signal = offline.state.runtime.get("offline", "signal", {})
    if offline.enabled and signal.get("offline") is not False:
        return {**state,"blocked":"offline_or_economy_mode"}
    groups = await asyncio.wait_for(bot.call_action("get_group_list"), timeout=20)
    matches = [row for row in groups if row.get("group_name") == state["target_group_name"]]
    if len(matches) != 1:
        raise ValueError("Authorized group was not uniquely found")
    group_id = int(matches[0]["group_id"])
    capability = await asyncio.wait_for(bot.call_action("can_send_record"), timeout=15)
    if not capability.get("yes"):
        raise RuntimeError("QQ bridge reports voice sending unavailable")
    report = json.loads(tts_receipt.read_text(encoding="utf-8-sig"))
    first = report["attempts"][0]
    if first.get("state") != "passed" or not Path(first["audio"]).is_file():
        raise ValueError("A validated existing sample is required")
    state.update(group_id=group_id, voice_id=report["voice_id"], sends=[])
    save_receipt(output, state)

    class CaptureBot:
        async def send_group_msg(self, **arguments):
            if arguments.get("group_id") != group_id:
                raise ValueError("Send target differs from authorized test group")
            result = await bot.send_group_msg(**arguments)
            state["sends"][-1].update(state="sent", message_id=result.get("message_id"))
            save_receipt(output, state)
            return result

    try:
        for kind, chain in (("ai_label", [Plain("AI合成角色语音｜苹果乐 MiniMax 试听")]),
                            ("voice", [Record.fromFileSystem(first["audio"])])):
            state["sends"].append({"kind":kind,"state":"submitted"})
            save_receipt(output, state)
            await asyncio.wait_for(AiocqhttpMessageEvent.send_message(
                CaptureBot(), MessageChain(chain=chain), is_group=True, session_id=str(group_id)), timeout=90)
        message_id = state["sends"][-1]["message_id"]
        message = await asyncio.wait_for(bot.call_action("get_msg", message_id=message_id), timeout=20)
        records = [part for part in message.get("message", []) if part.get("type") == "record"]
        state["record_readback"] = bool(records)
        if records:
            converted = await asyncio.wait_for(bot.call_action("get_record", file=records[0]["data"]["file"], out_format="wav"), timeout=45)
            path = Path(converted["file"])
            process = await asyncio.create_subprocess_exec(str(_resolve_tool("ffmpeg")), "-v", "error", "-xerror", "-i", str(path),
                "-f", "null", "-", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(process.wait(), timeout=30)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            state["qq_converted_audio_decoded"] = process.returncode == 0
        save_receipt(output, state)
    except Exception as exc:
        state.update(error_type=type(exc).__name__, outcome="inspect_before_any_retry")
        save_receipt(output, state)
    return state
