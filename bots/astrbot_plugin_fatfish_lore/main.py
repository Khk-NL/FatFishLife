"""AstrBot plugin: keyword-retrieval lore for 苹果乐, no embedding required."""

from __future__ import annotations

import re
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

DEFAULT_PATH = "D:/Code/Projects/FatFishLife/docs/persona/apple-le-full.md"


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _grams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[index : index + 2] for index in range(len(cleaned) - 1) if _is_cjk(cleaned[index]) or _is_cjk(cleaned[index + 1])}


def _sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^##\s+", text)
    result: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        title, _, body = part.partition("\n")
        result.append((title.strip(), body.strip()))
    return result


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.path = Path(str(self.config.get("lore_path") or DEFAULT_PATH))
        self.max_chars = max(300, int(self.config.get("max_chars", 1800)))
        self.sections = self._load()
        logger.info(f"fatfish lore ready: {self.path} ({len(self.sections)} sections)")

    def _load(self) -> list[tuple[str, str]]:
        try:
            return _sections(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning(f"读取设定库失败：{exc}")
            return []

    def _search(self, query: str, limit: int = 2) -> list[tuple[str, str]]:
        if not self.sections:
            return []
        if not query.strip():
            return self.sections[:limit]
        query_grams = _grams(query)
        scored = []
        for title, body in self.sections:
            if query in title:
                scored.append((1000, title, body))
                continue
            if query in body:
                scored.append((100 + body.count(query) * 5, title, body))
                continue
            score = sum(body.count(gram) + title.count(gram) * 3 for gram in query_grams)
            if score:
                scored.append((score, title, body))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [(title, body) for _, title, body in scored[:limit]]

    def _render(self, matches: list[tuple[str, str]]) -> str:
        if not matches:
            return "设定库里没有找到这部分，先不编。"
        blocks = []
        remaining = self.max_chars
        for title, body in matches:
            block = f"【{title}】\n{body}"
            if len(block) > remaining:
                block = block[:remaining].rstrip() + "…"
            blocks.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        return "\n\n".join(blocks)

    @filter.command("设定")
    async def lore(self, event: AstrMessageEvent, text: GreedyStr = GreedyStr("")):
        query = str(text or "").strip()
        if query in ("目录", "列表", "list"):
            yield event.plain_result("设定库目录：\n" + "\n".join(f"- {title}" for title, _ in self.sections))
            return
        if not query:
            yield event.plain_result("用法：/设定 <关键词>，或 /设定 目录")
            return
        yield event.plain_result(self._render(self._search(query)))

    @filter.llm_tool(name="lore_lookup")
    async def lore_lookup(self, event: AstrMessageEvent, topic: str):
        """查询苹果乐的设定库：世界观、人物关系、过往经历、对话示例。

        Args:
            topic(string): 想了解的主题或关键词
        """
        matches = self._search(topic, limit=2)
        yield event.plain_result(self._render(matches))

    async def terminate(self) -> None:
        logger.info("fatfish lore stopped")
