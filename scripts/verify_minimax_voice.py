"""Three budgeted samples through the installed community MiniMax TTS client."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_minimax_voice import read_key, save_receipt
from fatfish_video.renderer import _resolve_tool

TEXTS = ("哟，老板！今天也是个适合冒险的好日子！", "苹果派！正宗天意！", "老板老板！你们在聊什么好玩的？")
MODEL = "speech-2.8-hd"


def billed_characters(text):
    return sum(2 if "\u3400" <= char <= "\u9fff" else 1 for char in text)


def estimate():
    return 9.9 + sum(billed_characters(text) for text in TEXTS) * 3.5 / 10000


def verify_encoding(path):
    result = subprocess.run([str(_resolve_tool("ffprobe")), "-v", "error", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, timeout=30, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(audio) != 1 or (audio[0].get("codec_name"), int(audio[0].get("sample_rate", 0)), audio[0].get("channels")) != ("mp3", 32000, 1):
        raise ValueError("Sample must actually be 32 kHz mono MP3")


async def verify(args):
    clone = json.loads(args.clone_receipt.read_text(encoding="utf-8-sig"))
    if clone.get("clone_state") != "accepted" or not clone.get("authorized"):
        raise ValueError("A successful authorized clone receipt is required")
    budget = min(10, float(clone.get("budget_cny", 0)))
    if estimate() > budget:
        raise ValueError("Three samples plus first-use voice fee exceed the authorized budget")
    if not args.apply:
        return {"voice_id": clone["voice_id"], "model": MODEL, "calls": 0,
                "estimated_total_cny": round(estimate(), 5), "budget_cny": budget}
    # Reuse the already installed MiniMax client and its hex decoder/audio cache.
    sys.path.insert(0, str(args.astrbot / "data/plugins"))
    sys.path.insert(0, str(args.astrbot))
    os.environ["ASTRBOT_ROOT"] = str(args.astrbot)
    os.environ["PATH"] = str(_resolve_tool("ffmpeg").parent) + os.pathsep + os.environ.get("PATH", "")
    module = importlib.import_module("astrbot_plugin_tts_emotion_router.tts.provider_minimax")
    diagnostics = importlib.import_module("astrbot_plugin_tts_emotion_router.core.diagnostics")
    diagnostics.check_decoder()
    state = {"voice_id": clone["voice_id"], "model": MODEL, "budget_cny": budget,
             "estimated_total_cny": round(estimate(), 5), "reserved_first_use_fee_cny": 9.9,
             "tts_call_limit": 3, "platform_sends": 0, "attempts": []}
    if args.output.exists():
        state = json.loads(args.output.read_text(encoding="utf-8-sig"))
        if state.get("voice_id") != clone["voice_id"]:
            raise ValueError("Existing TTS receipt belongs to another voice")
    client = module.MiniMaxTTS("https://api.minimax.cn/v1/t2a_v2", read_key(args.key_file), MODEL,
        fmt="mp3", speed=1.0, vol=1.0, pitch=0, voice_id=clone["voice_id"],
        sample_rate=32000, channel=1, output_format="hex", aigc_watermark=True,
        max_retries=0, timeout=120)
    try:
        for index, text in enumerate(TEXTS):
            previous = next((row for row in state["attempts"] if row["index"] == index), None)
            if previous:
                if previous.get("state") != "passed":
                    raise ValueError("A previous sample failed or has uncertain billing; no automatic retry")
                await asyncio.to_thread(verify_encoding, Path(previous["audio"]))
                continue
            if len(state["attempts"]) >= 3:
                raise ValueError("Authorized synthesis request limit reached")
            row = {"index": index, "text": text, "state": "submitted", "billed_character_estimate": billed_characters(text)}
            state["attempts"].append(row)
            save_receipt(args.output, state)
            started = time.monotonic()
            try:
                client.last_response_meta = None
                path = await asyncio.wait_for(client.synth(text, clone["voice_id"], args.output.parent / "audio"), timeout=135)
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                meta = client.last_response_meta or {}
                row["base_resp_status_code"] = meta.get("status_code")
                row["usage_characters"] = meta.get("usage_characters")
                if path is None:
                    raise RuntimeError("Installed MiniMax client did not return valid audio")
                duration = await asyncio.to_thread(diagnostics.decode_duration, path, "mp3", 32000, 1)
                await asyncio.to_thread(verify_encoding, path)
                size = path.stat().st_size
                if not 0 < size <= 5_000_000 or not 0 < duration <= 90:
                    raise ValueError("Unexpected sample size or duration")
                row.update(state="passed", audio=str(path.resolve()), seconds=round(duration, 3), bytes=size,
                           format="mp3", sample_rate=32000, channels=1, emotion_requested=False)
                save_receipt(args.output, state)
            except BaseException as exc:
                row.update(state="failed_or_uncertain", error_type=type(exc).__name__,
                           elapsed_seconds=round(time.monotonic() - started, 3))
                save_receipt(args.output, state)
                raise
    finally:
        await client.close()
    return {"voice_id": state["voice_id"], "samples_passed": len(state["attempts"]),
            "estimated_total_cny": state["estimated_total_cny"], "platform_sends": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot", type=Path, default=Path("D:/Code/Apps/AstrBot"))
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--clone-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/minimax-20261025/tts-receipt.json"))
    parser.add_argument("--apply", action="store_true")
    try:
        print(json.dumps(asyncio.run(verify(parser.parse_args())), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        raise SystemExit(1)
