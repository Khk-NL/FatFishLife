"""TTS/STT 业务：从 AstrBot provider 里抽出来的纯逻辑。

迁移原则：只保留「调 API + 规整音频」，不碰 AstrBot 的事件、provider 基类。
音色、语速、ffmpeg 路径从环境变量取，不写死在代码里。

环境变量：
    FATFISH_TTS_API_KEY    硅基流动专用 key，不回退到 DeepSeek key
    FATFISH_TTS_BASE       API base，默认 https://api.siliconflow.cn/v1
    FATFISH_TTS_MODEL      默认 FunAudioLLM/CosyVoice2-0.5B
    FATFISH_TTS_VOICE      克隆音色 ID
    FATFISH_TTS_SPEED      默认 1.1
    FATFISH_FFMPEG         ffmpeg 可执行文件路径
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
WAV_HEADER = b"RIFF"


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    api_key: str
    api_base: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    voice: str = ""
    speed: float = 1.1
    ffmpeg: str = ""
    timeout: float = 40.0

    @classmethod
    def from_env(cls) -> "TTSConfig":
        key = os.environ.get("FATFISH_TTS_API_KEY", "").strip()
        return cls(
            api_key=key,
            api_base=os.environ.get("FATFISH_TTS_BASE", DEFAULT_BASE).strip(),
            model=os.environ.get("FATFISH_TTS_MODEL", DEFAULT_MODEL).strip(),
            voice=os.environ.get("FATFISH_TTS_VOICE", "").strip(),
            speed=float(os.environ.get("FATFISH_TTS_SPEED", "1.1")),
            ffmpeg=os.environ.get("FATFISH_FFMPEG", "").strip(),
            timeout=float(os.environ.get("FATFISH_TTS_TIMEOUT", "40")),
        )

    def validate(self) -> None:
        if not self.api_key:
            raise TTSError("缺少 TTS API key（FATFISH_TTS_API_KEY）")
        if not self.voice:
            raise TTSError("缺少音色 ID（FATFISH_TTS_VOICE）")


def synth(config: TTSConfig, text: str) -> bytes:
    """调 SiliconFlow 合成，返回 WAV 字节。失败抛 TTSError。"""
    config.validate()
    body = json.dumps(
        {
            "model": config.model,
            "input": text,
            "voice": config.voice,
            "response_format": "wav",
            "speed": config.speed,
        }
    ).encode()
    request = urllib.request.Request(
        config.api_base.rstrip("/") + "/audio/speech",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except OSError:
            pass
        raise TTSError(f"TTS HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TTSError(f"TTS 网络失败：{exc}") from exc

    if not data or not data.startswith(WAV_HEADER):
        raise TTSError(f"TTS 返回非 WAV 内容（{len(data)} 字节）")
    return data


def normalize_wav(config: TTSConfig, source: Path, target: Path) -> Path:
    """Decode all streamed PCM and verify complete 24kHz mono frames."""
    ffmpeg = config.ffmpeg or shutil.which("ffmpeg") or ""
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise TTSError('FFmpeg不可用，无法验证QQ音频格式')
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-loglevel", "error",
             "-f", "wav", "-ignore_length", "1", "-i", str(source),
             "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target)],
            capture_output=True,
            timeout=config.timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TTSError('音频解码失败') from exc
    if result.returncode != 0 or not target.is_file() or target.stat().st_size < 44:
        raise TTSError('FFmpeg未生成有效音频')
    try:
        with wave.open(str(target), 'rb') as audio:
            expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            actual = len(audio.readframes(audio.getnframes()))
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000) or expected <= 0 or expected != actual:
                raise TTSError('QQ音频帧数或格式无效')
    except (wave.Error, EOFError) as exc:
        raise TTSError('QQ音频无法读取') from exc
    return target


def synth_to_file(config: TTSConfig, text: str, out_dir: Path) -> Path:
    """合成并规整，返回最终 WAV 路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "tts-raw.wav"
    final = out_dir / "tts.wav"
    raw.write_bytes(synth(config, text))
    return normalize_wav(config, raw, final)


def probe(config: TTSConfig, text: str = "喂喂，听得见不") -> dict:
    """给验收用：合成一句，返回大小与头部，不落盘。"""
    data = synth(config, text)
    return {"bytes": len(data), "riff": data[:4] == WAV_HEADER, "model": config.model, "voice": config.voice}


def preflight(config: TTSConfig) -> dict:
    """Local readiness only: never submit text or credentials to a provider."""
    config.validate()
    if not math.isfinite(config.speed) or not 0.25 <= config.speed <= 4:
        raise TTSError("TTS 语速必须在0.25至4之间")
    if not math.isfinite(config.timeout) or config.timeout <= 0:
        raise TTSError("TTS 超时必须为正数")
    ffmpeg = config.ffmpeg or shutil.which("ffmpeg")
    return {"ok": True, "configuration_ready": True,
            "decoder_ready": bool(ffmpeg and Path(ffmpeg).is_file()),
            "synthesis_verified": False, "synthesis_requests": 0}
