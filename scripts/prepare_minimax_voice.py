"""Prepare an existing reference WAV for MiniMax; upload only with --apply."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import uuid
import wave

from configure_local_services import read_env


def validate(reference: Path, voice_id: str):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]", voice_id):
        raise ValueError("Voice ID must contain 8-256 supported characters")
    if reference.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Reference exceeds 20 MB")
    with wave.open(str(reference), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if not 10 <= duration <= 300:
        raise ValueError("Reference WAV must be 10-300 seconds")
    return {"duration": round(duration, 2), "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()}


def request(url, key, body, content_type):
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.load(response)
    status = (result.get("base_resp") or {}).get("status_code", 0)
    if status != 0:
        raise RuntimeError("MiniMax request failed with status " + str(status))
    return result


def run(args):
    info = validate(args.reference, args.voice_id)
    env = read_env(args.env_file)
    key = env.get("FATFISH_MINIMAX_KEY") or ""
    if not args.apply:
        return {"ready_reference": True, "key_configured": bool(key), "uploaded": False, **info}
    if not key:
        raise ValueError("Fill FATFISH_MINIMAX_KEY in the local env file")
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous.get("sha256") == info["sha256"] and previous.get("voice_id") == args.voice_id:
            return {"already_prepared": True, "uploaded": False}
        raise ValueError("Existing receipt belongs to another reference; use a new output and voice ID")
    boundary = "fatfish-" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nvoice_clone\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"reference.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n").encode() + args.reference.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    upload = request(args.api_base + "/v1/files/upload", key, body, "multipart/form-data; boundary=" + boundary)
    file_id = upload["file"]["file_id"]
    payload = {"file_id": file_id, "voice_id": args.voice_id, "need_noise_reduction": True,
               "need_volume_normalization": True, "text": "老板，今天的事情我记住啦。好耶，啊噗噜派！",
               "model": "speech-2.8-hd"}
    cloned = request(args.api_base + "/v1/voice_clone", key, json.dumps(payload).encode(), "application/json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**info, "voice_id": args.voice_id, "file_id": file_id,
                                     "result": cloned}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"uploaded": True, "clone_accepted": True, "preview_available": bool(cloned.get("demo_audio"))}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--voice-id", default="FatFishExusiai2026")
    p.add_argument("--api-base", default="https://api.minimax.cn")
    p.add_argument("--output", type=Path, default=Path("outputs/minimax-voice.json"))
    p.add_argument("--apply", action="store_true")
    try:
        print(json.dumps(run(p.parse_args()), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)
