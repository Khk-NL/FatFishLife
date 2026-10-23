"""Compatibility import; shared persistence lives in fatfish_core."""

from fatfish_core.memory import MemoryStore, SCHEMA, now

__all__ = ["MemoryStore", "SCHEMA", "now"]
