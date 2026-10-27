import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

spec = importlib.util.spec_from_file_location("dsh_baseline", Path(__file__).resolve().parents[1] / "scripts/dsh_migration_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class BaselineTests(unittest.TestCase):
    def test_wal_database_and_configuration_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "source"
            root.mkdir()
            (root / "settings.yaml").write_text("example: local-only\n", encoding="utf-8")
            (root / "cache").mkdir()
            (root / "cache/ignored").write_text("rebuildable")
            db = sqlite3.connect(root / "memory.db")
            try:
                db.execute("pragma journal_mode=WAL")
                db.execute("create table evidence(value text)")
                db.execute("insert into evidence values ('committed WAL evidence')")
                db.commit()
                backup = Path(folder) / "backup"
                report = baseline.snapshot({"local": root}, backup)
                self.assertTrue(report["complete"])
                self.assertEqual(len(report["files"]), 2)
                self.assertFalse((backup / "local/cache").exists())
                self.assertFalse((backup / "local/memory.db-wal").exists())
                with closing(sqlite3.connect(backup / "local/memory.db")) as restored:
                    self.assertEqual(restored.execute("select value from evidence").fetchone()[0], "committed WAL evidence")
                self.assertEqual((backup / "local/settings.yaml").read_bytes(), (root / "settings.yaml").read_bytes())
            finally:
                db.close()

    def test_never_overwrites_existing_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(FileExistsError):
                baseline.snapshot({"local": root}, root)
