"""Boot a disposable DSH profile and run native bridge tests, without real accounts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = Path("D:/dsh/resources/runtime/cli/bin/dsh.cmd")


def run() -> int:
    # The test profile is deliberately separate from both desktop and earlier probes.
    home = ROOT / "outputs/dsh-migration/native-smoke"
    home.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT", "PROGRAMDATA",
    }}
    env.update(DSH_HOME=str(home), FATFISH_POLICY_FILE=str(ROOT / "dsh/policy.example.json"))
    archive = ROOT / ".tools/dsh-vendor/adapted/fatfish-onebot-0.9.6.tgz"
    if not archive.is_file():
        raise RuntimeError("Run scripts/prepare_dsh_onebot.py --pack first")
    profile = home / "profiles/web"
    log = home / "host.private.log"
    # CLI installs outside the production profile. A tarball, unlike a linked
    # source directory, gets its own dependencies inside the profile tree.
    with log.open("w", encoding="utf-8") as output:
        installed = subprocess.run([str(CLI), "plugin", "--profile", "web", "add", "file:" + archive.as_posix(), "--ignore-scripts"],
                                   cwd=home, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=120)
    if installed.returncode:
        print(json.dumps({"ok": False, "stage": "install", "log": str(log)})); return 1
    shutil.copy2(ROOT / "dsh/tests/native-smoke-plugin.mjs", profile / "native-smoke-plugin.mjs")
    patch = [
        {"id": "dsh-onebot", "config": {"port": 0, "host": "127.0.0.1", "accessToken": secrets.token_urlsafe(24), "botQQ": "10000001", "dmPolicy": "disabled", "groupPolicy": "disabled", "workspacePath": str(home)}},
        {"insert": [{"id": "fatfish-native-smoke", "name": str(profile / "native-smoke-plugin.mjs")} ]},
    ]
    (profile / "cordis.patch.yml").write_text(json.dumps(patch), encoding="utf-8")
    report = home / f"report-{time.time_ns()}.json"
    env["FATFISH_SMOKE_REPORT"] = str(report)
    with log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen([str(CLI), "web", "--port", "0", "--no-open"], cwd=home, env=env,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic() + 30
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
    raise SystemExit(run())
