"""Local archive installation must preserve upstream integrity and licensing."""
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.prepare_dsh_onebot import pack, replace


class DshPrepareTests(unittest.TestCase):
    def test_archive_is_separate_from_pinned_upstream_and_has_runtime_and_license(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "dsh-onebot-qq-0.9.6.tgz"
            original.write_bytes(b"immutable-pinned-upstream")
            package = root / "prepared-onebot"
            package.mkdir()
            for name in ("package.json", "cordis.patch.yml", "LICENSE", "README.md", "README.en.md"):
                (package / name).write_text(name, encoding="utf-8")
            (package / "lib").mkdir()
            (package / "lib/policy.mjs").write_text("export const policy = true;", encoding="utf-8")
            (package / ".env").write_text("TEST_ONLY=must-not-be-packed", encoding="utf-8")
            archive = pack(package)
            self.assertNotEqual(archive, original)
            self.assertEqual(original.read_bytes(), b"immutable-pinned-upstream")
            with tarfile.open(archive) as bundle:
                names = bundle.getnames()
                self.assertIn("package/LICENSE", names)
                self.assertIn("package/lib/policy.mjs", names)
                self.assertNotIn("package/.env", names)

    def test_unexpected_upstream_does_not_get_silently_patched(self):
        with self.assertRaises(RuntimeError):
            replace("different upstream source", "expected", "new")
        with self.assertRaises(RuntimeError):
            replace("expected expected", "expected", "new")
