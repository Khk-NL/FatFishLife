import tempfile
import unittest
from pathlib import Path

from bots.astrbot_plugin_fatfish_stickers.library import StickerLibrary


class StickerLibraryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.library = StickerLibrary(self.base)
        self.sample = self.base / "sample.png"
        self.sample.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_owner_sticker_is_approved(self):
        item = self.library.add(self.sample, ["苹果乐", "开心"], approved=True)
        self.assertEqual(item["tags"], ["苹果乐", "开心"])
        self.assertIn(item["id"], self.library.approved())
        self.assertEqual(len(self.library.pending()), 0)

    def test_anonymous_sticker_waits_for_review(self):
        item = self.library.add(self.sample, ["未分类"], approved=False)
        self.assertIn(item["id"], self.library.pending())
        approved = self.library.approve(item["id"], ["能天使"])
        self.assertIsNotNone(approved)
        self.assertIn(item["id"], self.library.approved())
        self.assertEqual(approved["tags"], ["能天使"])

    def test_reject_removes_file(self):
        item = self.library.add(self.sample, ["随手拍"], approved=False)
        stored = self.library.path(item)
        self.assertTrue(stored.exists())
        self.assertTrue(self.library.reject(item["id"]))
        self.assertFalse(stored.exists())
        self.assertNotIn(item["id"], self.library.pending())

    def test_pick_by_keyword(self):
        self.library.add(self.sample, ["苹果乐"], approved=True)
        self.library.add(self.sample, ["德克萨斯"], approved=True)
        picked = self.library.pick("苹果")
        self.assertIsNotNone(picked)
        self.assertIn("苹果乐", picked[1]["tags"])
        self.assertIsNone(self.library.pick("不存在"))

    def test_reload_keeps_items(self):
        self.library.add(self.sample, ["苹果乐"], approved=True)
        reloaded = StickerLibrary(self.base)
        self.assertEqual(len(reloaded.approved()), 1)


if __name__ == "__main__":
    unittest.main()
