import test from 'node:test'
import assert from 'node:assert/strict'
import { dynamicPost } from '../control/bili.mjs'

test('动态发布复用已有CLI，默认关闭，业务失败不误报成功且不重试', async () => {
  const calls = []
  const run = async (...args) => { calls.push(args); return { ok: true, data: { id: 'fake-only' } } }
  await assert.rejects(dynamicPost('测试', { run }), /publish-disabled/)
  assert.equal(calls.length, 0)
  await dynamicPost(' 中文与表情 🐳 ', { write: true, bin: 'fake.exe', run })
  assert.deepEqual(calls[0][0], ['dynamic', 'post', '中文与表情 🐳'])
  assert.equal(calls[0][1].timeoutMs, 180_000)
  assert.equal(calls[0][1].bin, 'fake.exe')
  await assert.rejects(dynamicPost('测试', { write: true, run: async () => ({ ok: false }) }), /未确认成功/)
})
