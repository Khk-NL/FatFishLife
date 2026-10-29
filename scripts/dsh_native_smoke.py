"""Boot a disposable DSH profile and run native bridge tests, without real accounts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import secrets
import hashlib
import yaml
import subprocess
import time
import argparse

ROOT = Path(__file__).resolve().parents[1]
CLI = Path("D:/dsh/resources/runtime/cli/bin/dsh.cmd")


def run(community=False) -> int:
    # The test profile is deliberately separate from both desktop and earlier probes.
    home = ROOT / "outputs/dsh-migration/native-smoke"
    home.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT", "PROGRAMDATA",
    }}
    env.update(DSH_HOME=str(home), FATFISH_POLICY_FILE=str(ROOT / "dsh/policy.example.json"))
    # 忙时那句默认会问本地小模型；验收要确定性，固定用文案
    env.update(FATFISH_BUSY_BRIEF='fixed')
    def artifact(name):
        reference = ROOT / f'.tools/dsh-vendor/adapted/{name}-current.json'
        item = json.loads(reference.read_text(encoding='utf-8'))
        path = Path(item['archive'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Prepared archive hash mismatch')
        return path
    archive, control_archive = artifact('onebot'), artifact('control')
    profile = home / "profiles/web"
    log = home / "host.private.log"
    # CLI installs outside the production profile. A tarball, unlike a linked
    # source directory, gets its own dependencies inside the profile tree.
    # pnpm keeps its store index in SQLite. When this script runs under a
    # restricted file sandbox, SQLite cannot take file locks outside the
    # workspace, so the store pinned in the user's pnpm config fails to open.
    # FATFISH_SMOKE_STORE lets the caller point the store at a writable path.
    store = os.environ.get('FATFISH_SMOKE_STORE')
    extra = ['--store-dir', store] if store else []
    with log.open("w", encoding="utf-8") as output:
        controls = subprocess.run([str(CLI), 'plugin', '--profile', 'web', 'add', 'file:' + control_archive.as_posix(), '--ignore-scripts', *extra],
                                  cwd=home, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=300)
        if controls.returncode:
            raise RuntimeError('Control bundle installation failed; see private log')
        installed = subprocess.run([str(CLI), "plugin", "--profile", "web", "add", "file:" + archive.as_posix(), "--ignore-scripts", *extra],
                                   cwd=home, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=300)
    if installed.returncode:
        print(json.dumps({"ok": False, "stage": "install", "log": str(log)})); return 1
    if community:
        artifacts = json.loads((ROOT / '.tools/dsh-vendor/adapted/community-current.json').read_text(encoding='utf-8'))
        specs = []
        for item in artifacts:
            path = Path(item['archive'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Community archive hash mismatch')
            specs.append('file:' + path.as_posix())
        with log.open('a', encoding='utf-8') as output:
            subprocess.run([str(CLI), 'plugin', '--profile', 'web', 'add', *specs, '--ignore-scripts', *extra],
                           cwd=home, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=300, check=True)
        shutil.copy2(ROOT / 'scripts/dsh_community_check.mjs', profile / 'community-check.mjs')
        env['FATFISH_COMMUNITY_REPORT'] = str(home / 'community-check.json')
    shutil.copy2(ROOT / "dsh/tests/native-smoke-plugin.mjs", profile / "native-smoke-plugin.mjs")
    patch = [
        {'id': 'fatfish-control', 'config': {'identity': {'botId': '10000001', 'ownerId': '10000002', 'adapterId': 'native-test'},
                                         'dataDirectory': str(home / 'fatfish-settings')}},
        {"id": "dsh-onebot", "config": {"port": 0, "host": "127.0.0.1", "accessToken": secrets.token_urlsafe(24), "botQQ": "10000001", "dmPolicy": "disabled", "groupPolicy": "disabled", "workspacePath": str(home)}},
        {"insert": [{"id": "fatfish-native-smoke", "name": str(profile / "native-smoke-plugin.mjs")} ]},
    ]
    preset_rows = yaml.safe_load((ROOT / 'dsh/preset-apple-le.yml').read_text(encoding='utf-8'))
    patch.extend(preset_rows)
    persona = preset_rows[0]['insert'][0]['config']['plugins'][0]['config']['prefix']
    (home / 'expected-persona.txt').write_text(persona.strip(), encoding='utf-8', newline='\n')
    (profile / "cordis.patch.yml").write_text(json.dumps(patch), encoding="utf-8")
    report = home / f"report-{time.time_ns()}.json"
    env["FATFISH_SMOKE_REPORT"] = str(report)
    with log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen([str(CLI), "web", "--port", "0", "--no-open"], cwd=home, env=env,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic() + (55 if community else 30)
            while not report.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            result = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {"ok": False, "stage": "host/no-test-report"}
        finally:
            # Only the process tree just created here; never select by app name.
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
            process.wait(timeout=10)
    host_log = log.read_text(encoding="utf-8", errors="replace")
    result["bridgePluginActivated"] = "reverse WS server listening on" in host_log
    result["ok"] = result["ok"] and result["bridgePluginActivated"]
    print(json.dumps({**result, "log": str(log), "report": str(report)}, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--community', action='store_true', help='Verify reviewed text plugins using public read-only requests')
    raise SystemExit(run(parser.parse_args().community))
