import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { postThought, qzoneStatus } from '../control/qzone.mjs'

async function withBridge(handler, action) {
  const server = createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  try { await action(`http://127.0.0.1:${server.address().port}`) }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)) }
}

test('QQ空间JSON传输逐字保留中文和颜文字，鉴权不进入正文', async () => {
  const text = '在试说说这个按钮通不通 (｡•̀ᴗ-)✧ 通的话以后就常来了 🐳'
  await withBridge(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const raw = Buffer.concat(chunks)
    assert.match(req.headers['content-type'], /charset=utf-8/)
    assert.equal(req.headers.authorization, 'Bearer test-only-token')
    assert.equal(JSON.parse(raw.toString('utf8')).message[0].data.text, text)
    assert.equal(raw.includes(Buffer.from('test-only-token')), false)
    res.end(JSON.stringify({ status: 'ok', retcode: 0, data: { tid: 'local-receipt' } }))
  }, async base => {
    const result = await postThought(text, { base, token: 'test-only-token' })
    assert.equal(result.tid, 'local-receipt')
    assert.equal(result.text, text)
  })
})

test('HTTP或业务失败不能仅凭tid误报发布成功，异常正文不回显', async () => {
  let mode = 'business'
  await withBridge((req, res) => {
    if (mode === 'http') { res.statusCode = 500; res.end('private-error-body'); return }
    if (mode === 'invalid') { res.end('private-error-body'); return }
    res.end(JSON.stringify({ status: 'ok', retcode: 1401, data: { tid: 'not-success' } }))
  }, async base => {
    assert.equal((await postThought('业务失败', { base, token: '' })).ok, false)
    assert.equal((await qzoneStatus({ base, token: '' })).online, false)
    for (mode of ['http', 'invalid']) {
      const result = await postThought('异常测试', { base, token: '' })
      assert.equal(result.ok, false)
      assert.equal(result.reason.includes('private-error-body'), false)
    }
  })
})

test('超时结果标为未知且不重试，阻止已经损坏的文字再次发布', async () => {
  let requests = 0
  await withBridge((req, res) => { requests++; setTimeout(() => res.end('{}'), 50) }, async base => {
    const result = await postThought('超时测试', { base, token: '', timeoutMs: 10 })
    assert.equal(result.ok, false)
    assert.equal(result.unknown, true)
    assert.equal(result.reason, 'publish-timeout-result-unknown')
    assert.ok(requests <= 1)
    const before = requests
    assert.equal((await postThought('损坏\uFFFD文字', { base, token: '' })).reason, 'invalid-text-encoding')
    assert.equal(requests, before)
  })
})

test('定时出口复用桥私有token文件，HTTP200但登录失效仍准确返回', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'qzone-auth-'))
  const tokenFile = join(dir, 'test.env')
  writeFileSync(tokenFile, 'QZONE_COOKIE_STRING=not-used\nFATFISH_QZONE_ACCESS_TOKEN=test-file-token\n')
  try {
    await withBridge((req, res) => {
      assert.equal(req.headers.authorization, 'Bearer test-file-token')
      res.end(JSON.stringify({ status: 'ok', retcode: 0, data: { valid: false, expired: true } }))
    }, async base => {
      const result = await qzoneStatus({ base, tokenFile })
      assert.equal(result.online, true)
      assert.equal(result.valid, false)
      assert.equal(result.expired, true)
    })
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
