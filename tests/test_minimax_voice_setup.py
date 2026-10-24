from pathlib import Path
import json
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
import wave

from scripts import prepare_minimax_voice as module


class MiniMaxPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.audio('reference.wav', 12)
        self.prompt = self.audio('prompt.wav', 3)
        self.text = self.root/'prompt.txt'
        self.text.write_text('一致的示例文字。',encoding='utf-8')
        self.env = self.root/'.env'
        self.env.write_text('FATFISH_MINIMAX_KEY=test-local-key\n',encoding='utf-8')

    def audio(self, name, duration):
        path=self.root/name
        with wave.open(str(path),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(8000)
            output.writeframes(b'\0\0' * int(duration * 8000))
        return path

    def args(self, **values):
        defaults=dict(env_file=self.env,reference=self.reference,voice_id='FatFishTest2026',
                      prompt_audio=None,prompt_text_file=None,apply=False,
                      api_base='https://api.minimax.cn',output=self.root/'receipt.json',
                      authorized=True,budget_cny=10)
        defaults.update(values)
        return types.SimpleNamespace(**defaults)

    def test_main_and_optional_example_have_different_duration_requirements(self):
        module.validate(self.reference,'FatFishTest2026')
        module.validate(self.prompt,'FatFishTest2026',prompt=True)
        with self.assertRaises(ValueError):module.validate(self.prompt,'FatFishTest2026')
        with self.assertRaises(ValueError):module.validate(self.audio('eight.wav',8),'FatFishTest2026',prompt=True)

    def test_preview_never_uploads_and_missing_transcript_is_rejected(self):
        with patch.object(module,'request') as request:
            result=module.run(self.args(prompt_audio=self.prompt,prompt_text_file=self.text))
            self.assertTrue(result['optional_prompt_ready'])
            self.assertNotIn('test-local-key',str(result))
            request.assert_not_called()
        with self.assertRaises(ValueError):module.run(self.args(prompt_audio=self.prompt))

    def test_upload_purposes_and_matching_text_reach_existing_clone_endpoint(self):
        args=self.args(prompt_audio=self.prompt,prompt_text_file=self.text,apply=True)
        responses=[{'base_resp':{'status_code':0},'file':{'file_id':11}},
                   {'base_resp':{'status_code':0},'file':{'file_id':12}},
                   {'base_resp':{'status_code':0},'demo_audio':'https://example.invalid/preview'}]
        with patch.object(module,'request',side_effect=responses) as request:
            result=module.run(args)
            self.assertTrue(result['clone_accepted'])
            self.assertEqual(request.call_args_list[0].kwargs['purpose'],'voice_clone')
            self.assertEqual(request.call_args_list[1].kwargs['purpose'],'prompt_audio')
            payload=request.call_args_list[2].kwargs['payload']
            self.assertEqual(payload['clone_prompt'],{'prompt_audio':12,'prompt_text':'一致的示例文字。'})
            self.assertEqual(payload['file_id'],11)
            self.assertFalse(payload['need_noise_reduction'])
            self.assertFalse(payload['need_volume_normalization'])
            for field in ('text','model','text_validation','accuracy'):
                self.assertNotIn(field,payload)
        with patch.object(module,'request') as request:
            self.assertTrue(module.run(args)['already_prepared'])
            request.assert_not_called()

    def test_authorization_budget_and_prompt_punctuation_gate_before_requests(self):
        with patch.object(module,'request') as request:
            for values in ({'authorized':False},{'budget_cny':9.89},{'api_base':'https://example.invalid'}):
                with self.assertRaises(ValueError):module.run(self.args(apply=True,**values))
            self.text.write_text('无标点文本',encoding='utf-8')
            with self.assertRaises(ValueError):module.run(self.args(prompt_audio=self.prompt,prompt_text_file=self.text))
            request.assert_not_called()

    def test_uncertain_clone_is_never_automatically_resubmitted(self):
        args=self.args(apply=True)
        with patch.object(module,'request',side_effect=[{'file':{'file_id':11}},module.MiniMaxRequestError('ReadTimeout')]) as request:
            with self.assertRaises(module.MiniMaxRequestError):module.run(args)
            self.assertEqual(request.call_count,2)
        with patch.object(module,'request') as request:
            with self.assertRaises(ValueError):module.run(args)
            request.assert_not_called()

    def test_raw_key_file_is_supported_without_leaking_the_value(self):
        self.env.write_text('test-bare-local-key\n',encoding='utf-8')
        self.assertEqual(module.read_key(self.env),'test-bare-local-key')
        self.assertNotIn('test-bare-local-key',str(module.run(self.args())))

    def test_multipart_is_encoded_by_requests_and_audit_contains_no_key(self):
        audit=[]
        def post(url, **kwargs):
            self.assertEqual(kwargs['data'],{'purpose':'voice_clone'})
            self.assertNotIn('Content-Type',kwargs['headers'])
            self.assertTrue(kwargs['files']['file'][1].read())
            return Mock(status_code=200,json=lambda:{'base_resp':{'status_code':0},'file':{'file_id':11}})
        with patch.object(module.requests,'post',side_effect=post):
            self.assertEqual(module.upload_audio(self.reference,'voice_clone','test-local-key','https://api.minimax.cn',audit=audit.append),11)
        self.assertEqual(audit[0]['http_status'],200)
        self.assertEqual(audit[0]['base_resp']['status_code'],0)
        self.assertNotIn('test-local-key',str(audit))

    def test_upload_network_retry_is_bounded_and_http_200_is_not_business_success(self):
        audit=[]
        with patch.object(module.requests,'post',side_effect=module.requests.ReadTimeout),patch.object(module.time,'sleep'):
            with self.assertRaises(module.MiniMaxRequestError):
                module.upload_audio(self.reference,'voice_clone','key','https://api.minimax.cn',audit=audit.append)
        self.assertEqual(len(audit),2)
        self.assertEqual(audit[0]['network_exception'],'ReadTimeout')
        response=Mock(status_code=200,json=lambda:{'base_resp':{'status_code':1004,'status_msg':'test-local-key denied'}})
        audit=[]
        with patch.object(module.requests,'post',return_value=response):
            with self.assertRaises(module.MiniMaxRequestError):
                module.request('https://api.minimax.cn/v1/voice_clone','test-local-key',payload={},audit=audit.append)
        self.assertEqual(audit[0]['base_resp']['status_code'],1004)
        self.assertNotIn('test-local-key',str(audit))
