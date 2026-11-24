import assert from 'node:assert/strict';
import test from 'node:test';
import { feishuLinks, readFeishuDocument } from '../feishu-docs.mjs';

const link = 'https://team.feishu.cn/wiki/WikiFixture01';

test('reads a wiki node and the matching latest document body using only official API requests', async () => {
  const requests = [];
  const result = await readFeishuDocument(link, { ready: async () => {}, async request(path, params) {
    requests.push([path, params]);
    return path.endsWith('get_node')
      ? { ok: true, data: { node: { obj_type: 'docx', obj_token: 'DocxFixture01' } } }
      : { ok: true, data: { content: '三项待办' } };
  } });
  assert.deepEqual(requests, [
    ['/open-apis/wiki/v2/spaces/get_node', { token: 'WikiFixture01' }],
    ['/open-apis/docx/v1/documents/DocxFixture01/raw_content', null],
  ]);
  assert.deepEqual(result, { ok: true, source: link, content: '三项待办', truncated: false });
});

test('extracts only Feishu document links and stops after permission failure or an unsupported node', async () => {
  const alien = 'https://team.feishu.cn.example.org/wiki/WikiFixture01';
  assert.deepEqual(feishuLinks(`${alien} [请读](${link}?from=copy) ${link}`), [link]);
  const denied = { ok: false, reason: '无页面权限' };
  for (const first of [denied, { ok: true, data: { node: { obj_type: 'bitable', obj_token: 'DocxFixture01' } } }]) {
    let calls = 0;
    const outcome = await readFeishuDocument(link, { ready: async () => {}, async request() { calls++; return first; } });
    assert.equal(outcome.ok, false);
    assert.equal(calls, 1);
  }
});
