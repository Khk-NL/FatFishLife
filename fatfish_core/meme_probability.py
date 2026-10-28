"""Progressive probability around the existing meme_manager send lifecycle."""
from functools import wraps
import logging
import random
import re

from .progressive_probability import MissCounters, progressive_probability

STATE = "_fatfish_meme_probability_state"
LOG = logging.getLogger(__name__)
from .media_intent import MEME_REQUEST as MANUAL_REQUEST, MEME_OPT_OUT


def _manual_requested(plugin, event):
    text = str(getattr(event, "message_str", "") or "")
    enabled = plugin._read_config_value(("generation", "emotion", "manual_trigger"), default=True)
    return bool(enabled and not MEME_OPT_OUT.search(text) and MANUAL_REQUEST.search(text))


def _counts(plugin):
    counts = getattr(plugin, "_fatfish_meme_counts", None)
    if counts is None:
        counts = plugin._fatfish_meme_counts = MissCounters()
    return counts


def _state(plugin, event):
    key = str(getattr(event, "unified_msg_origin", "") or "")
    if not key:
        return None
    state = getattr(event, STATE, None)
    if state is not None:
        return state
    read = plugin._read_config_value
    base = float(read(("generation", "emotion", "probability"), default=plugin.emotions_probability))
    step = float(read(("generation", "emotion", "probability_step"), default=10))
    ceiling = float(read(("generation", "emotion", "probability_max"), default=90))
    chance = progressive_probability(base / 100, step / 100, _counts(plugin).get(key), ceiling=ceiling / 100)
    manual = _manual_requested(plugin, event)
    state = {"key":key, "hit":manual or random.random() < chance, "probability":chance, "manual":manual,
             "sent":False, "finished":False, "replied":False, "image_ids":set()}
    setattr(event, STATE, state)
    _observe_send(plugin, event, state)
    return state


def meme_probability_hit(plugin, event):
    state = _state(plugin, event)
    return bool(state and state["hit"])


def _sent(plugin, state):
    if not state["sent"]:
        _counts(plugin).record(state["key"], sent=True)
        state["sent"] = True
    state["replied"] = True


def _observe_send(plugin, event, state):
    original = getattr(event, "send", None)
    if not callable(original):
        return
    async def send(message, *args, **kwargs):
        result = await original(message, *args, **kwargs)
        if result is not False:
            state["replied"] = True
            if any(id(part) in state["image_ids"] for part in getattr(message, "chain", ())):
                _sent(plugin, state)
        return result
    state["original_send"], state["send_wrapper"] = original, send
    event.send = send


def _finish(plugin, event):
    state = getattr(event, STATE, None)
    if not state or state["finished"]:
        return
    if not state["sent"]:
        _counts(plugin).record(state["key"], sent=False)
    state["finished"] = True
    if getattr(event, "send", None) is state.get("send_wrapper"):
        event.send = state["original_send"]


def _images(parts):
    return {id(part) for part in parts if type(part).__name__ == "Image"}


def _clear_selection(event):
    for key in ("meme_manager_semantic_selected_ids", "found_emotions", "meme_manager_pending_images"):
        event.set_extra(key, [])


async def _complete_manual_selection(plugin, event, response, state):
    """Use the community tool once if an explicit request got text only.

    Candidate validity, pack scope, score threshold and image delivery remain
    upstream responsibilities. Never search from a plain/offline result or
    invent an image ID when the active tool has no suitable candidate.
    """
    if not state or not state["manual"]:
        return
    if not plugin._scope_allows_llm_origin(event):
        return
    if (not callable(getattr(plugin, "_semantic_mode_active", None))
            or not plugin._semantic_mode_active(event)
            or event.get_extra("meme_manager_semantic_mode") != "tool"):
        return
    if event.get_extra("meme_manager_semantic_selected_ids") or event.get_extra("found_emotions"):
        return
    try:
        if not event.get_extra("meme_manager_semantic_search_completed"):
            await plugin.search_memes_tool(event, str(getattr(event, "message_str", "") or "")[:160])
        candidates = event.get_extra("meme_manager_semantic_candidates") or {}
        candidates = [value for value in candidates.values() if isinstance(value, dict) and value.get("id")]
        if not candidates:
            return
        selected = max(candidates, key=lambda item: float(item.get("score") or 0))
        text = str(response.completion_text or "").rstrip()
        await plugin._resp_semantic_impl(event, response, text + "\n&&" + selected["id"] + "&&")
    except Exception as exc:
        LOG.warning("Manual meme selection kept the original reply: %s", type(exc).__name__)


def progressive_response(function):
    @wraps(function)
    async def wrapped(plugin, event, response, *args, **kwargs):
        state = None
        if plugin._scope_allows_llm_origin(event) and response and response.completion_text:
            state = _state(plugin, event)
        result = await function(plugin, event, response, *args, **kwargs)
        await _complete_manual_selection(plugin, event, response, state)
        if state and not state["hit"]:
            _clear_selection(event)
        return result
    return wrapped


def progressive_decorate(function):
    @wraps(function)
    async def wrapped(plugin, event, *args, **kwargs):
        result = event.get_result()
        state = getattr(event, STATE, None)
        if state is None and plugin._should_attach_for_result(event, result):
            state = _state(plugin, event)
        before = _images(getattr(result, "chain", ()) or ())
        if state and not state["hit"]:
            _clear_selection(event)
        answer = await function(plugin, event, *args, **kwargs)
        if state:
            state["image_ids"].update(_images(getattr(event.get_result(), "chain", ()) or ()) - before)
            state["image_ids"].update(_images(event.get_extra("meme_manager_pending_images") or ()))
        return answer
    return wrapped


def progressive_after_sent(function):
    @wraps(function)
    async def wrapped(plugin, event, *args, **kwargs):
        try:
            return await function(plugin, event, *args, **kwargs)
        finally:
            # AstrBot calls this only after a real outgoing reply; absent images
            # and failed pending images count as one miss, never one success.
            _finish(plugin, event)
    return wrapped


def progressive_image_send(function):
    @wraps(function)
    async def wrapped(plugin, event, image, *args, **kwargs):
        state = _state(plugin, event)
        if not state or not state["hit"]:
            return False
        result = await function(plugin, event, image, *args, **kwargs)
        if result is not False:
            _sent(plugin, state)
        return result
    return wrapped


def progressive_compat_send(function):
    @wraps(function)
    async def wrapped(plugin, event, prepared, *args, **kwargs):
        state = _state(plugin, event)
        if state:
            state["image_ids"].update(_images(prepared.get("images") or ()))
        try:
            return await function(plugin, event, prepared, *args, **kwargs)
        finally:
            if state and state["replied"]:
                _finish(plugin, event)
    return wrapped
