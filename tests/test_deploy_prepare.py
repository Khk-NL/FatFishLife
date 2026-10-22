from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deploy.prepare import prepare


class DeploymentPreparationTests(unittest.TestCase):
    def test_default_check_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state"
            result = prepare(state_dir=destination)
            self.assertEqual(result["status"], "checked")
            self.assertFalse(result["services_started"])
            self.assertFalse(destination.exists())

    def test_write_uses_safe_defaults_and_never_overwrites_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state"
            result = prepare(state_dir=destination, write=True)
            self.assertEqual(len(result["written"]), 3)
            config = destination / "astrbot/config/astrbot_plugin_fatfish_bili_config.json"
            bili = json.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(bili["dry_run_writes"])
            self.assertFalse(bili["auto_reply"])
            self.assertFalse(bili["enable_inbox_poll"])
            self.assertFalse(bili["owner_uid"])
            config.write_text("existing configuration", encoding="utf-8")
            repeated = prepare(state_dir=destination, write=True)
            self.assertEqual(repeated["written"], [])
            self.assertIn(config.name, repeated["preserved"])
            self.assertEqual(config.read_text(encoding="utf-8"), "existing configuration")


if __name__ == "__main__":
    unittest.main()
