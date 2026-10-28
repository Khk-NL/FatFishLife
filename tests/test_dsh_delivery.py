import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from fatfish_core.delivery import DeliveryPolicy
from fatfish_core import tts
from scripts.dsh_behavior_snapshot import snapshot

SCOPE = json.dumps(['qq', 'napcat', '1', 'group:2'])
CONFIG = {'voice': {'enabled': True, 'base': .15, 'step': 0, 'max': 1},
          'meme': {'enabled': True, 'base': .35, 'step': .1, 'max': .9, 'manual_trigger': True}}


class DeliveryTests(unittest.TestCase):
    def test_progression_depends_on_actual_receipt(self):
        policy = DeliveryPolicy(copy.deepcopy(CONFIG), rng=Mock(random=lambda: .99))
        first = policy.prepare(SCOPE, '苹果派真好吃', '')
        self.assertEqual(first['voice']['probability'], .15)
        self.assertEqual(first['meme']['probability'], .35)
        policy.finish(first['id'], replied=True)
        next_plan = policy.prepare(SCOPE, '苹果派真好吃', '给我表情包')
        self.assertAlmostEqual(next_plan['meme']['probability'], .45)
        self.assertTrue(next_plan['meme']['hit'])
        policy.finish(next_plan['id'], replied=True, meme_sent=True)
        self.assertEqual(policy.prepare(SCOPE, '苹果派真好吃', '')['meme']['probability'], .35)

    def test_cancelled_muted_reply_does_not_increment_or_reset(self):
        policy = DeliveryPolicy(copy.deepcopy(CONFIG), rng=Mock(random=lambda: .99))
        plan = policy.prepare(SCOPE, '苹果派', '')
        policy.finish(plan['id'], replied=False)
        self.assertEqual(policy.prepare(SCOPE, '苹果派', '')['meme']['probability'], .35)
        self.assertFalse(policy.finish(plan['id'], replied=True)['recorded'])

    def test_ceilings_and_conversations_are_separate(self):
        policy = DeliveryPolicy(copy.deepcopy(CONFIG), rng=Mock(random=lambda: .99))
        for _ in range(12):
            plan = policy.prepare(SCOPE, '苹果派', '')
            policy.finish(plan['id'], replied=True)
        self.assertEqual(policy.prepare(SCOPE, '苹果派', '')['meme']['probability'], .9)
        other = json.dumps(['qq', 'napcat', '1', 'private:2'])
        self.assertEqual(policy.prepare(other, '苹果派', '')['meme']['probability'], .35)

    def test_opt_out_and_busy_have_no_random_or_media_work(self):
        rng = Mock(random=Mock(side_effect=AssertionError('must not draw')))
        policy = DeliveryPolicy(copy.deepcopy(CONFIG), rng=rng)
        plan = policy.prepare(SCOPE, '苹果派', '不要语音，不要表情包')
        self.assertFalse(plan['voice']['hit']); self.assertFalse(plan['meme']['hit'])
        plan = policy.prepare(SCOPE, '忙着送快递', '', active=False)
        self.assertFalse(plan['voice']['eligible']); self.assertFalse(plan['meme']['eligible'])

    def test_cooldown_starts_on_confirmed_voice_only(self):
        cfg = copy.deepcopy(CONFIG); cfg['voice']['cooldown_seconds'] = 180
        policy = DeliveryPolicy(cfg, rng=Mock(random=lambda: 0), clock=lambda: 1000)
        failed = policy.prepare(SCOPE, '苹果派', '')
        policy.finish(failed['id'], replied=True, voice_sent=False)
        sent = policy.prepare(SCOPE, '苹果派', '')
        self.assertTrue(sent['voice']['eligible'])
        policy.finish(sent['id'], replied=True, voice_sent=True)
        self.assertFalse(policy.prepare(SCOPE, '苹果派', '')['voice']['eligible'])

    def test_native_snapshot_ignores_stale_router_and_preserves_disabled_plugin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'config').mkdir()
            for name in ('meme_manager', 'astrbot_plugin_proactive_chat', 'astrbot_plugin_fatfish_life'):
                (root/'plugins'/name).mkdir(parents=True)
            native = {'provider_tts_settings': {'enable': True, 'trigger_probability': .15, 'dual_output': False}, 'api_key': 'must-never-export'}
            configs = {'meme_manager': {'generation': {'emotion': {'probability': 35, 'probability_step': 10, 'probability_max': 90}}},
                       'astrbot_plugin_fatfish_life': {'enabled': True, 'publish_enabled': True}, 'astrbot_plugin_fatfish_bili': {}}
            (root/'cmd_config.json').write_text(json.dumps(native))
            for name, value in configs.items(): (root/'config'/f'{name}_config.json').write_text(json.dumps(value))
            connection = sqlite3.connect(root/'data_v4.db')
            connection.execute('create table preferences(scope,scope_id,key,value)')
            connection.execute('insert into preferences values (?,?,?,?)', ('global','global','inactivated_plugins',json.dumps({'val':['data.plugins.astrbot_plugin_proactive_chat.main']})))
            connection.commit(); connection.close()
            result = snapshot(root)
            self.assertEqual(result['voice']['base'], .15)
            self.assertFalse(result['proactive']['enabled'])
            self.assertNotIn('must-never-export', json.dumps(result))

    def test_audio_conversion_rejects_failed_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); decoder = root/'ffmpeg.exe'; decoder.touch()
            source = root/'source.wav'; source.write_bytes(b'RIFF-not-valid')
            with patch.object(tts.subprocess, 'run', return_value=Mock(returncode=1)):
                with self.assertRaises(tts.TTSError): tts.normalize_wav(tts.TTSConfig('test',ffmpeg=str(decoder)),source,root/'out.wav')

    def test_streaming_audio_decoder_ignores_placeholder_lengths_and_checks_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); decoder = root/'ffmpeg.exe'; decoder.touch()
            target = root/'out.wav'
            def convert(args, **kwargs):
                self.assertIn('-ignore_length', args)
                with wave.open(str(target),'wb') as audio:
                    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000); audio.writeframes(b'\x00\x00'*100)
                return Mock(returncode=0)
            with patch.object(tts.subprocess,'run',side_effect=convert):
                self.assertEqual(tts.normalize_wav(tts.TTSConfig('test',ffmpeg=str(decoder)),root/'source.wav',target), target)
