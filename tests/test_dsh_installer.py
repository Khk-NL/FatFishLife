"""Guard the installer script's encoding and QQ bridge configuration.

The .ps1 files in this repository mix UTF-16LE and UTF-8 on purpose. Windows
PowerShell 5.1 reads a UTF-8 file without a BOM as ANSI, which mangles the
Chinese strings and breaks quoting. Rewriting
`scripts/dsh_install_plugins.ps1` as UTF-8 has already broken it once, so the
encoding is asserted here.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/dsh_install_plugins.ps1"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.raw = INSTALLER.read_bytes()

    def test_script_keeps_windows_powershell_readable_encoding(self):
        self.assertTrue(
            self.raw.startswith(b"\xff\xfe"),
            "dsh_install_plugins.ps1 must stay UTF-16LE with BOM; "
            "PowerShell 5.1 misreads the Chinese strings otherwise",
        )
        text = self.raw.decode("utf-16-le")
        self.assertIn("公开设定资料", text)

    def test_dry_run_is_allowed_while_the_host_is_running(self):
        text = self.raw.decode("utf-16-le")
        # The running-process guard must not short-circuit a DryRun.
        self.assertRegex(text, r"if \(\$DryRun\) \{[\s\S]{0,200}?\} else \{")
        self.assertIn("DryRun 只打印计划", text)

    def test_qq_bridge_config_uses_defaults_and_takes_botqq(self):
        text = self.raw.decode("utf-16-le")
        self.assertIn("[string]$BotQQ", text)
        for expected in ("mode: reverse", "host: 127.0.0.1", "port: 8643"):
            self.assertIn(expected, text)
        # botQQ is written from the parameter, never hard-coded.
        self.assertIn('"    botQQ: \'$BotQQ\'"', text)

    def test_onebot_entry_is_id_targeted_not_inserted(self):
        text = self.raw.decode("utf-16-le")
        # A top-level `- id:` override is required; nesting it inside an insert
        # block is rejected by the settings composer self-check.
        self.assertIn("'- id: dsh-onebot'", text)
        self.assertIn("# >>> dsh-onebot-managed", text)
        # The managed block must not be glued onto a preceding quoted name.
        self.assertRegex(text, r"'# <<< dsh-onebot-managed',")

    def test_existing_onebot_block_is_not_duplicated(self):
        text = self.raw.decode("utf-16-le")
        self.assertIn("-like \u0022*$onebotMarker*\u0022", text)
        self.assertIn("跳过；要改端口或 botQQ", text)


if __name__ == "__main__":
    unittest.main()
