"""Verify installed AstrBot TTS/STT locally without sending a QQ message.

Run with AstrBot's Python environment. Credentials stay in its configuration;
only fixed test speech, audio files and a credential-free report are produced.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import wave


TEST_TEXT = "老板，今天的语音检查开始啦。企鹅物流，使命必达。"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_tts_adapter(provider_type: str, astrbot_root: Path):
    if provider_type == "fatfish_siliconflow_tts":
        # Verify the deployed plugin, rather than importing a development copy.
        path = astrbot_root / "data/plugins/astrbot_plugin_fatfish_voice/main.py"
        if not path.is_file():
            raise FileNotFoundError("installed_fatfish_voice_adapter_missing")
        spec = importlib.util.spec_from_file_location("_fatfish_voice_adapter_verification", path)
        if spec is None or spec.loader is None:
            raise ImportError("installed_fatfish_voice_adapter_unloadable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.FatfishSiliconFlowTTS
    adapters = {
        "edge_tts": ("edge_tts_source", "ProviderEdgeTTS"),
        "openai_tts_api": ("openai_tts_api_source", "ProviderOpenAITTSAPI"),
    }
    if provider_type not in adapters:
        raise ValueError("unsupported_or_missing_tts_provider")
    module_name, class_name = adapters[provider_type]
    module = importlib.import_module("astrbot.core.provider.sources." + module_name)
    return getattr(module, class_name)


async def verify(args: argparse.Namespace) -> dict:
    config = read_json(args.astrbot_root / "data" / "cmd_config.json")
    sys.path.insert(0, str(args.astrbot_root))
    os.environ["ASTRBOT_ROOT"] = str(args.astrbot_root.resolve())
    if args.ffmpeg_bin:
        executable = args.ffmpeg_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not executable.is_file():
            raise ValueError("configured_ffmpeg_missing")
        os.environ["PATH"] = str(args.ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "test_text": TEST_TEXT,
        "message_sent": False,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
        "ffmpeg_override": bool(args.ffmpeg_bin),
    }
    try:
        from fatfish_video.renderer import _resolve_tool
        report["ffmpeg_available"] = _resolve_tool("ffmpeg").is_file()
    except (ImportError, RuntimeError) as exc:
        report["ffmpeg_resolution_error"] = type(exc).__name__
    tts_settings = config.get("provider_tts_settings", {})
    stt_settings = config.get("provider_stt_settings", {})
    providers = {item["id"]: item for item in config.get("provider", [])}
    tts_id = args.tts_provider_id or tts_settings.get("provider_id")
    stt_id = stt_settings.get("provider_id")
    tts_config = providers.get(tts_id, {})
    stt_config = providers.get(stt_id, {})
    report["tts"] = {"provider_id": tts_id, "enabled": bool(tts_settings.get("enable"))}
    report["stt"] = {"provider_id": stt_id, "enabled": bool(stt_settings.get("enable"))}

    # Use the installed adapters, including their actual conversion/resolver code.
    tts_type = tts_config.get("type")
    report["tts"]["type"] = tts_type
    tts = None
    target = args.output_dir / "tts-test.wav"
    try:
        adapter = load_tts_adapter(tts_type, args.astrbot_root)
        tts = adapter(tts_config, tts_settings)
        source = await asyncio.wait_for(tts.get_audio(TEST_TEXT), timeout=args.timeout)
        shutil.copyfile(source, target)
        with wave.open(str(target), "rb") as audio:
            frame_width = audio.getnchannels() * audio.getsampwidth()
            byte_count = 0
            while chunk := audio.readframes(65536):
                byte_count += len(chunk)
            seconds = byte_count / frame_width / audio.getframerate()
            valid = byte_count > 0 and byte_count % frame_width == 0
        report["tts"].update(
            success=valid, audio=str(target.resolve()), bytes=target.stat().st_size,
            seconds=round(seconds, 2),
        )
    except Exception as exc:
        # Provider exceptions can contain request details; report the type only.
        report["tts"].update(success=False, error=type(exc).__name__)
        return report
    finally:
        terminate = getattr(tts, "terminate", None)
        if terminate is not None:
            await terminate()

    if stt_config.get("type") != "openai_whisper_api":
        report["stt"].update(success=False, error="unsupported_or_missing_stt_provider")
        return report
    report["stt"]["credential_configured"] = bool(stt_config.get("api_key"))
    if not stt_config.get("api_key"):
        report["stt"].update(success=False, error="missing_stt_api_key")
        return report
    stt = None
    try:
        module = importlib.import_module("astrbot.core.provider.sources.whisper_api_source")
        stt = module.ProviderOpenAIWhisperAPI(stt_config, stt_settings)
        text = await asyncio.wait_for(stt.get_text(str(target.resolve())), timeout=args.timeout)
        # This transcript contains only the fixed test text above, never a chat.
        report["stt"].update(
            success=bool(text.strip()),
            matches_expected=all(word in text for word in ("老板", "语音", "企鹅物流", "使命必达")),
            transcript=text,
        )
    except Exception as exc:
        report["stt"].update(success=False, error=type(exc).__name__)
    finally:
        if stt is not None:
            await stt.terminate()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="本机语音合成及转写验收，不向QQ发送消息。")
    parser.add_argument("--astrbot-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-bin", type=Path, help="已有 ffmpeg 的目录，不下载或安装依赖")
    parser.add_argument("--tts-provider-id", help="默认使用 AstrBot 当前选择的 TTS")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    try:
        report = asyncio.run(verify(args))
    except Exception as exc:
        report = {"success": False, "error": type(exc).__name__, "message_sent": False}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "voice-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    # ASCII keeps legacy Windows consoles from failing on STT emotion symbols.
    print(json.dumps(report, ensure_ascii=True))
    passed = (
        all(report.get(key, {}).get("success") for key in ("tts", "stt"))
        and report.get("stt", {}).get("matches_expected", False)
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
