"""Offline security contracts; all records and command effects are synthetic."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from fatfish_core import MemoryStore
from scripts.prepare_dsh_onebot import replace


ROOT = Path(__file__).resolve().parents[1]


class SocialSecurityTests(unittest.TestCase):
    def test_guard_requires_private_owner_for_a_private_memory_query(self):
        # Execute the actual MCP wrapper against a disposable DB, without loading MCP.
        source = (ROOT / 'dsh/service/fatfish_memory_mcp.py').read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'recall')
        node.decorator_list = []
        with tempfile.TemporaryDirectory() as folder:
            memory = MemoryStore(Path(folder) / 'memory.db')
            memory.remember('SYNTHETIC_PRIVATE_MARKER', scope='private', platform='qq', session='private:2', kind='note')
            namespace = {'store': lambda: memory, '_limit': lambda value: value, '_dump': json.dumps}
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-recall-wrapper', 'exec'), namespace)
            rows = json.loads(namespace['recall']('SYNTHETIC_PRIVATE_MARKER', scope='private'))
            self.assertEqual(len(rows), 1)  # Backend can return private data; the caller guard is required.
            script = """
import assert from 'node:assert/strict';
import { FatFishPolicy } from './dsh/policy.mjs';
const policy = new FatFishPolicy({ botId: '1', ownerId: '2', adapterId: 'mock', silent: false }, { accountPaused: () => false });
const exec = { name: 'mcp__fatfish__recall', arguments: { scope: 'private', query: 'synthetic' } };
assert.ok(policy.toolDenial(exec, 'group:4', ['recall']));
assert.ok(policy.toolDenial(exec, 'private:8', ['recall']));
assert.equal(policy.toolDenial(exec, 'private:2', ['recall']), undefined);
"""
            self.run_node(script)

    def test_generated_command_entry_rejects_group_owner_before_routing(self):
        # Compile the existing packaging transform itself, so the check is not a parallel router.
        tree = ast.parse((ROOT / 'scripts/prepare_dsh_onebot.py').read_text(encoding='utf-8'))
        prepare = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare')
        bridge = next(n for n in prepare.body if isinstance(n, ast.FunctionDef) and n.name == 'bridge')
        namespace = {'replace': replace}
        exec(compile(ast.Module(body=[bridge], type_ignores=[]), 'actual-bridge-transform', 'exec'), namespace)
        with tarfile.open(ROOT / '.tools/dsh-vendor/dsh-onebot-qq-0.9.6.tgz') as bundle:
            source = bundle.extractfile('package/lib/bridge.js').read().decode('utf-8')
        generated = namespace['bridge'](source)
        start = generated.index('    tryHandleCommand(chatId, text, userId, nickname) {')
        end = generated.index('\n    /**', start)
        method = generated[start:end].strip()
        script = """
import assert from 'node:assert/strict';
let routes = 0;
let resets = 0;
const parseNewTarget = () => { resets++; return null; };
const parseModeCommand = () => null;
const routeCommand = async () => { routes++; return true; };
const object = {
  deps: { fatfishPolicy: { owner: id => id === '2', config: { ownerId: '2' } } },
  commandCtx: {},
""" + method + """
};
for (const command of ['/help', '/model --default mock mock', '/workspace', '/permission f', '/new all', '/mode 44444 quiet']) {
  assert.equal(await object.tryHandleCommand('group:4', command, '2'), false);
  assert.equal(await object.tryHandleCommand('private:8', command, '2'), false);
  assert.equal(await object.tryHandleCommand('private:2', command, '8'), false);
}
assert.equal(routes, 0);
assert.equal(resets, 0);
assert.equal(await object.tryHandleCommand('private:2', '/help', '2'), true);
assert.equal(routes, 1);
"""
        self.run_node(script)

    def run_node(self, source):
        result = subprocess.run([shutil.which('node') or 'node', '--input-type=module', '-'],
                                input=source, cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
