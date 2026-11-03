"""Exercise installation rollback without touching QQ, tasks or the network."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.version_guard import replace_installation


class VersionGuardTests(unittest.TestCase):
    def make_install(self, root):
        home, incoming = root / 'NapCat', root / 'incoming'
        (home / 'config').mkdir(parents=True)
        incoming.mkdir()
        (home / 'napcat.mjs').write_text('old', encoding='utf-8')
        (home / 'config' / 'settings.json').write_text('local settings', encoding='utf-8')
        (incoming / 'napcat.mjs').write_text('new', encoding='utf-8')
        return home, incoming

    def test_complete_swap_preserves_config_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            home, incoming = self.make_install(Path(folder))
            backup = replace_installation(incoming, home)
            self.assertEqual((home / 'napcat.mjs').read_text(), 'new')
            self.assertEqual((home / 'config/settings.json').read_text(), 'local settings')
            self.assertEqual((backup / 'napcat.mjs').read_text(), 'old')

    def test_failed_stage_does_not_move_the_original(self):
        with tempfile.TemporaryDirectory() as folder:
            home, incoming = self.make_install(Path(folder))
            with patch('scripts.version_guard.shutil.copytree', side_effect=OSError('copy failed')):
                with self.assertRaisesRegex(OSError, 'copy failed'):
                    replace_installation(incoming, home)
            self.assertEqual((home / 'napcat.mjs').read_text(), 'old')
            self.assertEqual(list(home.parent.glob('NapCat.new-*')), [])

    def test_failed_swap_restores_original_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            home, incoming = self.make_install(Path(folder))
            rename = Path.rename

            def fail_stage(source, target):
                if '.new-' in source.name:
                    raise OSError('swap failed')
                return rename(source, target)

            with patch.object(Path, 'rename', fail_stage):
                with self.assertRaisesRegex(OSError, 'swap failed'):
                    replace_installation(incoming, home)
            self.assertEqual((home / 'napcat.mjs').read_text(), 'old')
            self.assertEqual((home / 'config/settings.json').read_text(), 'local settings')
            self.assertEqual(list(home.parent.glob('NapCat.new-*')), [])
