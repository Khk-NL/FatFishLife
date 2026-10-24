from __future__ import annotations

import io
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

from plugin_support import load_plugin


def module(name, **values):
    result = types.ModuleType(name)
    result.__dict__.update(values)
    return result


class TTSProvider:
    def __init__(self, config, settings):
        self.provider_config, self.provider_settings = config, settings
        self.request_headers = {}

    def set_model(self, model):
        self.model_name = model


registry = {}
registration = Mock()


def register(name, description, provider_type, **kwargs):
    registration(name, description, provider_type, **kwargs)

    def decorate(cls):
        registry[name] = types.SimpleNamespace(cls_type=cls)
        return cls
    return decorate


httpx = module("httpx", AsyncClient=Mock())
PLUGIN = load_plugin("astrbot_plugin_fatfish_voice", module_overrides={
    "httpx": httpx,
    "astrbot.core.provider": module("astrbot.core.provider"),
    "astrbot.core.provider.entities": module("astrbot.core.provider.entities", ProviderType=types.SimpleNamespace(TEXT_TO_SPEECH="tts")),
    "astrbot.core.provider.provider": module("astrbot.core.provider.provider", TTSProvider=TTSProvider),
    "astrbot.core.provider.register": module("astrbot.core.provider.register", provider_cls_map=registry, register_provider_adapter=register),
    "astrbot.core.utils": module("astrbot.core.utils"),
    "astrbot.core.utils.astrbot_path": module("astrbot.core.utils.astrbot_path", get_astrbot_temp_path=lambda: "unused"),
})


class VoiceProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.client = types.SimpleNamespace(post=AsyncMock(), aclose=AsyncMock())
        self.response = Mock(content=b"not accessed before conversion")
        self.client.post.return_value = self.response
        self.client_patch = patch.object(httpx, "AsyncClient", return_value=self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.temp_patch = patch.object(PLUGIN, "get_astrbot_temp_path", return_value=str(self.root))
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)

    def provider(self, **config):
        return PLUGIN.FatfishSiliconFlowTTS({"api_key": "synthetic-test-key", **config}, {})

    async def test_adapter_registers_disabled_native_tts_without_creating_a_provider(self):
        self.assertEqual(registry[PLUGIN.PROVIDER_TYPE].cls_type, PLUGIN.FatfishSiliconFlowTTS)
        args, kwargs = registration.call_args
        self.assertEqual(args[2], "tts")
        self.assertFalse(kwargs["default_config_tmpl"]["enable"])
        self.assertEqual(kwargs["default_config_tmpl"]["api_key"], "")
        self.client.post.assert_not_awaited()

    async def test_request_passes_actual_speed_and_voice_and_returns_only_converted_file(self):
        async def convert(source, target, *, timeout):
            self.assertEqual(source.read_bytes(), self.response.content)
            with wave.open(str(target), "wb") as stream:
                stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\0\0" * 240)

        provider = self.provider(voice="custom-voice", speed=1.15)
        with patch.object(PLUGIN, "normalize_wav", side_effect=convert):
            target = Path(await provider.get_audio("固定测试文本"))
        args, kwargs = self.client.post.call_args
        self.assertEqual(args[0], "https://api.siliconflow.cn/v1/audio/speech")
        self.assertEqual(kwargs["json"], {"model": PLUGIN.DEFAULT_MODEL, "voice": "custom-voice", "speed": 1.15,
                                           "input": "固定测试文本", "response_format": "wav"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer synthetic-test-key")
        self.assertEqual(list(self.root.iterdir()), [target])
        await provider.terminate()
        self.client.aclose.assert_awaited_once()

    async def test_emotion_reference_is_selected_and_internal_marker_is_not_spoken(self):
        async def convert(source, target, *, timeout):
            target.write_bytes(b"validated_by_converter")
        provider = self.provider(voice="neutral", emotion_voices={"happy": "happy-reference"})
        with patch.object(PLUGIN, "normalize_wav", side_effect=convert):
            await provider.get_audio("[EMO:happy] 好耶，出发！")
        sent = self.client.post.await_args.kwargs["json"]
        self.assertEqual(sent["voice"], "happy-reference")
        self.assertEqual(sent["input"], "好耶，出发！")
        self.assertEqual(sent["speed"], 1.1)
        await provider.terminate()

    async def test_normalizes_streaming_wav_placeholder_lengths_to_actual_frame_count(self):
        try:
            PLUGIN._resolve_tool("ffmpeg")
        except Exception:
            self.skipTest("FFmpeg required for actual WAV normalization")
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 4800)
        malformed = bytearray(stream.getvalue())
        malformed[4:8] = struct.pack("<I", 0xFFFFFFFF)
        malformed[40:44] = struct.pack("<I", 0xFFFFFFFF)
        self.response.content = bytes(malformed)
        result = await self.provider().get_audio("固定测试文本")
        with wave.open(result, "rb") as audio:
            self.assertEqual(audio.getnframes(), 4800)
            self.assertEqual(len(audio.readframes(10000)), 9600)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    async def test_http_failure_and_timeout_propagate_without_fallback_or_artifacts(self):
        provider = self.provider()
        self.response.raise_for_status.side_effect = RuntimeError("synthetic HTTP failure")
        with self.assertRaises(RuntimeError):
            await provider.get_audio("测试")
        self.client.post.side_effect = TimeoutError("synthetic timeout")
        with self.assertRaises(TimeoutError):
            await provider.get_audio("测试")
        self.assertEqual(self.client.post.await_count, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_conversion_failure_is_not_replaced_with_raw_audio(self):
        async def fail(source, target, **kwargs):
            target.write_bytes(b"partial")
            raise RuntimeError("synthetic conversion failure")
        with patch.object(PLUGIN, "normalize_wav", side_effect=fail), self.assertRaises(RuntimeError):
            await self.provider().get_audio("测试")
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_default_speed_and_invalid_configurations(self):
        provider = self.provider()
        self.assertEqual(provider.speed, 1.1)
        self.assertEqual(provider.voice, PLUGIN.DEFAULT_MODEL + ":diana")
        for config in ({"api_key": ""}, {"speed": 0}, {"speed": float("nan")}, {"timeout": -1}):
            with self.assertRaises(ValueError):
                self.provider(**config)


if __name__ == "__main__":
    unittest.main()
