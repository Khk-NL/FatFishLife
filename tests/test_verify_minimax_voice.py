import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

from scripts import verify_minimax_voice as module


class MiniMaxSampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_has_three_fixed_texts_and_never_loads_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clone.json'
            path.write_text(json.dumps({'clone_state':'accepted','authorized':True,'voice_id':'AppleLeTest2026','budget_cny':10}))
            args=types.SimpleNamespace(clone_receipt=path,apply=False)
            with patch.object(module.importlib,'import_module') as imported:
                report=await module.verify(args)
                imported.assert_not_called()
            self.assertEqual(report['calls'],0)
            self.assertEqual(len(module.TEXTS),3)
            self.assertAlmostEqual(report['estimated_total_cny'],9.92765)
            self.assertEqual(module.billed_characters('老板!'),5)
            path.write_text(json.dumps({'clone_state':'accepted','authorized':True,'budget_cny':9.92}))
            with self.assertRaises(ValueError):await module.verify(args)

    async def test_unaccepted_or_unauthorized_clone_is_rejected_before_any_api(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clone.json';path.write_text(json.dumps({'clone_state':'submitted','authorized':True}))
            with self.assertRaises(ValueError):await module.verify(types.SimpleNamespace(clone_receipt=path,apply=True))

    async def test_encoder_checks_real_format_rate_and_channels(self):
        def result(rate):
            return Mock(stdout=json.dumps({'streams':[{'codec_type':'audio','codec_name':'mp3','sample_rate':str(rate),'channels':1}]}).encode())
        with patch.object(module,'_resolve_tool',return_value=Path('ffprobe')),patch.object(module.subprocess,'run',return_value=result(32000)):
            module.verify_encoding(Path('sample.mp3'))
        with patch.object(module,'_resolve_tool',return_value=Path('ffprobe')),patch.object(module.subprocess,'run',return_value=result(24000)):
            with self.assertRaises(ValueError):module.verify_encoding(Path('sample.mp3'))
