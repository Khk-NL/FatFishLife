import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave

from fatfish_core import tts
from fatfish_core.local_credentials import read_value


class Response(io.BytesIO):
    headers = {'Content-Type': 'audio/pcm'}


class ProviderTests(unittest.TestCase):
    def test_media_permission_does_not_grant_memory_writes(self):
        from dsh.service import fatfish_memory_mcp as service
        with patch.dict(os.environ, {'FATFISH_SERVICE_READONLY':'1','FATFISH_MEDIA_WRITE':'1'},clear=True), patch.object(service,'store',side_effect=AssertionError('memory write')):
            result = json.loads(service.remember('test'))
        self.assertFalse(result['ok'])

    def test_named_and_bare_credentials_stay_provider_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            path.write_text('ELEVENLABS_API_KEY="test-eleven-only"\nDEEPSEEK_API_KEY=other-provider\n')
            self.assertEqual(read_value(path, ('ELEVENLABS_API_KEY',)), 'test-eleven-only')
            self.assertEqual(read_value(path, ('MINIMAX_API_KEY',), allow_bare=True), '')
            path.write_text('bare-test-key\n')
            self.assertEqual(read_value(path, ('ELEVENLABS_API_KEY',), allow_bare=True), 'bare-test-key')

    def test_switch_to_elevenlabs_does_not_reuse_siliconflow_key_or_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'; path.write_text('ELEVENLABS_API_KEY=test-eleven-only')
            env = {'FATFISH_TTS_PROVIDER': 'elevenlabs', 'FATFISH_TTS_API_KEY': 'wrong-siliconflow-key',
                   'FATFISH_TTS_BASE': 'https://siliconflow.invalid/v1', 'FATFISH_ELEVENLABS_ENV_FILE': str(path)}
            with patch.dict(os.environ, env, clear=True), patch.object(tts, 'managed_voice', return_value={}):
                config = tts.TTSConfig.from_env()
            self.assertEqual(config.api_key, 'test-eleven-only')
            self.assertEqual(config.api_base, 'https://api.elevenlabs.io/v1')
            self.assertEqual(config.model, 'eleven_multilingual_v2')

    def test_saved_dsh_provider_selection_controls_the_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'; path.write_text('ELEVENLABS_API_KEY=test-eleven-only')
            settings={'provider':'elevenlabs','providers':{'elevenlabs':{'voiceId':'chosen-voice','speed':.9,'envFile':str(path)}}}
            with patch.dict(os.environ,{'FATFISH_TTS_PROVIDER':'siliconflow','FATFISH_TTS_API_KEY':'unrelated'},clear=True),patch.object(tts,'managed_voice',return_value=settings):
                config=tts.TTSConfig.from_env()
            self.assertEqual((config.provider,config.voice,config.speed),('elevenlabs','chosen-voice',.9))
            self.assertEqual(config.api_key,'test-eleven-only')

    def test_elevenlabs_pcm_is_wrapped_as_valid_wav_with_correct_auth(self):
        config = tts.TTSConfig('test-eleven-only', provider='elevenlabs', api_base='https://api.elevenlabs.io/v1',
                               model='eleven_multilingual_v2', voice='voice-id', speed=1)
        def post(request, **kwargs):
            self.assertEqual(request.get_header('Xi-api-key'), 'test-eleven-only')
            self.assertIsNone(request.get_header('Authorization'))
            self.assertIn('/text-to-speech/voice-id?output_format=pcm_24000', request.full_url)
            self.assertEqual(json.loads(request.data)['model_id'], 'eleven_multilingual_v2')
            return Response(b'\x00\x00'*100)
        with patch.object(tts.urllib.request, 'urlopen', side_effect=post):
            audio = tts.synth(config, '苹果派')
        with wave.open(io.BytesIO(audio), 'rb') as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getnframes()), (24000, 1, 100))

    def test_minimax_business_status_and_hex_are_validated(self):
        config = tts.TTSConfig('minimax-test', provider='minimax', api_base='https://api.minimax.io/v1', model='speech-2.8-hd', voice='test', speed=1)
        def post(request, **kwargs):
            self.assertEqual(request.get_header('Authorization'), 'Bearer minimax-test')
            self.assertEqual(json.loads(request.data)['audio_setting']['format'], 'wav')
            return Response(json.dumps({'base_resp': {'status_code': 0}, 'data': {'audio': b'RIFFtest'.hex()}}).encode())
        with patch.object(tts.urllib.request, 'urlopen', side_effect=post):
            self.assertTrue(tts.synth(config, '苹果派').startswith(b'RIFF'))
        with patch.object(tts.urllib.request, 'urlopen', return_value=Response(b'{"base_resp":{"status_code":1004}}')):
            with self.assertRaises(tts.TTSError): tts.synth(config, '苹果派')

    def test_provider_speed_limits_fail_before_network(self):
        config = tts.TTSConfig('test', provider='elevenlabs', voice='test', speed=1.3)
        with patch.object(tts.urllib.request,'urlopen',side_effect=AssertionError('network')):
            with self.assertRaises(tts.TTSError): tts.synth(config, '苹果派')

    def test_backend_errors_do_not_echo_response_credentials(self):
        config = tts.TTSConfig('test', voice='test')
        error = urllib.error.HTTPError('https://example.invalid',401,'Unauthorized',{},io.BytesIO(b'echo-secret-test'))
        with patch.object(tts.urllib.request,'urlopen',side_effect=error):
            with self.assertRaises(tts.TTSError) as caught: tts.synth(config, '苹果派')
        self.assertNotIn('echo-secret-test', str(caught.exception))
