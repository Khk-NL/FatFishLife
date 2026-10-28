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
import io
from urllib.parse import quote, urlencode

from .local_credentials import read_value
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
WAV_HEADER = b"RIFF"
PROVIDERS = {
    'siliconflow': {'base': DEFAULT_BASE, 'model': DEFAULT_MODEL},
    'elevenlabs': {'base': 'https://api.elevenlabs.io/v1', 'model': 'eleven_multilingual_v2'},
    'minimax': {'base': 'https://api.minimax.io/v1', 'model': 'speech-2.8-hd'},
}


def managed_voice() -> dict:
    path = Path(os.environ.get('FATFISH_BEHAVIOR_FILE') or Path(__file__).resolve().parents[1] / 'data/dsh/runtime-behavior.json')
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('voice', {})
    except (OSError, ValueError) as exc:
        raise TTSError('DSH配音配置无法读取') from exc


def synthesis_allowed() -> bool:
    return os.environ.get('FATFISH_MEDIA_WRITE') == '1' or managed_voice().get('allow_synthesis') is True


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
    provider: str = 'siliconflow'

    @classmethod
    def from_env(cls) -> "TTSConfig":
        settings = managed_voice()
        provider = settings.get('provider') or os.environ.get('FATFISH_TTS_PROVIDER', 'siliconflow').strip()
        if provider not in PROVIDERS:
            raise TTSError('未知配音服务')
        selected = settings.get('providers', {}).get(provider, {})
        if provider == 'siliconflow':
            key = os.environ.get('FATFISH_TTS_API_KEY', '').strip()
            base = selected.get('apiBase') or os.environ.get('FATFISH_TTS_BASE', DEFAULT_BASE)
            model = selected.get('modelId') or os.environ.get('FATFISH_TTS_MODEL', DEFAULT_MODEL)
            voice = selected.get('voiceId') or os.environ.get('FATFISH_TTS_VOICE', '')
            speed = selected.get('speed', os.environ.get('FATFISH_TTS_SPEED', '1.1'))
        else:
            prefix = 'FATFISH_' + provider.upper()
            key = os.environ.get(prefix + '_API_KEY') or os.environ.get(provider.upper() + '_API_KEY', '')
            credential_file = selected.get('envFile') or os.environ.get(prefix + '_ENV_FILE', '')
            if not key and not credential_file and provider == 'elevenlabs':
                try:
                    credential_file = str(Path.home() / 'Desktop/.env')
                except RuntimeError as exc:
                    raise TTSError('请明确设置ElevenLabs密钥文件路径') from exc
            if not key and credential_file:
                aliases = (provider.upper() + '_API_KEY', prefix + '_API_KEY', 'XI_API_KEY', 'API_KEY') if provider == 'elevenlabs' else ('MINIMAX_API_KEY', prefix + '_API_KEY')
                key = read_value(credential_file, aliases, allow_bare=provider == 'elevenlabs')
            base = selected.get('apiBase') or os.environ.get(prefix + '_BASE', PROVIDERS[provider]['base'])
            model = selected.get('modelId') or os.environ.get(prefix + '_MODEL', PROVIDERS[provider]['model'])
            voice = selected.get('voiceId') or os.environ.get(prefix + '_VOICE', '')
            speed = selected.get('speed', os.environ.get(prefix + '_SPEED', '1.0'))
        return cls(
            api_key=key,
            api_base=str(base).strip(), model=str(model).strip(), voice=str(voice).strip(), speed=float(speed),
            ffmpeg=os.environ.get("FATFISH_FFMPEG", "").strip(),
            timeout=float(os.environ.get("FATFISH_TTS_TIMEOUT", "40")),
            provider=provider,
        )

    def validate(self) -> None:
        if self.provider not in PROVIDERS:
            raise TTSError('未知配音服务')
        if not self.api_key:
            raise TTSError(f"缺少{self.provider}专用API key")
        if not self.voice:
            raise TTSError(f"缺少{self.provider}音色ID，请在配音配置中选择")
        low, high = (.7, 1.2) if self.provider == 'elevenlabs' else (.5, 2.) if self.provider == 'minimax' else (.25, 4.)
        if not math.isfinite(self.speed) or not low <= self.speed <= high:
            raise TTSError(f'{self.provider}语速范围为{low}至{high}')


def synth(config: TTSConfig, text: str) -> bytes:
    """Provider-specific auth and payloads; always return WAV bytes."""
    config.validate()
    if config.provider == 'siliconflow':
        url, payload = config.api_base.rstrip('/') + '/audio/speech', {
            "model": config.model,
            "input": text,
            "voice": config.voice,
            "response_format": "wav",
            "speed": config.speed,
        }
    elif config.provider == 'elevenlabs':
        url = config.api_base.rstrip('/') + '/text-to-speech/' + quote(config.voice, safe='') + '?' + urlencode({'output_format': 'pcm_24000'})
        payload = {'text': text, 'model_id': config.model, 'voice_settings': {'speed': config.speed}}
    else:
        url = config.api_base.rstrip('/') + '/t2a_v2'
        payload = {'model': config.model, 'text': text, 'stream': False, 'output_format': 'hex',
                   'voice_setting': {'voice_id': config.voice, 'speed': config.speed, 'vol': 1, 'pitch': 0},
                   'audio_setting': {'sample_rate': 24000, 'format': 'wav', 'channel': 1}}
    auth = {'xi-api-key': config.api_key} if config.provider == 'elevenlabs' else {'Authorization': 'Bearer ' + config.api_key}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={**auth, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            if config.provider == 'elevenlabs':
                content_type = response.headers.get('Content-Type', '').partition(';')[0]
                if content_type and not (content_type.startswith('audio/') or content_type == 'application/octet-stream'):
                    raise TTSError('ElevenLabs返回非音频响应')
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise TTSError(f"{config.provider} TTS HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TTSError(f"{config.provider} TTS网络失败：{type(exc).__name__}") from exc

    if config.provider == 'elevenlabs':
        if not data or len(data) % 2:
            raise TTSError('ElevenLabs返回无效PCM帧')
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000); audio.writeframes(data)
        data = buffer.getvalue()
    elif config.provider == 'minimax':
        try:
            result = json.loads(data)
            code = result.get('base_resp', {}).get('status_code')
            if code != 0:
                raise TTSError(f'MiniMax业务错误码{code}')
            data = bytes.fromhex(result['data']['audio'])
        except (ValueError, TypeError, KeyError) as exc:
            raise TTSError('MiniMax返回无效音频数据') from exc

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
            "synthesis_verified": False, "synthesis_requests": 0, "provider": config.provider}
