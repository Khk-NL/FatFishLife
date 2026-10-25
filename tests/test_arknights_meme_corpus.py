"""Curated community knowledge stays scoped, source-labeled and deterministic."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from fatfish_core.graph_build import build_graph, file_documents
from fatfish_core.knowledge_graph import KnowledgeGraph
from fatfish_core.prts_facts import structured_documents


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/knowledge/arknights-meme-encyclopedia.md"


class ArknightsMemeCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CORPUS.read_text(encoding="utf-8")
        cls.documents = list(structured_documents(cls.text, CORPUS.name, "lore"))

    def test_all_curated_entries_are_unique_and_reuse_the_existing_schema(self):
        self.assertEqual(len(self.documents), 82)
        self.assertEqual(len({doc["source"] for doc in self.documents}), 82)
        self.assertEqual(sum(len(doc["structured"]["relations"]) for doc in self.documents), 251)
        for doc in self.documents:
            self.assertEqual(doc["collection"], "lore")
            self.assertIn("用户", doc["text"])
            self.assertIn("不是官方设定", doc["text"])
            for relation in doc["structured"]["relations"]:
                self.assertIn(relation["evidence"], doc["text"])
                self.assertIn(relation["predicate"], {"社区含义", "使用边界", "资料性质", "社区讨论关联"})

    def test_numeric_scope_and_gameplay_identifiers_are_not_conflated(self):
        names = {doc["structured"]["relations"][0]["subject"] for doc in self.documents}
        self.assertEqual({name for name in names if name.isdigit()}, {"325", "799"})
        self.assertNotIn("42姐", names)
        self.assertIn("塞7", names)
        self.assertIn("一杯茶，一包烟，1-7刷一天", names)

    def test_corrections_and_ambiguous_terms_keep_their_boundaries(self):
        by_name = {doc["structured"]["relations"][0]["subject"]:doc for doc in self.documents}
        self.assertIn("艾雅法拉二技能", by_name["点燃杯"]["text"])
        self.assertIn("不是史尔特尔二技能", by_name["点燃杯"]["text"])
        self.assertIn("不是普适DPS", by_name["799"]["text"])
        self.assertIn("不按发色硬映射", by_name["红蒂、蓝蒂、白蒂"]["text"])
        self.assertIn("不是官方恋爱设定", by_name["驴外四女友"]["text"])
        self.assertIn("不是官方台词", by_name["给我玩明日方舟"]["text"])

    def test_import_and_alias_recall_need_no_model_and_keep_private_graph_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root / CORPUS.name).write_text(self.text, encoding="utf-8")
            graph=KnowledgeGraph(root / "graph.db")
            async def forbidden(*args):
                raise AssertionError("Curated structured memes must not invoke a model")
            result=asyncio.run(build_graph(graph, file_documents(root, "lore"), forbidden))
            self.assertEqual(result["processed"],82)
            self.assertEqual(result["failed"],0)
            self.assertEqual(result["relations"],251)
            self.assertIn("魔法Zc目录",graph.context("325是什么梗"))
            self.assertIn("提丰",graph.context("799是什么意思"))
            self.assertIn("艾雅法拉",graph.context("点燃杯"))
            self.assertIn("异客为什么是神",graph.context("客门"))
            self.assertIn("血狼破军",graph.context("血狼破军相关的梗"))
            self.assertIn("魔法Zc目录",graph.context("Zc"))
            self.assertEqual(graph.stats(collection="private_obsidian")["relations"],0)
            repeated=asyncio.run(build_graph(graph,file_documents(root,"lore"),forbidden))
            self.assertEqual(repeated["processed"],0)
            self.assertEqual(repeated["unchanged"],82)


if __name__ == "__main__":
    unittest.main()
