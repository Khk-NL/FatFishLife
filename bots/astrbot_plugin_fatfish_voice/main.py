"""A native AstrBot TTS adapter with explicit SiliconFlow voice and speed."""

from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path
from uuid import uuid4
import wave

import httpx

from astrbot.api.star import Context, Star
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.provider.register import provider_cls_map, register_provider_adapter
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from fatfish_video.renderer import _resolve_tool

PROVIDER_TYPE = "fatfish_siliconflow_tts"
DEFAULT_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
DEFAULT_CONFIG = {
    "type": PROVIDER_TYPE, "id": PROVIDER_TYPE, "enable": False,
    "api_key": "", "api_base": "https://api.siliconflow.cn/v1",
    "model": DEFAULT_MODEL, "voice": DEFAULT_MODEL + ":diana", "speed": 1.1,
    "timeout": 60,
}


async def normalize_wav(source: Path, target: Path, *, timeout: float):
    """Decode all received PCM even when the streaming WAV lengths are placeholders."""
    executable = _resolve_tool("ffmpeg")
    process = await asyncio.create_subprocess_exec(
        str(executable), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "wav", "-ignore_length", "1", "-i", str(source),
        "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", str(target),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("TTS WAV 规整失败，请检查音频响应和 FFmpeg")
    with wave.open(str(target), "rb") as audio:
        size = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
        actual = len(audio.readframes(audio.getnframes()))
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000) or size <= 0 or actual != size:
            raise RuntimeError("TTS WAV 帧数或格式无效")


class FatfishSiliconFlowTTS(TTSProvider):
    def __init__(self, provider_config: dict, provider_settings: dict):
        super().__init__(provider_config, provider_settings)
        self.api_key = str(provider_config.get("api_key") or "").strip()
        if not self.api_key:
            raise ValueError("请在原生语音提供商配置中填写硅基流动 api_key")
        self.api_base = str(provider_config.get("api_base") or DEFAULT_CONFIG["api_base"]).rstrip("/")
        self.set_model(str(provider_config.get("model") or DEFAULT_MODEL))
        self.voice = str(provider_config.get("voice") or self.model_name + ":diana")
        self.emotion_voices = provider_config.get("emotion_voices") or {}
        self.speed = float(provider_config.get("speed", 1.1))
        if not math.isfinite(self.speed) or not 0.25 <= self.speed <= 4.0:
            raise ValueError("语速 speed 需在 0.25～4.0 之间")
        self.timeout = float(provider_config.get("timeout", 60))
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("语音 timeout 必须为正数")
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def get_audio(self, text: str) -> str:
        if not str(text).strip():
            raise ValueError("语音文本不能为空")
        text = str(text).strip()
        marker = re.match(r"^\[EMO:([a-z_]+)\]\s*", text, re.I)
        emotion = marker.group(1).lower() if marker else (
            "happy" if re.search(r"哈哈|好耶|太好啦|出发|啊噗噜派|嘿嘿", text) else
            "soft" if re.search(r"晚安|别难过|休息|困了|没关系", text) else "neutral"
        )
        if marker:
            text = text[marker.end():].strip()
        if not text:
            raise ValueError("语音文本不能为空")
        voice = str(self.emotion_voices.get(emotion) or self.voice)
        response = await self.client.post(
            self.api_base + "/audio/speech",
            headers={**self.request_headers, "Authorization": "Bearer " + self.api_key},
            json={"model": self.model_name, "voice": voice, "speed": self.speed,
                  "input": text, "response_format": "wav"},
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("TTS 返回空音频")
        directory = Path(get_astrbot_temp_path())
        directory.mkdir(parents=True, exist_ok=True)
        stem = "fatfish-voice-" + uuid4().hex
        source, target = directory / (stem + ".source.wav"), directory / (stem + ".wav")
        completed = False
        try:
            source.write_bytes(response.content)
            await normalize_wav(source, target, timeout=self.timeout)
            completed = True
            return str(target)
        finally:
            source.unlink(missing_ok=True)
            if not completed:
                target.unlink(missing_ok=True)

    async def terminate(self):
        await self.client.aclose()


# Plugin reload keeps the registered metadata object while refreshing its class.
if PROVIDER_TYPE in provider_cls_map:
    provider_cls_map[PROVIDER_TYPE].cls_type = FatfishSiliconFlowTTS
else:
    register_provider_adapter(
        PROVIDER_TYPE, "硅基流动语音，可选声线和语速", ProviderType.TEXT_TO_SPEECH,
        default_config_tmpl=dict(DEFAULT_CONFIG), provider_display_name="FatFish 硅基语音",
    )(FatfishSiliconFlowTTS)


class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)
