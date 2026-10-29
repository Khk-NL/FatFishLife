import tempfile
import unittest
from pathlib import Path

from fatfish_core.learning import extract_terms, save_style
from fatfish_core.memory import MemoryStore


class LearningTest(unittest.TestCase):
    def test_extracts_repeated_phrase(self):
        texts = ["今天打什么本", "打什么本好", "打什么本带我一个", "随便聊聊"]
        terms = extract_terms(texts, min_count=2)
        self.assertIn("打什么本", terms)

    def test_ignores_stopwords(self):
        texts = ["这个真的可以", "这个真的可以", "这个真的可以"]
        terms = extract_terms(texts, min_count=2)
        self.assertNotIn("这个", terms)
        self.assertNotIn("真的", terms)

    def test_ignores_function_words_in_mixed_messages(self):
        # 真实群聊里"这个/什么"分散在不同消息中，不会被更长片段包含，
        # 必须靠词表挡掉，否则它们会长期占据 top 把梗挤出去。
        texts = [
            "这个不错啊", "什么情况这是", "这个我熟", "什么鬼东西", "这个真的行",
            "倒反天罡", "倒反天罡吧这", "离谱倒反天罡",
        ]
        terms = extract_terms(texts, min_count=2)
        self.assertNotIn("这个", terms)
        self.assertNotIn("什么", terms)
        self.assertTrue(any("倒反天罡" in term for term in terms), terms)

    def test_save_style_writes_public_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            count = save_style(store, ["打什么本", "随便聊聊"])
            self.assertEqual(count, 2)
            rows = store.recall("群友最近常这样说", scopes=("public",), limit=5)
            self.assertTrue(any("打什么本" in row["content"] for row in rows))


if __name__ == "__main__":
    unittest.main()
