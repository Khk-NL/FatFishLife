import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fatfish_core.runtime import resolve_shared_db


class SharedDbConfigTests(unittest.TestCase):
    def test_native_bom_config_loads_with_explicit_and_default_database(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            root = Path(temp)
            config = root / 'config/astrbot_plugin_fatfish_memory_config.json'
            config.parent.mkdir()
            expected = root / 'custom/memory.db'
            config.write_text(json.dumps({'db_path':str(expected)}), encoding='utf-8-sig')
            self.assertEqual(resolve_shared_db(root), expected)
            config.write_text('{}', encoding='utf-8-sig')
            self.assertEqual(resolve_shared_db(root), root/'plugin_data/astrbot_plugin_fatfish_memory/memory.db')
