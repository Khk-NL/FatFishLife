import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createTaskModelBudget } from '../control/llm.mjs'
import { recordSkillEvidence } from '../control/schedule.mjs'

test('a failed model attempt exhausts only its own scheduled task budget', async () => {
  const attempts = []
  const request = async (_messages, options) => {
    attempts.push(options)
    throw new Error('provider unavailable')
  }
  const first = createTaskModelBudget('configured', request)
  assert.equal(first.calls(), 0)
  await assert.rejects(first.chat([], { thinking: true, maxTokens: 200 }), /provider unavailable/)
  await assert.rejects(first.chat([], { model: 'different' }), /background-model-budget-exhausted/)
  assert.equal(first.calls(), 1)
  assert.deepEqual(attempts, [{ model: 'configured', thinking: false, maxTokens: 200 }])
  const next = createTaskModelBudget('configured', async () => 'ok')
  assert.equal(await next.chat([]), 'ok')
  assert.equal(next.calls(), 1)
})

test('only verified task outcomes produce bounded, distinct skill evidence', () => {
  const slots = [1, 2, 3, 4].map(day => `2026-11-0${day}T12:30:00.000Z`)
  let evidence = {}
  for (const noEvidence of [{ ok: false, sent: 1 }, { ok: true, sent: 0 },
    { ok: true, sent: 1, skipped: 'paused' }]) {
    assert.equal(recordSkillEvidence(evidence, 'bili-recommend', noEvidence, slots[0]), evidence)
  }
  for (const slot of [...slots, slots[3]]) {
    evidence = recordSkillEvidence(evidence, 'bili-recommend', { ok: true, sent: 1 }, slot)
  }
  assert.deepEqual(evidence, { bili_lookup: slots.slice(1) })
})
