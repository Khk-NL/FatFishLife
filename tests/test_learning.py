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

    def test_save_style_writes_public_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            count = save_style(store, ["打什么本", "随便聊聊"])
            self.assertEqual(count, 2)
            rows = store.recall("群友最近常这样说", scopes=("public",), limit=5)
            self.assertTrue(any("打什么本" in row["content"] for row in rows))


if __name__ == "__main__":
    unittest.main()
