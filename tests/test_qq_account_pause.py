import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class QQAccountPauseTests(unittest.TestCase):
    def test_mcp_pause_prevents_http_and_quota_updates(self):
        source = ROOT / 'dsh/service/fatfish_memory_mcp.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        names = {'_qq_account_paused', '_qzone_call', 'qzone_post', 'qzone_delete'}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in functions:
            node.decorator_list = []
        network = Mock(side_effect=AssertionError('network must not run'))
        quota = Mock(side_effect=AssertionError('quota must not update'))
        namespace = {'__file__': str(source), 'Path': Path, 'os': os, 'json': json,
                     '_dump': json.dumps, '_autonomy': quota, 'urlopen': network, 'Request': network}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
        with tempfile.TemporaryDirectory(prefix='qq-pause-') as directory:
            marker = Path(directory) / 'pause'
            marker.write_text('manual review', encoding='utf-8')
            with patch.dict(os.environ, {'FATFISH_QQ_PAUSE_FILE': str(marker), 'FATFISH_QZONE_WRITE': '1'}):
                self.assertTrue(namespace['_qq_account_paused']())
                self.assertEqual(json.loads(namespace['qzone_post']('test'))['error'], 'qq-account-paused')
                self.assertEqual(json.loads(namespace['qzone_delete']('fake-id'))['error'], 'qq-account-paused')
                with self.assertRaisesRegex(RuntimeError, 'qq-account-paused'):
                    namespace['_qzone_call']('get_emotion_list')
                network.assert_not_called()
                quota.assert_not_called()
                marker.unlink()
                self.assertFalse(namespace['_qq_account_paused']())
