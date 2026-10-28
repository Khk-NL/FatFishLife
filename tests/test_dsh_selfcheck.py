"""Migration checks distinguish local preparation, paid calls and QQ proof."""
import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from fatfish_core import tts
from scripts import dsh_selfcheck as checks


class DshSelfcheckTests(unittest.TestCase):
    def setUp(self):
        checks.results.clear()
        self.config=tts.TTSConfig(api_key='test-local-key',voice='test-voice')

    def test_deepseek_key_is_not_sent_to_unrelated_tts_provider(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'unrelated-key'},clear=True):
            self.assertEqual(tts.TTSConfig.from_env().api_key,'')

    def test_preflight_never_calls_network_or_synthesis(self):
        with patch.object(tts,'synth',side_effect=AssertionError('paid request')), patch.object(tts.urllib.request,'urlopen',side_effect=AssertionError('network')):
            result=tts.preflight(self.config)
        self.assertEqual(result['synthesis_requests'],0)
        self.assertFalse(result['synthesis_verified'])

    def test_invalid_local_parameters_are_rejected_before_any_request(self):
        for field,value in [('speed',float('nan')),('speed',5),('timeout',float('inf')),('timeout',0)]:
            config=tts.TTSConfig(api_key='test',voice='voice')
            setattr(config,field,value)
            with self.subTest(field=field,value=value),self.assertRaises(tts.TTSError):
                tts.preflight(config)

    def test_default_tts_check_reports_preparation_and_does_not_charge(self):
        with patch.object(tts.TTSConfig,'from_env',return_value=self.config),patch.object(tts,'probe',side_effect=AssertionError('paid request')):
            checks.check_tts()
        self.assertEqual(checks.results[-1]['status'],'WARN')

    def test_explicit_live_tts_check_makes_only_one_synthesis_probe(self):
        with patch.object(tts.TTSConfig,'from_env',return_value=self.config),patch.object(tts,'probe',return_value={'riff':True,'bytes':100}) as probe:
            checks.check_tts(live=True)
        probe.assert_called_once_with(self.config)
        self.assertEqual(checks.results[-1]['status'],'PASS')

    def test_mcp_check_is_local_preflight_too(self):
        source=Path('dsh/service/fatfish_memory_mcp.py').read_text(encoding='utf-8')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='tts_check')
        node.decorator_list=[]
        namespace={'TTSConfig':tts.TTSConfig,'TTSError':tts.TTSError,'tts_preflight':tts.preflight,'_dump':json.dumps}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'mcp-tts-check','exec'),namespace)
        with patch.object(tts.TTSConfig,'from_env',return_value=self.config),patch.object(tts,'synth',side_effect=AssertionError('paid request')):
            result=json.loads(namespace['tts_check']())
        self.assertFalse(result['synthesis_verified'])
        self.assertEqual(result['synthesis_requests'],0)

    def test_an_arbitrary_listening_port_cannot_pass_qq_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(checks,'PROFILE',Path(tmp)),patch('socket.socket') as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value=0
            checks.check_qq_bridge()
            self.assertEqual(checks.results[-1]['status'],'FAIL')
            (Path(tmp)/'node_modules/dsh-onebot-qq').mkdir(parents=True)
            checks.check_qq_bridge()
            self.assertEqual(checks.results[-1]['status'],'WARN')

    def test_default_local_model_check_never_sends_a_prompt(self):
        from fatfish_core import local_llm
        with patch.dict(os.environ,{'FATFISH_LOCAL_LLM_URL':'http://127.0.0.1:6193/v1'},clear=True),patch('socket.create_connection'),patch.object(local_llm,'probe',side_effect=AssertionError('model inference')):
            checks.check_local_llm()
        self.assertEqual(checks.results[-1]['status'],'WARN')

    def test_json_mode_uses_failure_exit_status(self):
        names=['check_memory','check_gallery','check_kb','check_plugins','check_preset','check_mcp_tools','check_local_llm','check_tts','check_bili','check_qq_bridge']
        patches=[patch.object(checks,name,side_effect=lambda *a,**kw:checks.check('test','WARN','prepared')) for name in names]
        for item in patches:item.start();self.addCleanup(item.stop)
        checks.check_qq_bridge.side_effect=lambda:checks.check('QQ','FAIL','unverified')
        with patch('sys.argv',['dsh_selfcheck.py','--json']),patch.object(checks,'load_env'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(checks.main(),1)
        self.assertEqual(len(json.loads(output.getvalue())),10)
        checks.check_tts.assert_called_once_with(live=False)
