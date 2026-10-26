"""Thin policy/delivery adapters for the installed MIT TTS Emotion Router.

The community plugin owns synthesis, emotion, cooldown, probability and history.
These wrappers only gate that work and protect this event's existing sender.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import wraps
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from .progressive_probability import MissCounters, progressive_probability

LOG = logging.getLogger(__name__)
DEFAULT_POLICY = {
    "enabled": False, "voice_probability": .10, "voice_probability_step": 0.0,
    "voice_probability_max": 1.0, "cooldown_seconds": 180,
    "max_text_length": 80, "manual_trigger": True, "fallback_to_text": True,
    "text_alongside_voice": False, "disable_during_economy_mode": True,
}
MANUAL_REQUEST = re.compile(r"(?:用|发|来|转|说|读).{0,8}(?:语音|声音)|(?:语音|声音).{0,8}(?:说|读|回复|回答|来|发)|念(?:一下|一遍|给我听)|读给我听|^\s*(?:语音|声音)(?:呢|呀|啊|来一个|来一条)?[？?！!。\s]*$")
VOICE_OPT_OUT = re.compile(r"(?:别|不要|不用|不必|不想|禁止).{0,4}(?:语音|声音)|(?:用文字|打字回复|文字就好)")
_CURRENT_PROBABILITY = ContextVar("fatfish_voice_probability", default=None)
_CURRENT_MANUAL = ContextVar("fatfish_manual_voice", default=False)


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


async def _blocked_reason(router, event, text, *, manual=False):
    cfg = policy(router)
    if not cfg["enabled"] or not str(event.unified_msg_origin or ""):
        return "语音开关未开启"
    if not router.config.is_voice_output_enabled_for_umo(str(event.unified_msg_origin)):
        return "当前会话没有开启语音"
    if not str(event.get_platform_name()).startswith(("aiocqhttp", "qq_official")):
        return "当前平台不支持这条QQ语音路径"
    if not text.strip() or len(text) > int(cfg["max_text_length"]):
        return f"回复为空或超过{int(cfg['max_text_length'])}字"
    if cfg["disable_during_economy_mode"] and _offline(router):
        return "现在处于节能离线时段"
    if manual and not cfg["manual_trigger"]:
        return "手动语音请求未开启"
    from astrbot.core.star.session_llm_manager import SessionServiceManager
    if not await SessionServiceManager.should_process_tts_request(event):
        return "当前会话的语音服务已关闭"
    return ""


async def _allowed(router, event, text, *, manual=False):
    return not await _blocked_reason(router, event, text, manual=manual)


def _manual_unavailable(router, event, result, text, reason):
    """Explicit requests must not silently claim voice was delivered."""
    reasons = getattr(router, "_recent_reasons", None)
    if reasons is not None:
        reasons[str(event.unified_msg_origin)] = (time.time(), reason)
    from astrbot.core.message.components import Plain
    result.chain = [Plain(text + "\n（这次未发语音：" + reason + "）")] + [part for part in result.chain if type(part).__name__ != "Plain"]


def _sync_native_limits(router):
    """Use the router's actual checker instead of adding another random roll."""
    cfg = policy(router)
    router.condition_checker.prob = max(0., min(1., float(cfg["voice_probability"])))
    router.condition_checker.cooldown = max(0, int(cfg["cooldown_seconds"]))
    router.condition_checker.text_limit = max(1, int(cfg["max_text_length"]))
    checker = router.condition_checker
    if not getattr(checker, "_fatfish_context_probability", False):
        original = checker.check_all
        def check_all(*args, **kwargs):
            probability = _CURRENT_PROBABILITY.get()
            manual = _CURRENT_MANUAL.get()
            if probability is None and not manual:
                return original(*args, **kwargs)
            previous = checker.prob
            minimum = getattr(checker, "text_min_limit", 0)
            if probability is not None:
                checker.prob = probability
            if manual:
                checker.text_min_limit = 0
            try:
                # The upstream checker is synchronous. Only it rolls, and
                # another task cannot observe the temporary value mid-call.
                return original(*args, **kwargs)
            finally:
                checker.prob = previous
                if manual:
                    checker.text_min_limit = minimum
        checker.check_all = check_all
        checker._fatfish_context_probability = True


def _voice_counters(router):
    counters = getattr(router, "_fatfish_voice_misses", None)
    if counters is None:
        counters = router._fatfish_voice_misses = MissCounters()
    return counters


def _effective_probability(router, event):
    cfg = policy(router)
    return progressive_probability(cfg["voice_probability"], cfg["voice_probability_step"],
                                   _voice_counters(router).get(str(event.unified_msg_origin)),
                                   ceiling=cfg["voice_probability_max"])


def _eligible(router, event, text, chain=()):
    state = router._get_session_state(router._get_umo(event))
    mixed = any(type(part).__name__ not in {"Plain", "At", "Reply", "Image", "Face"} for part in chain)
    return router.condition_checker.check_all(text, state, mixed, enable_probability=False)


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


def protect_delivery(event, chain, text, *, root, alongside=False, fallback=True, on_success=None,
                     raise_on_failure=False):
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
    success_recorded = False

    async def send(message, *args, **kwargs):
        nonlocal announced, fallback_sent, success_recorded
        matched = [part for part in message.chain if id(part) in pending]
        if not matched:
            return await original_send(message, *args, **kwargs)
        remainder = [part for part in message.chain if id(part) not in pending]
        last = None
        delivery_failed = False
        try:
            for record in matched:
                try:
                    if not event.is_private_chat() and not announced:
                        announcement = await original_send(message.derive([Plain("AI合成角色语音")]), *args, **kwargs)
                        if announcement is False:
                            raise RuntimeError("QQ voice disclosure sender returned False")
                        announced = True
                    last = await original_send(message.derive([record]), *args, **kwargs)
                    if last is False:
                        raise RuntimeError("QQ voice sender returned False")
                    if on_success is not None and not success_recorded:
                        on_success()
                        success_recorded = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    delivery_failed = True
                    LOG.warning("QQ voice delivery failed: %s", type(exc).__name__)
                    if fallback and not alongside and not fallback_sent:
                        last = await original_send(message.derive([Plain(text)]), *args, **kwargs)
                        fallback_sent = True
            if remainder:
                last = await original_send(message.derive(remainder), *args, **kwargs)
            if delivery_failed and raise_on_failure:
                # Native manual/tool callers mark history and suppress the next
                # LLM result only when this send returns normally. A successful
                # text fallback must not masquerade as successful voice delivery.
                detail = "，已保留文字" if fallback_sent or (alongside and remainder) else ""
                raise RuntimeError("语音投递失败" + detail) from None
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
        blocked = await _blocked_reason(router, event, text, manual=manual)
        if blocked:
            if manual:
                _manual_unavailable(router, event, result, text, blocked)
            return
        if not manual and float(cfg["voice_probability"]) <= 0 and float(cfg["voice_probability_step"]) <= 0:
            return
        if not _reserve(router, event):
            if manual:
                _manual_unavailable(router, event, result, text, "已有语音正在处理")
            return
        event._fatfish_manual_voice = manual
        attempted = False
        token = None
        previous_reason = getattr(router, "_recent_reasons", {}).get(str(event.unified_msg_origin))
        manual_token = _CURRENT_MANUAL.set(manual)
        try:
            _sync_native_limits(router)
            eligibility = _eligible(router, event, text, original)
            if not eligibility.passed:
                if manual:
                    _manual_unavailable(router, event, result, text, "语音冷却或长度限制中")
                return
            counters = _voice_counters(router)
            key = str(event.unified_msg_origin)
            token = _CURRENT_PROBABILITY.set(_effective_probability(router, event))
            attempted = True
            await function(router, event, *args, **kwargs)
            from astrbot.core.message.components import Plain
            from importlib import import_module
            root = import_module(router.__class__.__module__.rsplit(".", 1)[0] + ".core.constants").TEMP_DIR
            records = [part for part in result.chain if type(part).__name__ == "Record"]
            if records:
                others = [part for part in original if type(part).__name__ != "Plain"]
                result.chain = ([Plain(text)] if cfg["text_alongside_voice"] else []) + records + others
                protect_delivery(event, result.chain, text, root=root,
                                 alongside=cfg["text_alongside_voice"], fallback=cfg["fallback_to_text"],
                                 on_success=lambda: counters.record(key, sent=True))
            elif manual:
                recent = getattr(router, "_recent_reasons", {}).get(str(event.unified_msg_origin))
                reason = recent[1] if recent and recent != previous_reason else "本次未生成语音，已保留文字"
                _manual_unavailable(router, event, result, text, reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("TTS policy kept the original text: %s", type(exc).__name__)
            result.chain = original
            if manual:
                _manual_unavailable(router, event, result, text, "语音服务暂时不可用，已保留文字")
        finally:
            if attempted:
                counters.record(key, sent=False)
            if token is not None:
                _CURRENT_PROBABILITY.reset(token)
            _CURRENT_MANUAL.reset(manual_token)
            event._fatfish_manual_voice = False
            _release(router, event)
    return wrapped


def guarded_manual(function):
    """Apply the same offline/length/cooldown gates to existing /tts commands."""
    @wraps(function)
    async def wrapped(router, event, text, *args, **kwargs):
        blocked = await _blocked_reason(router, event, text, manual=True)
        if blocked:
            return False, [], blocked + "，保留文字"
        if not _reserve(router, event):
            return False, [], "已有语音正在处理，保留文字"
        attempted = False
        manual_token = _CURRENT_MANUAL.set(True)
        try:
            _sync_native_limits(router)
            state = router._get_session_state(router._get_umo(event))
            check = router.condition_checker.check_all(text, state, enable_probability=False)
            if not check.passed:
                return False, [], "语音冷却或长度限制中，保留文字"
            counters = _voice_counters(router)
            key = str(event.unified_msg_origin)
            attempted = True
            ok, chain, history = await function(router, event, text, *args, **kwargs)
            if ok:
                from importlib import import_module
                from astrbot.core.message.components import Plain
                root = import_module(router.__class__.__module__.rsplit(".", 1)[0] + ".core.constants").TEMP_DIR
                cfg = policy(router)
                chain = ([Plain(text)] if cfg["text_alongside_voice"] else []) + [part for part in chain if type(part).__name__ != "Plain"]
                protect_delivery(event, chain, text, root=root, alongside=cfg["text_alongside_voice"], fallback=cfg["fallback_to_text"],
                                 on_success=lambda: counters.record(key, sent=True), raise_on_failure=True)
            return ok, chain, history
        finally:
            if attempted:
                counters.record(key, sent=False)
            _CURRENT_MANUAL.reset(manual_token)
            _release(router, event)
    return wrapped
