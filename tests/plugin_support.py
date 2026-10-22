"""Load plugin handlers for isolated tests without an installed AstrBot runtime."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch


def load_plugin(plugin_name: str, *, module_overrides: dict | None = None):
    plugins = Path(__file__).resolve().parent.parent / "bots"
    root = plugins / plugin_name
    modules = {
        name: types.ModuleType(name)
        for name in (
            "astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star", "astrbot.api.message_components", "astrbot.api.provider",
            "astrbot.core", "astrbot.core.star", "astrbot.core.star.filter",
            "astrbot.core.star.filter.command",
        )
    }

    def decorator(*args, **kwargs):
        return lambda function: function

    modules["astrbot.api"].logger = types.SimpleNamespace(info=lambda *args: None, warning=lambda *args: None)
    modules["astrbot.api.event"].AstrMessageEvent = object
    modules["astrbot.api.event"].filter = types.SimpleNamespace(
        EventMessageType=types.SimpleNamespace(ALL="all"),
        event_message_type=decorator, command=decorator, llm_tool=decorator, on_llm_request=decorator,
        after_message_sent=decorator,
    )
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = type("Star", (), {})
    modules["astrbot.api.star"].StarTools = object
    modules["astrbot.api.provider"].ProviderRequest = object
    modules["astrbot.core.star.filter.command"].GreedyStr = str
    modules["astrbot.api.message_components"].Image = types.SimpleNamespace(fromFileSystem=lambda path: path)
    modules["astrbot.api.message_components"].Plain = lambda text: text
    parent = types.ModuleType("_fatfish_plugin_test")
    parent.__path__ = [str(plugins)]
    modules[parent.__name__] = parent
    package = types.ModuleType(parent.__name__ + "." + plugin_name)
    package.__path__ = [str(root)]
    modules[package.__name__] = package
    name = package.__name__ + ".main"
    spec = importlib.util.spec_from_file_location(name, root / "main.py")
    module = importlib.util.module_from_spec(spec)
    modules.update(module_overrides or {})
    with patch.dict(sys.modules, modules):
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module
