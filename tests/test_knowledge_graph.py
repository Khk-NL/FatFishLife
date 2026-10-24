import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from fatfish_core.knowledge_graph import KnowledgeGraph
from fatfish_core.graph_build import build_graph, file_documents, sanitize_document


TEXT = "能天使和德克萨斯是企鹅物流的成员。蕾缪安是能天使的姐姐。"
DATA = {"entities": [{"name": name, "type": kind} for name, kind in [("能天使", "人物"), ("企鹅物流", "组织"), ("蕾缪安", "人物")]],
        "relations": [{"subject": "能天使", "predicate": "所属组织", "object": "企鹅物流", "evidence": "能天使和德克萨斯是企鹅物流的成员", "confidence": .95},
                      {"subject": "能天使", "predicate": "姐姐", "object": "蕾缪安", "evidence": "蕾缪安是能天使的姐姐", "confidence": 1}]}


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.graph = KnowledgeGraph(Path(self.temp.name) / "memory.db")

    def test_query_returns_relationship_and_original_source(self):
        self.graph.replace("lore", "relations.md", "关系资料", TEXT, DATA, source_url="https://prts.wiki/w/能天使")
        rows = self.graph.query("能天使的姐姐是谁")
        self.assertEqual(rows[0]["object"], "蕾缪安")
        self.assertEqual(rows[0]["source"], "relations.md")
        self.assertIn("prts.wiki", rows[0]["source_url"])

    def test_private_graph_cannot_leak_via_public_query_or_alias(self):
        self.graph.replace("private_obsidian", "private.md", "私人笔记", TEXT, DATA)
        self.assertEqual(self.graph.query("能天使"), [])
        self.assertTrue(self.graph.query("能天使", collection="private_obsidian"))

    def test_requested_relation_is_ranked_before_high_confidence_unrelated_facts(self):
        self.graph.replace("lore", "family", "家人", TEXT, DATA)
        for index in range(40):
            other = f"地点{index}"
            text = f"能天使去过{other}。"
            self.graph.replace("lore", str(index), "旅行", text,
                {"entities": [{"name":"能天使","type":"人物"},{"name":other,"type":"地点"}],
                 "relations":[{"subject":"能天使","predicate":"去过","object":other,"evidence":text,"confidence":1}]})
        self.assertEqual(self.graph.query("能天使的姐姐是谁", limit=1)[0]["object"], "蕾缪安")

    def test_conflicting_family_directions_require_explicit_source(self):
        data = {**DATA, "relations": [DATA["relations"][1], {**DATA["relations"][1],
                "subject":"蕾缪安", "object":"能天使"}]}
        self.graph.replace("lore", "family", "家人", TEXT, data)
        rows = self.graph.query("能天使的姐姐是谁")
        self.assertEqual([(r["subject"],r["object"]) for r in rows], [("能天使","蕾缪安")])

    def test_missing_evidence_rejects_model_hallucination_and_preserves_old_graph(self):
        self.graph.replace("lore", "relations.md", "资料", TEXT, DATA)
        bad = {**DATA, "relations": [{**DATA["relations"][0], "evidence": "原文没有出现的事"}]}
        with self.assertRaises(ValueError):self.graph.replace("lore", "relations.md", "资料", TEXT + "变化", bad)
        self.assertEqual(self.graph.stats()["relations"], 2)
        self.assertTrue(self.graph.current("lore", "relations.md", TEXT))

    def test_repeat_import_is_idempotent_and_update_removes_obsolete_claims(self):
        self.graph.replace("lore", "relations.md", "资料", TEXT, DATA)
        self.graph.replace("lore", "relations.md", "资料", TEXT, DATA)
        self.assertEqual(self.graph.stats()["relations"], 2)
        self.graph.replace("lore", "relations.md", "资料", TEXT, {**DATA, "relations": DATA["relations"][:1]})
        self.assertEqual(self.graph.stats()["relations"], 1)

    def test_source_credentials_are_not_sent_to_the_extractor(self):
        text = "人物说明\npassword=PRIVATE\napi_key: PRIVATE\n正常设定"
        clean = sanitize_document(text)
        self.assertNotIn("PRIVATE", clean)
        self.assertIn("正常设定", clean)

    def test_manifest_removes_deleted_chunks_without_touching_other_collection(self):
        for collection in ("lore", "private_obsidian"):
            self.graph.replace(collection, "removed#chunk-1", "资料", TEXT, DATA)
        self.graph.replace("lore", "kept#chunk-0", "资料", TEXT, DATA)
        self.assertEqual(self.graph.prune("lore", {"kept#chunk-0"}), 1)
        self.assertEqual(self.graph.stats()["documents"], 1)
        self.assertEqual(self.graph.stats(collection="private_obsidian")["documents"], 1)

    def test_activity_metadata_uses_exact_document_entities_without_model_guesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "07-活动梗概.md").write_text("## 喧闹法则\n\n- 登场：能天使、德克萨斯\n- 梗概：参与龙门事件。\n", encoding="utf-8")
            docs = list(file_documents(root, "lore"))
            self.assertEqual(len(docs), 1)
            self.assertEqual(len(docs[0]["structured"]["relations"]), 2)
            self.graph.replace("lore", docs[0]["source"], docs[0]["title"], docs[0]["text"], docs[0]["structured"])
            self.assertTrue(self.graph.query("能天使参与过什么事件"))


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_extraction_is_reported_and_unchanged_sources_do_not_call_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = KnowledgeGraph(Path(tmp) / "memory.db")
            graph.replace("lore", "known", "资料", TEXT, DATA)
            docs = [{"collection": "lore", "source": "known", "title": "资料", "text": TEXT},
                    {"collection": "lore", "source": "new", "title": "新资料", "text": "其他资料"}]
            model = AsyncMock(side_effect=TimeoutError())
            report = await build_graph(graph, docs, model)
            self.assertEqual(report["unchanged"], 1)
            self.assertEqual(report["failed"], 1)
            self.assertEqual(model.await_count, 1)


if __name__ == "__main__": unittest.main()
