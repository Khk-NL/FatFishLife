// 心情同步的离线测试：只碰临时目录，不读真实 feiyu 状态、不发消息。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { applyMoodPending, feiyuPath, mergeIntoState, pendingEntries, pendingPath } from '../control/moodsync.mjs'

const sandbox = () => {
  const root = mkdtempSync(join(tmpdir(), 'fatfish-mood-'))
  const dataDir = join(root, 'data')
  const home = join(root, 'home')
  mkdirSync(dataDir, { recursive: true })
  mkdirSync(join(home, '.dsh', 'feiyu-mood'), { recursive: true })
  return { root, dataDir, home, cleanup: () => rmSync(root, { recursive: true, force: true }) }
}

const writeState = (home, state) => writeFileSync(feiyuPath(home), JSON.stringify(state), 'utf8')
const readState = home => JSON.parse(readFileSync(feiyuPath(home), 'utf8'))
const baseState = () => ({
  moods: {
    'dsh-onebot:private:3124904460': { mood: 72, dims: {}, lastReason: '老大夸我了', updatedAt: 1, timeline: [] },
    __default__: { mood: 70, dims: {}, lastReason: '', updatedAt: 1, timeline: [] },
  },
  lastActive: 'dsh-onebot:private:3124904460',
})

test('pendingEntries 认数组也认 {entries}', () => {
  assert.deepEqual(pendingEntries([{ value: 1 }]), [{ value: 1 }])
  assert.deepEqual(pendingEntries({ entries: [{ value: 2 }] }), [{ value: 2 }])
  assert.deepEqual(pendingEntries(null), [])
  assert.deepEqual(pendingEntries({ nope: 1 }), [])
})

test('mergeIntoState 改当前会话并留痕', () => {
  const state = baseState()
  assert.equal(mergeIntoState(state, { value: 64.5, reason: '被夸了', at: 1700000000000 }), true)
  const bucket = state.moods['dsh-onebot:private:3124904460']
  assert.equal(bucket.mood, 64.5)
  assert.equal(bucket.lastReason, '被夸了')
  assert.equal(bucket.updatedAt, 1700000000000)
  assert.equal(bucket.timeline.length, 1)
  assert.equal(bucket.timeline[0].mood, 64.5)
})

test('mergeIntoState 越界收拢到 0-100，结构不对返回 false', () => {
  const state = baseState()
  mergeIntoState(state, { value: 180 })
  assert.equal(state.moods['dsh-onebot:private:3124904460'].mood, 100)
  mergeIntoState(state, { value: -20 })
  assert.equal(state.moods['dsh-onebot:private:3124904460'].mood, 0)
  assert.equal(mergeIntoState({}, { value: 10 }), false)
  assert.equal(mergeIntoState(baseState(), { reason: '没数值' }), false)
})

test('applyMoodPending 把队列落盘并删掉队列文件', async () => {
  const box = sandbox()
  try {
    writeState(box.home, baseState())
    writeFileSync(pendingPath(box.dataDir), JSON.stringify([
      { value: 66, reason: '第一条', at: 1700000000000 },
      { value: 58, reason: '第二条', at: 1700000001000 },
    ]), 'utf8')
    const outcome = await applyMoodPending({ dataDir: box.dataDir, home: box.home })
    assert.equal(outcome.applied, 2)
    const state = readState(box.home)
    assert.equal(state.moods['dsh-onebot:private:3124904460'].mood, 58)
    assert.equal(state.moods['dsh-onebot:private:3124904460'].lastReason, '第二条')
    assert.equal(state.moods.__default__.mood, 70)
    assert.equal(existsSync(pendingPath(box.dataDir)), false)
  } finally {
    box.cleanup()
  }
})

test('applyMoodPending 没有队列/没有真源时安静返回', async () => {
  const box = sandbox()
  try {
    const missing = await applyMoodPending({ dataDir: box.dataDir, home: box.home })
    assert.equal(missing.applied, 0)
    assert.equal(missing.skipped, 'no-pending')
    writeFileSync(pendingPath(box.dataDir), JSON.stringify([{ value: 40 }]), 'utf8')
    const noState = await applyMoodPending({ dataDir: box.dataDir, home: box.home })
    assert.equal(noState.skipped, 'no-state')
    // 真源缺失时队列要留着，等插件写出来再合
    assert.equal(existsSync(pendingPath(box.dataDir)), true)
  } finally {
    box.cleanup()
  }
})
