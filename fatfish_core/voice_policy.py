"""Thin policy/delivery adapters for the installed MIT TTS Emotion Router.

The community plugin owns synthesis, emotion, cooldown, probability and history.
These wrappers only gate that work and protect this event's existing sender.
"""
from __future__ import annotations

import asyncio
from functools import wraps
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile

LOG = logging.getLogger(__name__)
DEFAULT_POLICY = {
    "enabled": False, "voice_probability": .10, "cooldown_seconds": 180,
    "max_text_length": 80, "manual_trigger": True, "fallback_to_text": True,
    "text_alongside_voice": False, "disable_during_economy_mode": True,
}
MANUAL_REQUEST = re.compile(r"(?:用|发|来|转|说|读).{0,8}(?:语音|声音)|(?:语音|声音).{0,8}(?:说|读|回复|回答|来|发)|念(?:一下|一遍|给我听)|读给我听")
VOICE_OPT_OUT = re.compile(r"(?:别|不要|不用|不必|不想|禁止).{0,4}(?:语音|声音)|(?:用文字|打字回复|文字就好)")


def policy(router):
    return {**DEFAULT_POLICY, **(router.config.get("fatfish_policy", {}) or {})}


def _offline(router):
    """Read the existing shared offline signal, never infer online from failure."""
    try:
        metadata = router.context.get_registered_star("astrbot_plugin_fatfish_offline")
        instance = getattr(metadata, "star_cls", None)
        if instance is None:
            return True
        if not instance.enabled:
            return False
        signal = instance.state.runtime.get("offline", "signal", {})
        return signal.get("offline") is not False
    except (AttributeError, OSError, ValueError):
        return True


async def _allowed(router, event, text, *, manual=False):
    cfg = policy(router)
    if not cfg["enabled"] or not str(event.unified_msg_origin or ""):
        return False
    if not router.config.is_voice_output_enabled_for_umo(str(event.unified_msg_origin)):
        return False
    if not str(event.get_platform_name()).startswith(("aiocqhttp", "qq_official")):
        return False
    if not text.strip() or len(text) > int(cfg["max_text_length"]):
        return False
    if cfg["disable_during_economy_mode"] and _offline(router):
        return False
    if manual and not cfg["manual_trigger"]:
        return False
    from astrbot.core.star.session_llm_manager import SessionServiceManager
    return await SessionServiceManager.should_process_tts_request(event)


def _sync_native_limits(router):
    """Use the router's actual checker instead of adding another random roll."""
    cfg = policy(router)
    router.condition_checker.prob = max(0., min(1., float(cfg["voice_probability"])))
    router.condition_checker.cooldown = max(0, int(cfg["cooldown_seconds"]))
    router.condition_checker.text_limit = max(1, int(cfg["max_text_length"]))


def _reserve(router, event):
    pending = getattr(router, "_fatfish_voice_inflight", None)
    if pending is None:
        pending = router._fatfish_voice_inflight = set()
    key = str(event.unified_msg_origin)
    if key in pending or len(pending) >= 2:
        return False
    pending.add(key)
    return True


def _release(router, event):
    router._fatfish_voice_inflight.discard(str(event.unified_msg_origin))


def _cleanup(paths, root):
    root = Path(root).resolve()
    for raw in paths:
        if not raw:
            continue
        try:
            path = Path(str(raw).removeprefix("file:///")).resolve()
            if path.is_relative_to(root):
                path.unlink(missing_ok=True)
        except OSError:
            # The community router's existing TTL cleaner handles locked files.
            LOG.warning("Voice temporary file cleanup deferred")


def protect_delivery(event, chain, text, *, root, alongside=False, fallback=True):
    """Keep native OneBot sending; records stay separate and failures use text.

    Attach only to this event and restore after its records complete. No queue,
    model call, protocol client or generated dialogue is introduced. Each record
    gets an event-owned copy so deleting it cannot invalidate a shared cache hit.
    """
    from astrbot.core.message.components import Plain
    records = [part for part in chain if type(part).__name__ == "Record"]
    if not records:
        return
    root = Path(root).resolve()
    pending = {}
    try:
        for part in records:
            source = Path(str(getattr(part, "file", "")).removeprefix("file:///")).resolve()
            owned = None
            if source.is_file() and source.is_relative_to(root):
                descriptor, name = tempfile.mkstemp(prefix="fatfish-delivery-", suffix=source.suffix, dir=root)
                os.close(descriptor)
                owned = Path(name)
                pending[id(part)] = owned
                shutil.copyfile(source, owned)
                part.file = str(owned)
                if hasattr(part, "url"):
                    part.url = str(owned)
                if hasattr(part, "path"):
                    part.path = str(owned)
            pending[id(part)] = owned
    except Exception:
        _cleanup(pending.values(), root)
        raise
    original_send = event.send
    announced = False
    fallback_sent = False

    async def send(message, *args, **kwargs):
        nonlocal announced, fallback_sent
        matched = [part for part in message.chain if id(part) in pending]
        if not matched:
            return await original_send(message, *args, **kwargs)
        remainder = [part for part in message.chain if id(part) not in pending]
        last = None
        try:
            for record in matched:
                try:
                    if not event.is_private_chat() and not announced:
                        await original_send(message.derive([Plain("AI合成角色语音")]), *args, **kwargs)
                        announced = True
                    last = await original_send(message.derive([record]), *args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOG.warning("QQ voice delivery failed: %s", type(exc).__name__)
                    if fallback and not alongside and not fallback_sent:
                        last = await original_send(message.derive([Plain(text)]), *args, **kwargs)
                        fallback_sent = True
            if remainder:
                last = await original_send(message.derive(remainder), *args, **kwargs)
            return last
        finally:
            _cleanup([pending.pop(id(record)) for record in matched], root)
            if not pending:
                event.send = original_send

    event.send = send


def guarded_result(function):
    """Decorate the community router's existing final-result hook."""
    @wraps(function)
    async def wrapped(router, event, *args, **kwargs):
        result = event.get_result()
        if not result or not result.is_llm_result():
            return await function(router, event, *args, **kwargs)
        original = list(result.chain)
        if any(type(part).__name__ == "Record" for part in original):
            return
        text = " ".join(part.text.strip() for part in original if type(part).__name__ == "Plain" and part.text.strip())
        cfg = policy(router)
        incoming = str(event.message_str or "")
        if VOICE_OPT_OUT.search(incoming):
            return
        manual = bool(cfg["manual_trigger"] and MANUAL_REQUEST.search(incoming))
        if not await _allowed(router, event, text, manual=manual):
            return
        if not manual and float(cfg["voice_probability"]) <= 0:
            return
        if not _reserve(router, event):
            return
        event._fatfish_manual_voice = manual
        try:
            _sync_native_limits(router)
            await function(router, event, *args, **kwargs)
            from astrbot.core.message.components import Plain
            from importlib import import_module
            root = import_module(router.__class__.__module__.rsplit(".", 1)[0] + ".core.constants").TEMP_DIR
            records = [part for part in result.chain if type(part).__name__ == "Record"]
            if records:
                others = [part for part in original if type(part).__name__ != "Plain"]
                result.chain = ([Plain(text)] if cfg["text_alongside_voice"] else []) + records + others
                protect_delivery(event, result.chain, text, root=root,
                                 alongside=cfg["text_alongside_voice"], fallback=cfg["fallback_to_text"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("TTS policy kept the original text: %s", type(exc).__name__)
            result.chain = original
        finally:
            event._fatfish_manual_voice = False
            _release(router, event)
    return wrapped


def guarded_manual(function):
    """Apply the same offline/length/cooldown gates to existing /tts commands."""
    @wraps(function)
    async def wrapped(router, event, text, *args, **kwargs):
        if not await _allowed(router, event, text, manual=True):
            return False, [], "当前语音策略未允许此请求，保留文字"
        if not _reserve(router, event):
            return False, [], "已有语音正在处理，保留文字"
        try:
            _sync_native_limits(router)
            state = router._get_session_state(router._get_umo(event))
            check = router.condition_checker.check_all(text, state, enable_probability=False)
            if not check.passed:
                return False, [], "语音冷却或长度限制中，保留文字"
            ok, chain, history = await function(router, event, text, *args, **kwargs)
            if ok:
                from importlib import import_module
                from astrbot.core.message.components import Plain
                root = import_module(router.__class__.__module__.rsplit(".", 1)[0] + ".core.constants").TEMP_DIR
                cfg = policy(router)
                chain = ([Plain(text)] if cfg["text_alongside_voice"] else []) + [part for part in chain if type(part).__name__ != "Plain"]
                protect_delivery(event, chain, text, root=root, alongside=cfg["text_alongside_voice"], fallback=cfg["fallback_to_text"])
            return ok, chain, history
        finally:
            _release(router, event)
    return wrapped
