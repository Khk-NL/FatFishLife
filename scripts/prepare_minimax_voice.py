"""Validate, upload and clone once; resumable receipts never contain the key."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.configure_local_services import read_env
from fatfish_video.renderer import _resolve_tool


def read_key(path: Path) -> str:
    """Accept env assignments or a one-line local key file without printing it."""
    values = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if len(values) == 1 and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", values[0]):
        key = values[0]
    else:
        env = read_env(path)
        key = env.get("FATFISH_MINIMAX_KEY") or env.get("MINIMAX_API_KEY") or ""
    key = os.environ.get("FATFISH_MINIMAX_KEY") or os.environ.get("MINIMAX_API_KEY") or key
    if not key or any(char.isspace() for char in key):
        raise ValueError("Missing or invalid local MiniMax key")
    return key


def validate(reference: Path, voice_id: str, *, prompt=False):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]", voice_id):
        raise ValueError("Voice ID must contain 8-256 supported characters")
    suffix = reference.suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a"}:
        raise ValueError("Reference must be WAV, MP3 or M4A")
    size = reference.stat().st_size
    if not 0 < size <= 20_000_000:
        raise ValueError("Reference exceeds 20 MB or is empty")
    if suffix == ".wav":
        with wave.open(str(reference), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            codec, rate, channels = "pcm", audio.getframerate(), audio.getnchannels()
    else:
        result = subprocess.run([str(_resolve_tool("ffprobe")), "-v", "error", "-show_format", "-show_streams",
                                 "-of", "json", str(reference)], capture_output=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
        if len(streams) != 1:
            raise ValueError("Reference must contain one audio stream")
        stream = streams[0]
        duration = float(data["format"]["duration"])
        codec, rate, channels = stream["codec_name"], int(stream["sample_rate"]), stream["channels"]
    if not math.isfinite(duration) or (not 0 < duration < 8 if prompt else not 10 <= duration <= 300):
        raise ValueError("Prompt must be <8 seconds; main reference must be 10-300 seconds")
    return {"duration": round(duration, 3), "bytes": size, "codec": codec, "sample_rate": rate,
            "channels": channels, "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()}


class MiniMaxRequestError(RuntimeError):
    def __init__(self, code=None):
        super().__init__("MiniMax request failed with status " + str(code))
        self.code = code


def save_receipt(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def request(url, key, *, payload=None, audio=None, purpose=None, audit=None, retries=0):
    """requests encodes multipart; only upload transport errors may retry."""
    for attempt in range(retries + 1):
        started = time.monotonic()
        entry = {"endpoint": url.rsplit("/", 1)[-1], "purpose": purpose,
                 "attempt": attempt + 1, "http_status": None}
        try:
            headers = {"Authorization": "Bearer " + key}
            if audio is not None:
                with audio.open("rb") as stream:
                    response = requests.post(url, headers=headers, data={"purpose": purpose},
                        files={"file": (audio.name, stream, mimetypes.guess_type(audio.name)[0] or "application/octet-stream")},
                        timeout=(15, 120))
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=(15, 120))
            entry["http_status"] = response.status_code
            try:
                result = response.json()
            except ValueError:
                raise MiniMaxRequestError("invalid_json") from None
            base = result.get("base_resp") or {}
            entry["base_resp"] = {"status_code": base.get("status_code"),
                "status_msg": str(base.get("status_msg", "")).replace(key, "[redacted]")[:300]}
            if response.status_code != 200 or base.get("status_code") != 0:
                raise MiniMaxRequestError(base.get("status_code", response.status_code))
            return result
        except (requests.Timeout, requests.ConnectionError) as exc:
            entry["network_exception"] = type(exc).__name__
            if audio is None or attempt == retries:
                raise MiniMaxRequestError(type(exc).__name__) from None
        finally:
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if audit is not None:
                audit(entry)
        time.sleep(min(2 ** attempt, 4))


def upload_audio(path, purpose, key, api_base, *, audit=None):
    uploaded = request(api_base + "/v1/files/upload", key, audio=path, purpose=purpose, audit=audit, retries=1)
    file_id = (uploaded.get("file") or {}).get("file_id")
    if not isinstance(file_id, int) or isinstance(file_id, bool) or file_id <= 0:
        raise ValueError("Upload response did not contain a valid file ID")
    return file_id


def run(args):
    info = validate(args.reference, args.voice_id)
    try:
        key = read_key(args.env_file)
    except (ValueError, FileNotFoundError):
        if args.apply:
            raise
        key = ""
    prompt = getattr(args, "prompt_audio", None)
    transcript_file = getattr(args, "prompt_text_file", None)
    if bool(prompt) != bool(transcript_file):
        raise ValueError("Prompt audio and its transcript must be provided together")
    prompt_info = validate(prompt, args.voice_id, prompt=True) if prompt else None
    prompt_text = transcript_file.read_text(encoding="utf-8-sig").strip() if transcript_file else ""
    if prompt and (not prompt_text or prompt_text[-1] not in "。！？.!?~～"):
        raise ValueError("Prompt transcript must match the audio and end in punctuation")
    if prompt_info:
        info["prompt_sha256"] = prompt_info["sha256"]
        info["prompt_text_sha256"] = hashlib.sha256(prompt_text.encode()).hexdigest()
    if not args.apply:
        return {"ready_reference": True, "key_configured": bool(key), "uploaded": False,
                "optional_prompt_ready": bool(prompt), **info}
    if not getattr(args, "authorized", False):
        raise ValueError("Confirm audio rights before upload")
    budget = float(getattr(args, "budget_cny", 0))
    if not math.isfinite(budget) or budget < 9.9:
        raise ValueError("Explicit budget covering the 9.90 CNY first-use clone fee is required")
    if args.api_base.rstrip("/") != "https://api.minimax.cn":
        raise ValueError("Only the verified official CN endpoint is accepted for live requests")
    state = {**info, "voice_id": args.voice_id, "file_id": None, "prompt_file_id": None,
             "clone_state": "not_submitted", "requests": [], "authorized": True, "budget_cny": budget}
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8-sig"))
        if any(previous.get(field) != state.get(field) for field in ("sha256", "voice_id", "prompt_sha256", "prompt_text_sha256")):
            raise ValueError("Existing receipt belongs to another reference")
        state = previous
        if state.get("clone_state") == "accepted" or state.get("result", {}).get("base_resp", {}).get("status_code") == 0:
            return {"already_prepared": True, "uploaded": False, "voice_id": args.voice_id}
        if state.get("clone_state") == "submitted":
            raise ValueError("Clone outcome uncertain; inspect official voice list before retrying")
    def audit(entry):
        state.setdefault("requests", []).append(entry)
        save_receipt(args.output, state)
    if not state.get("file_id"):
        state["file_id"] = upload_audio(args.reference, "voice_clone", key, args.api_base, audit=audit)
        save_receipt(args.output, state)
    if prompt and not state.get("prompt_file_id"):
        state["prompt_file_id"] = upload_audio(prompt, "prompt_audio", key, args.api_base, audit=audit)
        save_receipt(args.output, state)
    payload = {"file_id": state["file_id"], "voice_id": args.voice_id,
               "need_noise_reduction": False, "need_volume_normalization": False}
    if prompt:
        payload["clone_prompt"] = {"prompt_audio": state["prompt_file_id"], "prompt_text": prompt_text}
    state["clone_state"] = "submitted"
    save_receipt(args.output, state)
    cloned = request(args.api_base + "/v1/voice_clone", key, payload=payload, audit=audit)
    state.update(clone_state="accepted", result=cloned)
    save_receipt(args.output, state)
    return {"uploaded": True, "clone_accepted": True, "voice_id": args.voice_id,
            "preview_available": bool(cloned.get("demo_audio"))}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--prompt-audio", type=Path)
    p.add_argument("--prompt-text-file", type=Path)
    p.add_argument("--voice-id", default="AppleLeVoice20261025")
    p.add_argument("--api-base", default="https://api.minimax.cn")
    p.add_argument("--output", type=Path, default=Path("outputs/minimax-voice.json"))
    p.add_argument("--authorized", action="store_true")
    p.add_argument("--budget-cny", type=float, default=0)
    p.add_argument("--apply", action="store_true")
    try:
        print(json.dumps(run(p.parse_args()), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "status_code": getattr(exc, "code", None)}))
        raise SystemExit(1)
