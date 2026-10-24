import importlib.util
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location("migrate_meme_metadata", Path(__file__).resolve().parents[1] / "scripts/migrate_meme_metadata.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MigrationTests(unittest.TestCase):
    def test_existing_captions_kept_and_missing_file_records_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory)
            folder = pack / "memes/收藏"
            folder.mkdir(parents=True)
            (folder / "test.png").write_bytes(b"image bytes")
            old = {"schema_version": 1, "images": {
                "收藏/test.png": {"caption": "开心", "tags": ["笑"]},
                "收藏/removed.png": {"caption": "已移除"},
            }}
            result = module.normalize_legacy(old, pack)
            record = next(iter(result["images"].values()))
            self.assertEqual(len(result["images"]), 1)
            self.assertEqual(record["caption"], "开心")
            self.assertEqual(record["relative_path"], "memes/收藏/test.png")
            self.assertEqual(len(record["content_sha256"]), 64)
            self.assertEqual(len(old["images"]), 2)

    def test_path_escape_and_unsupported_schema_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                module.normalize_legacy({"schema_version": 1, "images": {"../../outside.png": {}}}, Path(directory))
            with self.assertRaises(ValueError):
                module.normalize_legacy({"schema_version": "2.0", "images": {}}, Path(directory))
