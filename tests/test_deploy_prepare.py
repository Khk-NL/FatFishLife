from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from deploy.prepare import PLUGINS, ROOT, bundle, prepare

try:
    import yaml
except ImportError:
    yaml = None


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
            self.assertEqual(len(result["written"]), 9)
            config = destination / "astrbot/config/astrbot_plugin_fatfish_bili_config.json"
            bili = json.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(bili["dry_run_writes"])
            self.assertFalse(bili["auto_reply"])
            self.assertFalse(bili["enable_inbox_poll"])
            self.assertFalse(bili["owner_uid"])
            offline = json.loads((config.parent / "astrbot_plugin_fatfish_offline_config.json").read_text(encoding="utf-8"))
            self.assertFalse(offline["local_model_enabled"])
            life = json.loads((config.parent / "astrbot_plugin_fatfish_life_config.json").read_text(encoding="utf-8"))
            self.assertFalse(life["publish_enabled"])
            self.assertFalse(life["qq_bot_id"])
            obsidian = json.loads((config.parent / "astrbot_plugin_fatfish_obsidian_config.json").read_text(encoding="utf-8"))
            self.assertFalse(obsidian["enabled"])
            self.assertFalse(obsidian["vault_path"])
            self.assertFalse(obsidian["owner_ids"])
            self.assertEqual(obsidian["kb_name"], "FatFish-Obsidian-Private")
            story = json.loads((config.parent / "astrbot_plugin_fatfish_story_config.json").read_text(encoding="utf-8"))
            self.assertEqual((story["zone"], story["tid"]), (0, 0))
            self.assertFalse(story["owner_qq"])
            steam = json.loads((config.parent / "astrbot_plugin_fatfish_steam_config.json").read_text(encoding="utf-8"))
            self.assertEqual(steam, {"country": "cn", "proxy": ""})
            config.write_text("existing configuration", encoding="utf-8")
            repeated = prepare(state_dir=destination, write=True)
            self.assertEqual(repeated["written"], [])
            self.assertIn(config.name, repeated["preserved"])
            self.assertEqual(config.read_text(encoding="utf-8"), "existing configuration")

    def test_prepare_preserves_community_plugins_and_legacy_sticker_data(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state"
            for relative in ("astrbot/plugins/meme_manager/main.py", "astrbot/plugins/astrbot_plugin_proactive_chat/main.py",
                             "astrbot/plugin_data/astrbot_plugin_fatfish_stickers/library.json"):
                marker = destination / relative
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("preserve", encoding="utf-8")
            prepare(state_dir=destination, write=True)
            for marker in destination.rglob("main.py"):
                self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual((destination / "astrbot/plugin_data/astrbot_plugin_fatfish_stickers/library.json").read_text(), "preserve")

    @unittest.skipIf(yaml is None, "Compose static parsing needs PyYAML")
    def test_compose_preserves_community_directory_and_only_starts_two_services(self):
        compose = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(set(services), {"astrbot", "napcat"})
        targets = {volume.split(":")[1] for volume in services["astrbot"]["volumes"]}
        self.assertIn("/AstrBot/data", targets)
        self.assertNotIn("/AstrBot/data/plugins", targets)
        mounted_plugins = {target.rsplit("/", 1)[1] for target in targets if target.startswith("/AstrBot/data/plugins/")}
        self.assertEqual(mounted_plugins, set(PLUGINS))
        self.assertTrue({"astrbot_plugin_fatfish_life", "astrbot_plugin_fatfish_story",
                         "astrbot_plugin_fatfish_obsidian", "astrbot_plugin_fatfish_steam",
                         "astrbot_plugin_fatfish_voice"}.issubset(mounted_plugins))
        self.assertTrue(all(volume.endswith(":ro") for volume in services["astrbot"]["volumes"] if ":/AstrBot/data/plugins/" in volume))
        self.assertNotIn("astrbot_plugin_fatfish_stickers", mounted_plugins)

    def test_source_bundle_has_all_nine_plugins_without_credentials_runtime_or_legacy_stickers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy = root / "deploy"
            files = ["pyproject.toml", "deploy/Dockerfile", "deploy/Dockerfile.dockerignore", "deploy/compose.yaml",
                     "deploy/prepare.py", "deploy/README.md", "deploy/.env.example", "fatfish_core/__init__.py",
                     "fatfish_core/growth.py", "fatfish_core/steam.py", "fatfish_story/review.py",
                     "fatfish_video/web/app.js", "assets/photo.png", "examples/single.json", "docs/persona/apple-le-full.md",
                     "bots/astrbot_plugin_fatfish_life/publishers.py", "bots/astrbot_plugin_fatfish_obsidian/sync.py"]
            files.extend("bots/" + plugin + "/main.py" for plugin in PLUGINS)
            files.extend("deploy/config/" + plugin + "_config.json.example" for plugin in PLUGINS if not plugin.endswith("_voice"))
            excluded = ["deploy/.env", "deploy/state/astrbot/memory.db", "assets/.env", "assets/private.db",
                        "fatfish_core/__pycache__/state.pyc", "bots/astrbot_plugin_fatfish_life/__pycache__/main.pyc",
                        "bots/astrbot_plugin_fatfish_stickers/main.py", "deploy/config/private.json"]
            for relative in files + excluded:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")
            destination = root / "bundle.zip"
            with patch("deploy.prepare.ROOT", root), patch("deploy.prepare.DEPLOY", deploy):
                result = bundle(destination)
                self.assertFalse(result["runtime_data_included"])
                with zipfile.ZipFile(destination) as archive:
                    names = set(archive.namelist())
                    self.assertTrue(set(files).issubset(names))
                    self.assertFalse(set(excluded) & names)
                    manifest = json.loads(archive.read("deploy/bundle-manifest.json"))["sha256"]
                    self.assertEqual(set(manifest), set(files))
                    for name, digest in manifest.items():
                        self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
                before = destination.read_bytes()
                with self.assertRaises(FileExistsError):
                    bundle(destination)
                self.assertEqual(destination.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
