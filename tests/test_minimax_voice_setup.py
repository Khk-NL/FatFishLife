from pathlib import Path
import json
import tempfile
import types
import unittest
from unittest.mock import patch
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
        self.text.write_text('一致的示例文字',encoding='utf-8')
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
                      api_base='https://example.invalid',output=self.root/'receipt.json')
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
            self.assertIn(b'voice_clone',request.call_args_list[0].args[2])
            self.assertIn(b'prompt_audio',request.call_args_list[1].args[2])
            payload=json.loads(request.call_args_list[2].args[2])
            self.assertEqual(payload['clone_prompt'],{'prompt_audio':12,'prompt_text':'一致的示例文字'})
            self.assertEqual(payload['file_id'],11)
        with patch.object(module,'request') as request:
            self.assertTrue(module.run(args)['already_prepared'])
            request.assert_not_called()
