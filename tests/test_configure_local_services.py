import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("configure_local_services", Path(__file__).parents[1] / "scripts/configure_local_services.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigureLocalServicesTest(unittest.TestCase):
    def test_explicit_apply_preserves_pixiv_and_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            (data / "config").mkdir(parents=True)
            fixtures = {
                "cmd_config.json": {"provider_sources": [{"provider": "deepseek"}, {"provider": "siliconflow", "provider_type": "embedding"}],
                                    "provider": [{"id": "siliconflow_stt"}], "unrelated": 123},
                "config/astrbot_plugin_anysearch_config.json": {"api_key": "", "unrelated": True},
                "config/astrbot_plugin_fatfish_bili_config.json": {"dry_run_writes": True},
                "config/astrbot_plugin_tts_emotion_router_config.json": {"tts_engine": {"siliconflow": {}}, "feature_policies": {"preserve": True}},
                "config/astrbot_plugin_pixiv_search_config.json": {"refresh_token": "existing-test-token"},
            }
            for name, obj in fixtures.items():
                (data / name).write_text(json.dumps(obj), encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text('FATFISH_DEEPSEEK_KEY="test-deepseek"\nFATFISH_SILICONFLOW_KEY=test-silicon\nFATFISH_ANYSEARCH_KEY=test-any\nFATFISH_BILI_OWNER_UID=123\nFATFISH_STUDY_TAGS=music,game\nFATFISH_PIXIV_REFRESH_TOKEN=must-not-replace\n', encoding="utf-8")
            pixiv_before = (data / "config/astrbot_plugin_pixiv_search_config.json").read_bytes()
            preview = MODULE.configure(env_file, root)
            self.assertFalse(preview["applied"])
            self.assertEqual(json.loads((data / "cmd_config.json").read_text())["provider_sources"][0], {"provider": "deepseek"})
            result = MODULE.configure(env_file, root, apply=True)
            self.assertTrue(result["backup_created"])
            self.assertNotIn("test-deepseek", json.dumps(result))
            self.assertEqual((data / "config/astrbot_plugin_pixiv_search_config.json").read_bytes(), pixiv_before)
            main = json.loads((data / "cmd_config.json").read_text())
            self.assertEqual(main["unrelated"], 123)
            self.assertEqual(main["provider_sources"][0]["key"], ["test-deepseek"])
            self.assertTrue(json.loads((data / "config/astrbot_plugin_fatfish_bili_config.json").read_text())["dry_run_writes"])
            self.assertEqual(MODULE.configure(env_file, root, apply=True)["changed_files"], [])


if __name__ == "__main__":
    unittest.main()
