"""Exercise the real Windows script host without launching a UI or service."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'scripts/run_hidden.vbs'


@unittest.skipUnless(os.name == 'nt', 'Windows Script Host required')
class HiddenLauncherTests(unittest.TestCase):
    def test_missing_command_is_failure(self):
        result = subprocess.run(['cscript.exe', '//nologo', str(LAUNCHER)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_waits_for_child_handles_spaces_and_returns_its_failure(self):
        with tempfile.TemporaryDirectory(prefix='fatfish hidden ') as folder:
            script = Path(folder) / 'child script.ps1'
            marker = Path(folder) / 'execution marker.txt'
            script.write_text("param([string]$Marker)\n"
                              "[IO.File]::WriteAllText($Marker, 'executed')\nexit 37\n",
                              encoding='utf-8-sig')
            result = subprocess.run(['cscript.exe', '//nologo', str(LAUNCHER),
                                     'powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden',
                                     '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                     '-Marker', str(marker)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 37, result.stderr.decode(errors='replace'))
            self.assertEqual(marker.read_text(), 'executed')
