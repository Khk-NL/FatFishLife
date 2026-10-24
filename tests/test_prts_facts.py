import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fatfish_core.graph_build import build_graph, file_documents
from fatfish_core.knowledge_graph import KnowledgeGraph
from fatfish_core.prts_facts import extract_page, markdown_document, structured_documents
from scripts.refresh_prts_facts import refresh


CHARACTER = '''<script>var card={"name":"能天使","group":"企鹅物流","class":"狙击","branch":"速射手"};</script>
<p>【代号】能天使<br>【出身地】拉特兰<br>【种族】萨科塔</p>'''


class PrtsFactTests(unittest.TestCase):
    def test_character_fields_are_from_the_named_card_and_archive(self):
        page = extract_page("能天使", CHARACTER, fetched_at="2026-10-24")
        facts = {(r["predicate"], r["object"]) for r in page["relations"]}
        self.assertIn(("游戏阵营", "企鹅物流"), facts)
        self.assertIn(("出身地", "拉特兰"), facts)
        self.assertIn(("种族", "萨科塔"), facts)
        self.assertNotIn(("所属组织", "企鹅物流"), facts)

    def test_undisclosed_race_is_not_guessed_from_appearance(self):
        html = CHARACTER.replace("能天使", "莫斯提马").replace("萨科塔", "未公开")
        page = extract_page("莫斯提马", html)
        self.assertFalse(any(r["predicate"] == "种族" for r in page["relations"]))
        self.assertTrue(any("未公开" in note for note in page["notes"]))

    def test_community_synthesis_is_labeled_in_graph_source(self):
        page = extract_page("泰拉大典:地理/龙门", "<p>龙门（Lungmen），炎国的移动城邦。</p>")
        self.assertIn("PRTS社区整理", page["title"])
        self.assertTrue(any("不是官方" in note for note in page["notes"]))

    def test_quote_in_structured_declaration_cannot_validate_itself(self):
        page = extract_page("能天使", CHARACTER)
        page["relations"][0]["evidence"] = "这句话不在原始证据片段里"
        page["relations"] = page["relations"][:1]
        document = next(structured_documents(markdown_document([page]), "facts.md", "lore"))
        with tempfile.TemporaryDirectory() as temp:
            graph = KnowledgeGraph(Path(temp) / "graph.db")
            with self.assertRaisesRegex(ValueError, "No source-supported"):
                graph.replace("lore", document["source"], document["title"], document["text"], document["structured"])

    def test_structured_import_uses_existing_validator_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "facts.md").write_text(markdown_document([extract_page("能天使", CHARACTER)]), encoding="utf-8")
            graph = KnowledgeGraph(root / "graph.db")
            async def forbidden(*args):
                raise AssertionError("Structured facts must not call a model")
            result = asyncio.run(build_graph(graph, file_documents(root, "lore"), forbidden))
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["relations"], 5)
            self.assertIn("企鹅物流", graph.context("能天使游戏阵营"))
            self.assertEqual(graph.stats(collection="private_obsidian")["relations"], 0)
            again = asyncio.run(build_graph(graph, file_documents(root, "lore"), forbidden))
            self.assertEqual(again["processed"], 0)

    def test_finite_refresh_reuses_cache_and_preserves_other_pages_and_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cache = root / "cache"; cache.mkdir()
            output, report = root / "facts.md", root / "report.json"
            old = extract_page("泰拉大典:地理/龙门", "<p>龙门（Lungmen），炎国的移动城邦。</p>", fetched_at="2026-10-23")
            output.write_text(markdown_document([old]), encoding="utf-8")
            import hashlib
            cached = cache / (hashlib.sha256("能天使".encode()).hexdigest() + ".json")
            cached.write_text(json.dumps({"title": "能天使", "html": CHARACTER, "revision": 123}), encoding="utf-8")
            result = refresh(cache, output, report, pages=["能天使"])
            self.assertEqual(result["completed"], 1)
            self.assertIn("龙门", output.read_text(encoding="utf-8"))
            before = output.read_text(encoding="utf-8")
            with patch("scripts.refresh_prts_facts.fetch_page", side_effect=TimeoutError):
                failed = refresh(cache, output, report, pages=["能天使"], force=True)
            self.assertEqual(failed["failed"], 1)
            self.assertEqual(failed["retained_previous_failed"], 1)
            self.assertEqual(output.read_text(encoding="utf-8"), before)
            with self.assertRaises(ValueError):
                refresh(cache, output, report, pages=["未知任意页面"])
