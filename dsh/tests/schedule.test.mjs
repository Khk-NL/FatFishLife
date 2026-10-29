import { test } from 'node:test'
import assert from 'node:assert/strict'

import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { TASKS, dueTasks, minutesOfDay, nextRun, scheduledFor, DEFAULT_GRACE_MINUTES, readState, writeState, statePath } from '../control/schedule.mjs'

const at = (hhmmss) => {
  const [h, m, s = '00'] = hhmmss.split(':')
  return new Date(2026, 9, 29, Number(h), Number(m), Number(s))
}

test('时间解析接受 HH:MM 并拒绝越界', () => {
  assert.equal(minutesOfDay('12:30'), 750)
  assert.equal(minutesOfDay('00:00'), 0)
  assert.throws(() => minutesOfDay('24:00'))
  assert.throws(() => minutesOfDay('12:60'))
  assert.throws(() => minutesOfDay('1230'))
})

test('scheduledFor 落在当天同一时刻', () => {
  const target = scheduledFor(at('09:00'), '12:30')
  assert.equal(target.getDate(), 29)
  assert.equal(target.getHours(), 12)
  assert.equal(target.getMinutes(), 30)
  assert.equal(target.getSeconds(), 0)
})

test('到点才触发，提前一分钟不触发', () => {
  assert.equal(dueTasks(at('12:29')).length, 0)
  const due = dueTasks(at('12:30'))
  assert.equal(due.length, 1)
  assert.equal(due[0].id, 'bili-recommend-noon')
  assert.equal(due[0].lateMinutes, 0)
})

test('宽限期内的迟到仍会触发', () => {
  const due = dueTasks(at('13:00'))
  assert.equal(due.length, 1)
  assert.equal(due[0].lateMinutes, 30)
})

test('超过宽限期不补跑（停机一夜不会一次性放出所有任务）', () => {
  // 12:30 的任务到 14:30 已迟到 120 分钟，超过默认 60 分钟宽限
  assert.equal(dueTasks(at('14:30')).length, 0)
  // 而 60 分钟整点仍算在宽限内
  const edge = new Date(scheduledFor(at('12:30'), '12:30').getTime() + DEFAULT_GRACE_MINUTES * 60000)
  assert.equal(dueTasks(edge).length, 1)
})

test('同一天跑过就不再跑', () => {
  const due = dueTasks(at('12:35'), { lastRun: { 'bili-recommend-noon': at('12:31') } })
  assert.equal(due.length, 0)
})

test('昨天的记录不会挡住今天的任务', () => {
  const yesterday = new Date(2026, 9, 28, 12, 31, 0)
  const due = dueTasks(at('12:35'), { lastRun: { 'bili-recommend-noon': yesterday } })
  assert.equal(due.length, 1)
})

test('23:50 的两个任务在同一天互不干扰', () => {
  const due = dueTasks(at('23:55'))
  assert.deepEqual(due.map((d) => d.id), ['diary'])
})

test('凌晨不会误触发前一天的日记', () => {
  const due = dueTasks(at('00:10'))
  assert.equal(due.length, 0)
})

test('nextRun 返回最近的一个未来任务', () => {
  const next = nextRun(at('13:00'))
  assert.equal(next.id, 'bili-recommend-evening')
  assert.equal(next.at, '20:30')
  assert.equal(next.when.getHours(), 20)
})

test('nextRun 在当天全部结束后指向明天的第一个', () => {
  const next = nextRun(at('23:59'))
  assert.equal(next.id, 'bili-recommend-noon')
  assert.equal(next.when.getDate(), 30)
})

test('任务表与 rules.md 的四个时间点一致', () => {
  assert.deepEqual(TASKS.map((t) => t.at).sort(), ['12:30', '20:30', '21:00', '23:50'])
})
test('状态读写往返，重启后不重复触发靠它', () => {
  const dir = mkdtempSync(join(tmpdir(), 'ff-sched-'))
  try {
    assert.deepEqual(readState(dir), {})
    writeState(dir, { lastRun: { diary: '2026-10-29T15:50:00.000Z' } })
    assert.equal(readState(dir).lastRun.diary, '2026-10-29T15:50:00.000Z')
    // 写进去的记录必须能挡住当天的重复触发
    const now = new Date(2026, 9, 29, 23, 55, 0)
    assert.equal(dueTasks(now, { lastRun: readState(dir).lastRun }).length, 0)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('状态文件损坏时返回空对象而不是抛错', () => {
  const dir = mkdtempSync(join(tmpdir(), 'ff-sched-'))
  try {
    writeFileSync(statePath(dir), '{ not json')
    assert.deepEqual(readState(dir), {})
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})