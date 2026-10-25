"""Progressive probability around the existing meme_manager send lifecycle."""
from functools import wraps
import random

from .progressive_probability import MissCounters, progressive_probability

STATE = "_fatfish_meme_probability_state"


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
    state = {"key":key, "hit":random.random() < chance, "probability":chance,
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


def progressive_response(function):
    @wraps(function)
    async def wrapped(plugin, event, response, *args, **kwargs):
        state = None
        if plugin._scope_allows_llm_origin(event) and response and response.completion_text:
            state = _state(plugin, event)
        result = await function(plugin, event, response, *args, **kwargs)
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
