import json
from pathlib import Path
import tempfile
import unittest

from scripts.merge_context_config import merge_context_config


class ContextConfigMergeTests(unittest.TestCase):
    def test_mapping_is_previewed_and_applied_without_overwriting_existing_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = root / 'config'; config.mkdir()
            source = config / 'astrbot_plugin_fatfish_context_config.json'
            target = config / 'astrbot_plugin_fatfish_memory_config.json'
            source.write_text(json.dumps({'enabled': False, 'image_history_turns': 2, 'max_current_images': 4,
                                           'monitor_interval_seconds': 1800, 'cost_warning_cny': 9}), encoding='utf-8')
            original = {'owner_ids': 'qq:private-owner-fixture', 'max_current_images': 3}
            target.write_text(json.dumps(original), encoding='utf-8')
            report = merge_context_config(root)
            self.assertTrue(report['changed']); self.assertFalse(report['applied'])
            self.assertEqual(json.loads(target.read_text()), original)
            self.assertFalse((root / 'private-config-backups').exists())
            applied = merge_context_config(root, apply=True)
            self.assertTrue(applied['backup_created'])
            saved = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(saved['owner_ids'], original['owner_ids'])
            self.assertEqual(saved['max_current_images'], 3)
            self.assertFalse(saved['context_hygiene_enabled'])
            self.assertNotIn('enabled', saved)
            self.assertEqual(saved['image_history_turns'], 2)
            self.assertEqual(saved['monitor_interval_seconds'], 1800)
            self.assertEqual(saved['cost_warning_cny'], 9)
            self.assertTrue(saved['cost_monitor_enabled'])
            self.assertNotIn(original['owner_ids'], str(applied))
            self.assertFalse(merge_context_config(root, apply=True)['changed'])

    def test_no_legacy_config_does_not_create_or_replace_memory_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = merge_context_config(root, apply=True)
            self.assertFalse(report['legacy_found'])
            self.assertFalse(report['changed'])
            self.assertEqual(list(root.iterdir()), [])
