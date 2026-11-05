import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, unlinkSync, rmdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { FatFishPolicy } from '../policy.mjs'
import { assertOutbound, ownerCommand } from '../runtime-adapter.mjs'
import { sendText } from '../control/transport.mjs'
import { postThought, qzoneStatus } from '../control/qzone.mjs'
import { runBiliDynamic, runBiliRecommend, runQzoneThought } from '../control/business.mjs'
import { runProactive } from '../control/proactive.mjs'

test('账号暂停实时阻止入站、工具、主动消息、空间及已排队发送，保留独立B站任务', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'fatfish-account-pause-'))
  const marker = join(directory, 'pause')
  const previous = process.env.FATFISH_QQ_PAUSE_FILE
  process.env.FATFISH_QQ_PAUSE_FILE = marker
  try {
    const policy = new FatFishPolicy({ adapterId: 'test', botId: '1', ownerId: '2', silent: false })
    assert.equal(policy.canSend(), true)
    writeFileSync(marker, 'manual review; no expiry')
    assert.equal(policy.canSend(), false)
    assert.equal(policy.decide({ self_id: 1, user_id: 2, message: '/resume' }, {}).reason, 'qq-account-paused')
    assert.throws(() => assertOutbound(policy, 'send_private_msg'), /paused/)
    await ownerCommand(policy, async () => {
      assert.throws(() => assertOutbound(policy, 'send_private_msg'), /paused/,
        'an in-flight owner command must not bypass the account pause')
      assert.doesNotThrow(() => assertOutbound(policy, 'get_status'))
    })
    assert.doesNotThrow(() => assertOutbound(policy, 'get_status'))
    assert.ok(policy.toolDenial({ name: 'web_search' }, 'private:2', ['web_search']))
    assert.equal((await sendText({ get() { throw new Error('must not access transport') } }, 'private:2', '排队的消息')).reason, 'qq-account-paused')
    assert.equal((await postThought('不能发', { base: 'http://127.0.0.1:1', token: '' })).reason, 'qq-account-paused')
    assert.equal((await qzoneStatus({ base: 'http://127.0.0.1:1', token: '' })).reason, 'qq-account-paused')
    assert.equal((await runProactive({})).reason, 'qq-account-paused')
    assert.equal((await runQzoneThought({})).skipped, 'qq-account-paused')
    assert.equal((await runBiliRecommend({})).skipped, 'qq-account-paused')
    let posted = 0
    const bili = await runBiliDynamic({ config: { workflows: { daily: { publishEnabled: true } } },
      hub: { dayDigest: async () => ({}), moodGet: async () => ({}) },
      llm: { chat: async () => '假依赖，无网络测试' },
      bili: { dynamicPost: async () => { posted++; return { ok: true } } } })
    assert.equal(bili.ok, true)
    assert.equal(posted, 1)
    unlinkSync(marker)
    assert.equal(policy.canSend(), true)
  } finally {
    if (previous === undefined) delete process.env.FATFISH_QQ_PAUSE_FILE
    else process.env.FATFISH_QQ_PAUSE_FILE = previous
    try { unlinkSync(marker) } catch (error) { if (error.code !== 'ENOENT') throw error }
    rmdirSync(directory)
  }
})
