import json
from pathlib import Path
import tempfile
import unittest

from scripts.plan_dsh_channels import channel_plan, initialize


class ChannelProfilesTest(unittest.TestCase):
    def test_qq_transports_use_same_bundle_and_are_mutually_exclusive(self):
        for name in ("qqbot", "napcat", "snowluma"):
            self.assertEqual(channel_plan([name])[name]["bundle"], "dsh-onebot-qq")
        with self.assertRaises(ValueError):
            channel_plan(["qqbot", "napcat"])
        with self.assertRaises(ValueError):
            channel_plan(["wechat", "wechat"])

    def test_only_selected_channels_and_local_only_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "new"
            profile = initialize(home, channel_plan(["wechat", "bilibili"]), mcp_python=Path("/test/python"))
            rows = json.loads((profile / "cordis.patch.yml").read_text(encoding="utf-8"))
            plugins = {row["id"]: row for row in rows if "id" in row}
            self.assertEqual(set(plugins), {"dsh-wechat", "dsh-bili-whale"})
            self.assertTrue(all(row["disabled"] for row in plugins.values()))
            self.assertFalse(plugins["dsh-wechat"]["config"]["autoLogin"])
            presets = {row["id"]: row["config"] for row in rows[-1]["insert"]}
            self.assertEqual(presets["whale-local"]["plugins"][-1]["id"], "fatfish-memory")
            self.assertEqual(len(presets["whale-social"]["plugins"]), 1)
            self.assertEqual(presets["whale-social"]["plugins"][0]["config"]["channel"], "wechat")
            with self.assertRaises(FileExistsError):
                initialize(home, channel_plan(["qqbot"]))

    def test_official_account_stub_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "new"
            initialize(home, channel_plan(["qqbot"]))
            config = json.loads((home / "official-qq.json").read_text(encoding="utf-8"))
            self.assertFalse(config["enabled"])
            self.assertEqual(config["appSecret"], "")
