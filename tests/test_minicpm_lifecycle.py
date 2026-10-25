"""Exercise the actual PowerShell launcher without starting a model process."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SHELL = shutil.which('pwsh') or shutil.which('powershell')
LAUNCHER = Path(__file__).resolve().parents[1] / 'scripts/start_minicpm_context.ps1'


@unittest.skipUnless(os.name == 'nt' and SHELL, 'Windows PowerShell launcher')
class MiniCPMLifecycleTests(unittest.TestCase):
    def launch(self, *, idle=60, healthy=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'llama').mkdir()
            for path in ('llama/llama-server.exe', 'MiniCPM5-2B-Q4_K_M.gguf', 'api-key.local'):
                (root / path).write_text('local-test', encoding='utf-8')
            script = root / 'harness.ps1'
            script.write_text('''$ErrorActionPreference='Stop'
$global:captured=@()
function Invoke-RestMethod {
    param($Uri,$Headers,$TimeoutSec)
    if($env:FATFISH_TEST_HEALTH -eq 'ok'){return @{status='ok'}}
    throw 'No running test service'
}
function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction) return @() }
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError)
    $global:captured+=@{file=$FilePath;arguments=@($ArgumentList);window=$WindowStyle}
}
& $env:FATFISH_TEST_LAUNCHER -Root $env:FATFISH_TEST_ROOT -IdleSeconds ([int]$env:FATFISH_TEST_IDLE)
ConvertTo-Json -InputObject @($global:captured) -Depth 5 -Compress
''', encoding='utf-8-sig')
            env = {**os.environ, 'FATFISH_TEST_LAUNCHER': str(LAUNCHER), 'FATFISH_TEST_ROOT': str(root),
                   'FATFISH_TEST_IDLE': str(idle), 'FATFISH_TEST_HEALTH': 'ok' if healthy else 'down'}
            result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(script)],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_default_launch_uses_native_sixty_second_sleep(self):
        launches = self.launch()
        self.assertEqual(len(launches), 1)
        args = launches[0]['arguments']
        self.assertEqual(args[args.index('--sleep-idle-seconds') + 1], '60')
        self.assertEqual(args[args.index('--host') + 1], '127.0.0.1')
        self.assertIn('--api-key-file', args)
        self.assertEqual(launches[0]['window'], 'Hidden')

    def test_custom_idle_timeout_reaches_runtime(self):
        args = self.launch(idle=30)[0]['arguments']
        self.assertEqual(args[args.index('--sleep-idle-seconds') + 1], '30')

    def test_healthy_existing_listener_is_not_duplicated_or_woken(self):
        self.assertEqual(self.launch(healthy=True), [])
