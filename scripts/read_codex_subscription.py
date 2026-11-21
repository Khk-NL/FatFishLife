"""Read the signed-in Codex catalog and quota through the official stdio service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


def read_status(executable: str, state_dir: Path, minimum_remaining: float = 80) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    command = [executable, "-c", "sqlite_home=" + json.dumps(state_dir.as_posix()),
               "-c", "log_dir=" + json.dumps((state_dir / "logs").as_posix()), "app-server"]
    messages = queue.Queue()
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
        def receive():
            for line in child.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
            messages.put(None)

        threading.Thread(target=receive, daemon=True).start()

        def send(message):
            child.stdin.write(json.dumps(message) + "\n")
            child.stdin.flush()

        def request(method, request_id, params=None):
            message = {"id": request_id, "method": method}
            if params is not None:
                message["params"] = params
            send(message)
            deadline = time.monotonic() + 12
            while True:
                allowance = deadline - time.monotonic()
                if allowance <= 0:
                    raise queue.Empty
                response = messages.get(timeout=allowance)
                if response is None:
                    raise RuntimeError("app-server-closed")
                if response.get("id") == request_id:
                    return response.get("result")

        try:
            if request("initialize", 1, {"clientInfo": {"name": "fatfishlife", "version": "1"}}) is None:
                return {"status": "initialization-unavailable"}
            send({"method": "initialized", "params": {}})
            account = request("account/read", 2, {"refreshToken": False}) or {}
            if (account.get("account") or {}).get("type") != "chatgpt":
                return {"status": "subscription-sign-in-required"}
            limits = request("account/rateLimits/read", 3) or {}
            catalog = request("model/list", 4, {"includeHidden": False, "limit": 100}) or {}
        except (OSError, RuntimeError, queue.Empty):
            return {"status": "app-server-unavailable"}
        finally:
            if child.poll() is None:
                child.terminate()

    target = next((model for model in catalog.get("data", []) if model.get("model") == "gpt-6.2-sol"), {})
    efforts = [entry.get("reasoningEffort") for entry in target.get("supportedReasoningEfforts", [])]
    pair = limits.get("rateLimits") or {}
    window = next((entry for entry in (pair.get("primary"), pair.get("secondary"))
                   if isinstance(entry, dict) and entry.get("windowDurationMins") == 300), {})
    used = window.get("usedPercent")
    remaining = 100 - used if type(used) in (int, float) and 0 <= used <= 100 else None
    now = int(time.time())
    resets_at = window.get("resetsAt")
    available = "medium" in efforts
    return {"status": "read", "checkedAt": now, "remaining5h": remaining,
            "resetsAt": resets_at, "solMediumAvailable": available,
            "minimumRemaining5h": minimum_remaining,
            "eligible": available and remaining is not None and remaining > minimum_remaining
            and type(resets_at) in (int, float) and resets_at > now}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--codex", default=shutil.which("codex"))
    options = parser.parse_args()
    behavior = Path(os.environ.get("FATFISH_BEHAVIOR_FILE")
                    or Path(__file__).resolve().parents[1] / "data/dsh/runtime-behavior.json")
    minimum = 80
    try:
        routing = json.loads(behavior.read_text(encoding="utf-8-sig")).get("model_routing") or {}
        value = routing.get("codex_min_remaining_percent")
        if type(value) in (int, float) and 0 <= value <= 100:
            minimum = value
    except (OSError, ValueError, AttributeError):
        pass
    result = (read_status(options.codex, options.state_dir.resolve(), minimum)
              if options.codex else {"status": "codex-cli-unavailable"})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
