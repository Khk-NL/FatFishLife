import assert from 'node:assert/strict'
import test from 'node:test'
import { explainWechatStop, installWechatOwnerAgent, pinnedWechatOwner, protectedWechatContent } from '../wechat-owner-agent.mjs'

test('owner tools require a pinned identity and the current direct turn', () => {
  const read = () => JSON.stringify({ botId: 'bot-a', ownerId: 'user-a' })
  assert.equal(pinnedWechatOwner('fixture', 'bot-a', 'user-a', read), true)
  assert.equal(pinnedWechatOwner('fixture', 'bot-b', 'user-a', read), false)
  assert.equal(pinnedWechatOwner('fixture', 'bot-a', 'user-b', read), false)
  const handlers = new Map()
  let guard
  let executor
  let owner = true
  const pending = { fatfishNative: true, fatfishDirect: '整理文件', sessionId: 'private-a' }
  const tools = {
    selectExecutor: () => ({ describe: schemas => ({ schemas }), execute: input => input }),
    setExecutor: value => { executor = value },
    guard: value => { guard = value },
  }
  installWechatOwnerAgent({ get: () => tools, on: (name, callback) => handlers.set(name, callback) },
    { owner: () => owner, current: () => pending, available: () => false, onStop: () => {} })
  const call = { name: 'write', args: { path: 'test.txt' }, agent: { session: { id: 'private-a' } } }
  assert.equal(guard(call), undefined)
  assert.ok(guard({ ...call, args: { path: 'C:/do-not-read/.env' } }))
  assert.ok(guard({ ...call, agent: { session: { id: 'other' } } }))
  assert.ok(guard({ ...call, name: 'mcp__fatfish__wechat_capability_internal' }))
  assert.ok(guard({ ...call, name: 'wechat_send_file' }))
  assert.deepEqual(executor.describe([{ name: 'write' }, { name: 'wechat_send_file' }]).schemas, [{ name: 'write' }])
  pending.fatfishDirect = '把图片发给我'
  assert.equal(guard({ ...call, name: 'wechat_send_file' }), undefined)
  pending.fatfishNative = false
  assert.ok(guard(call))
  pending.fatfishNative = true
  owner = false
  assert.ok(guard(call))
  assert.equal(protectedWechatContent('密码：testfixture123'), true)
})

test('native owner turns stop repeated tool errors with a tool-free report without a step ceiling', () => {
  const handlers = new Map()
  const stops = []
  const pending = { fatfishNative: true, fatfishDirect: '用 DeskBox 做个小组件', sessionId: 'owner' }
  const prefix = 'mcp__deskbox__deskbox_'
  let guard, executor, prompt
  const tools = {
    selectExecutor: () => ({ describe: schemas => ({ schemas }) }),
    setExecutor: value => { executor = value },
    guard: value => { guard = value },
  }
  installWechatOwnerAgent({ get: name => name === 'tools' ? tools : { section: value => { prompt = value.text } },
    on: (name, callback) => handlers.set(name, callback) },
  { owner: () => true, current: () => pending, available: () => false, onStop: value => stops.push(value) })
  const next = () => 'next'
  const step = () => handlers.get('agent/pre-step')({}, next)
  for (let n = 0; n < 30; n++) assert.equal(step(), 'next')
  assert.equal(stops.length, 0)
  const agent = { session: { id: pending.sessionId } }
  assert.equal(guard({ agent, name: prefix + 'upsert_widget', args: { commit: false } }), undefined)
  assert.match(guard({ agent, name: prefix + 'upsert_widget', args: { commit: true } }), /桌面确认/u)
  const event = (type, data) => handlers.get('session/event')(agent.session, { type, data })
  const tool = prefix + 'capture_widget_preview'
  for (let n = 0; n < 2; n++) {
    event('tool/call', { callId: 'fixture' + n, name: tool })
    event('tool/result', { message: { toolCallId: 'fixture' + n, isError: true,
      content: [{ type: 'text', text: 'preview timed out' }] } })
  }
  assert.equal(step(), 'next')
  assert.match(prompt(), /timeout/u)
  assert.deepEqual(executor.describe([{ name: tool }]).schemas, [])
  assert.deepEqual(step(), { kind: 'reject' })
  assert.match(explainWechatStop(stops[0]), /DeskBox 的预览渲染连续超时/u)
  event('turn/start', {})
  assert.equal(step(), 'next')
  assert.equal(guard({ agent, name: tool, args: {} }), undefined)
})
