"""Offline record compatibility checks against the locked OneBot archive."""
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from scripts.prepare_dsh_onebot import inbound_record, media_record


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / '.tools/dsh-vendor/dsh-onebot-qq-0.9.6.tgz'


def upstream(name):
    with tarfile.open(ARCHIVE) as bundle:
        return bundle.extractfile('package/lib/' + name).read().decode('utf-8')


class SnowLumaPreparationTests(unittest.TestCase):
    def test_disabled_templates_match_existing_reverse_endpoint(self):
        folder = ROOT / 'dsh/templates/snowluma-v2.4.0'
        config = json.loads((folder / 'onebot.json').read_text(encoding='utf-8'))
        runtime = json.loads((folder / 'runtime.json').read_text(encoding='utf-8'))
        self.assertFalse(runtime['hookAutoLoad'])
        for entries in config['networks'].values():
            for entry in entries:
                self.assertFalse(entry['enabled'])
                self.assertEqual(entry['accessToken'], '')
                self.assertEqual(entry['messageFormat'], 'array')
                if 'host' in entry:
                    self.assertEqual(entry['host'], '127.0.0.1')
        client = config['networks']['wsClients'][0]
        self.assertEqual(client['url'], 'ws://127.0.0.1:8646/ws')
        self.assertEqual(client['role'], 'Universal')

    def test_patch_requires_exact_upstream_anchor(self):
        for transform, name in ((inbound_record, 'inbound.js'), (media_record, 'media.js')):
            source = upstream(name)
            self.assertNotEqual(transform(source), source)
            with self.assertRaises(RuntimeError):
                transform('unrecognized upstream')
            with self.assertRaises(RuntimeError):
                transform(source + source)

    def test_mock_records_use_existing_bounded_media_path(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / 'package.json').write_text('{"type":"module"}', encoding='utf-8')
            for name in ('inbound.js', 'media.js', 'stt.js', 'cq.js', 'chat.js', 'errors.js', 'trace.js'):
                source = upstream(name)
                if name == 'inbound.js':
                    source = inbound_record(source)
                elif name == 'media.js':
                    source = media_record(source)
                (target / name).write_text(source, encoding='utf-8')
            # Image rendering is outside this voice contract; do not load native canvas.
            (target / 'image-shrink.js').write_text(
                "export async function shrinkImage() { throw new Error('image path must not run'); }",
                encoding='utf-8',
            )
            script = r"""
import assert from 'node:assert/strict';
import { readFile, writeFile, readdir, stat, utimes } from 'node:fs/promises';
import { join } from 'node:path';
import { MediaStore, VOICE_MAX_BYTES } from './media.js';
import { InboundPipeline } from './inbound.js';

globalThis.fetch = async () => { throw new Error('no network allowed'); };
const scratch = join(process.cwd(), 'scratch');
const store = new MediaStore(scratch, 6, 0, { maxBytes: 64 });
const bytes = Buffer.from('ID3-mock-converted-mp3');
let response;
let resolved;
let calls = 0;
const pipeline = new InboundPipeline({
    call: async (action, params) => {
        calls++;
        assert.equal(action, 'get_record');
        assert.deepEqual(params, { file: 'record-hash', out_format: 'mp3' });
        return response;
    },
    media: { resolve: async (...args) => { resolved = await store.resolve(...args); return resolved; } },
    transcriber: { enabled: false },
    log: () => {},
});
const resolve = () => pipeline.resolveMediaRef({ kind: 'voice', file: 'record-hash' }, 'private:10000002');

response = { file: 'original-source.silk', url: 'http://127.0.0.1/source.silk', out_format: 'mp3', base64: bytes.toString('base64') };
assert.equal(await resolve(), '[语音]');
assert.ok(resolved.path.endsWith('.mp3'));
assert.ok(resolved.path.startsWith(scratch));
assert.deepEqual(await readFile(resolved.path), bytes);
assert.equal(calls, 1);
// The existing TTL cleanup owns converted files, and leaves unrelated files alone.
await utimes(resolved.path, new Date(0), new Date(0));
await writeFile(join(scratch, 'state.json'), '{}');
await store.cleanupExpired();
await assert.rejects(stat(resolved.path), { code: 'ENOENT' });
assert.equal(await readFile(join(scratch, 'state.json'), 'utf8'), '{}');

const before = await readdir(scratch);
for (const bad of [
    { out_format: 'mp3', base64: Buffer.alloc(65).toString('base64') },
    { out_format: 'mp3', base64: 'invalid!base64===' },
    { out_format: 'mp3', base64: 'AAA' },
    { out_format: 'wav', base64: bytes.toString('base64') },
]) {
    response = { ...bad, file: 'original.silk', url: 'http://127.0.0.1/must-not-fallback' };
    assert.equal(await resolve(), '');
    assert.equal(resolved, undefined);
}
assert.deepEqual(await readdir(scratch), before);
// Disabling the generic download cap must not remove the voice payload cap.
store.downloadMaxBytes = 0;
response = { out_format: 'mp3', base64: 'A'.repeat(4 * Math.ceil(VOICE_MAX_BYTES / 3) + 4) };
assert.equal(await resolve(), '');
assert.deepEqual(await readdir(scratch), before);
store.downloadMaxBytes = 64;

// NapCat file:// replies retain their original copy-to-scratch behavior.
const napcatPath = join(process.cwd(), 'napcat.mp3');
await writeFile(napcatPath, bytes);
response = { file: 'file://' + napcatPath };
assert.equal(await resolve(), '[语音]');
assert.deepEqual(await readFile(resolved.path), bytes);

// A URL-only reply reaches the existing downloader and its SSRF fence.
response = { url: 'http://127.0.0.1/not-allowed', file: 'source.silk' };
assert.equal(await resolve(), '');
assert.equal(resolved, undefined);
console.log('record contracts passed');
"""
            (target / 'check.mjs').write_text(script, encoding='utf-8')
            result = subprocess.run(
                [shutil.which('node') or 'node', str(target / 'check.mjs')],
                cwd=target, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('record contracts passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
