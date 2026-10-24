"""Prepare an existing reference WAV for MiniMax; upload only with --apply."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.configure_local_services import read_env


def validate(reference: Path, voice_id: str, *, prompt=False):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]", voice_id):
        raise ValueError("Voice ID must contain 8-256 supported characters")
    if reference.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Reference exceeds 20 MB")
    with wave.open(str(reference), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if prompt and not 0 < duration < 8:
        raise ValueError("Prompt WAV must be shorter than 8 seconds")
    if not prompt and not 10 <= duration <= 300:
        raise ValueError("Reference WAV must be 10-300 seconds")
    return {"duration": round(duration, 2), "sha256": hashlib.sha256(reference.read_bytes()).hexdigest()}


def request(url, key, body, content_type):
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.load(response)
    status = (result.get("base_resp") or {}).get("status_code")
    if status != 0:
        raise RuntimeError("MiniMax request failed with status " + str(status))
    return result


def upload_audio(path, purpose, key, api_base):
    boundary = "fatfish-" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n{purpose}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"reference.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    uploaded = request(api_base + "/v1/files/upload", key, body, "multipart/form-data; boundary=" + boundary)
    file_id = (uploaded.get("file") or {}).get("file_id")
    if not isinstance(file_id, int) or isinstance(file_id, bool) or file_id <= 0:
        raise ValueError("Upload response did not contain a valid file ID")
    return file_id


def run(args):
    info = validate(args.reference, args.voice_id)
    env = read_env(args.env_file)
    key = env.get("FATFISH_MINIMAX_KEY") or ""
    prompt = getattr(args, "prompt_audio", None)
    transcript_file = getattr(args, "prompt_text_file", None)
    if bool(prompt) != bool(transcript_file):
        raise ValueError("Prompt audio and its transcript must be provided together")
    prompt_info = validate(prompt, args.voice_id, prompt=True) if prompt else None
    prompt_text = transcript_file.read_text(encoding="utf-8-sig").strip() if transcript_file else ""
    if prompt and not prompt_text:
        raise ValueError("Prompt transcript is empty")
    if prompt_info:
        info["prompt_sha256"] = prompt_info["sha256"]
        info["prompt_text_sha256"] = hashlib.sha256(prompt_text.encode()).hexdigest()
    if not args.apply:
        return {"ready_reference": True, "key_configured": bool(key), "uploaded": False,
                "optional_prompt_ready": bool(prompt), **info}
    if not key:
        raise ValueError("Fill FATFISH_MINIMAX_KEY in the local env file")
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if (previous.get("sha256") == info["sha256"] and previous.get("voice_id") == args.voice_id
                and previous.get("prompt_sha256") == info.get("prompt_sha256")
                and previous.get("prompt_text_sha256") == info.get("prompt_text_sha256")):
            return {"already_prepared": True, "uploaded": False}
        raise ValueError("Existing receipt belongs to another reference; use a new output and voice ID")
    file_id = upload_audio(args.reference, "voice_clone", key, args.api_base)
    payload = {"file_id": file_id, "voice_id": args.voice_id, "need_noise_reduction": True,
               "need_volume_normalization": True, "text": "老大，叫我呀？嘿嘿，忙完一起玩吧！",
               "model": "speech-2.8-hd"}
    if prompt:
        payload["clone_prompt"] = {"prompt_audio": upload_audio(prompt, "prompt_audio", key, args.api_base),
                                   "prompt_text": prompt_text}
    cloned = request(args.api_base + "/v1/voice_clone", key, json.dumps(payload).encode(), "application/json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**info, "voice_id": args.voice_id, "file_id": file_id,
                                     "result": cloned}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"uploaded": True, "clone_accepted": True, "preview_available": bool(cloned.get("demo_audio"))}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--prompt-audio", type=Path, help="Optional example WAV shorter than 8 seconds")
    p.add_argument("--prompt-text-file", type=Path, help="UTF-8 transcript matching the optional example")
    p.add_argument("--voice-id", default="FatFishExusiai2026")
    p.add_argument("--api-base", default="https://api.minimax.cn")
    p.add_argument("--output", type=Path, default=Path("outputs/minimax-voice.json"))
    p.add_argument("--apply", action="store_true")
    try:
        print(json.dumps(run(p.parse_args()), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)
