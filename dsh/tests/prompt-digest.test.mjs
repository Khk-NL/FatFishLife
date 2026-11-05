import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('prompt provider refreshes growth digest after cache expiry without reimporting', async t => {
  const folder = await mkdtemp(join(tmpdir(), 'fatfish-digest-'));
  t.after(() => rm(folder, { recursive: true, force: true }));
  const oldGrowth = process.env.FATFISH_GROWTH_DIGEST;
  const oldPeak = process.env.FATFISH_PEAK_DIGEST;
  const oldJournal = process.env.FATFISH_JOURNAL_DIR;
  const oldSchedule = process.env.FATFISH_SCHEDULE_STATE;
  process.env.FATFISH_GROWTH_DIGEST = join(folder, 'growth.txt');
  process.env.FATFISH_PEAK_DIGEST = join(folder, 'peak.txt');
  process.env.FATFISH_JOURNAL_DIR = join(folder, 'journal');
  process.env.FATFISH_SCHEDULE_STATE = join(folder, 'schedule.json');
  t.after(() => {
    if (oldGrowth === undefined) delete process.env.FATFISH_GROWTH_DIGEST;
    else process.env.FATFISH_GROWTH_DIGEST = oldGrowth;
    if (oldPeak === undefined) delete process.env.FATFISH_PEAK_DIGEST;
    else process.env.FATFISH_PEAK_DIGEST = oldPeak;
    if (oldJournal === undefined) delete process.env.FATFISH_JOURNAL_DIR;
    else process.env.FATFISH_JOURNAL_DIR = oldJournal;
    if (oldSchedule === undefined) delete process.env.FATFISH_SCHEDULE_STATE;
    else process.env.FATFISH_SCHEDULE_STATE = oldSchedule;
  });
  await mkdir(process.env.FATFISH_JOURNAL_DIR);
  await writeFile(join(process.env.FATFISH_JOURNAL_DIR, '2026-11-06.md'), 'PRIVATE_DIARY');
  await writeFile(process.env.FATFISH_PEAK_DIGEST, 'PRIVATE_PEAK');
  await writeFile(process.env.FATFISH_SCHEDULE_STATE, JSON.stringify({results: {
    diary: { at: new Date().toISOString(), ok: false, error: 'PRIVATE_TASK' }
  }}));
  await writeFile(process.env.FATFISH_GROWTH_DIGEST, 'first known capability');
  const { socialChannelPrompt } = await import('../runtime-adapter.mjs');
  assert.doesNotMatch(socialChannelPrompt(), /first known capability/);
  assert.doesNotMatch(socialChannelPrompt({ ownerPrivate: false }), /first known capability/);
  assert.doesNotMatch(socialChannelPrompt(), /PRIVATE_DIARY|PRIVATE_PEAK|PRIVATE_TASK/);
  for (const value of ['PRIVATE_DIARY', 'PRIVATE_PEAK', 'PRIVATE_TASK']) {
    assert.ok(socialChannelPrompt({ ownerPrivate: true }).includes(value));
  }
  assert.match(socialChannelPrompt({ ownerPrivate: true }), /first known capability/);
  await writeFile(process.env.FATFISH_GROWTH_DIGEST, 'newly learned capability');
  assert.match(socialChannelPrompt({ ownerPrivate: true }), /first known capability/);
  const later = Date.now() + 301_000;
  t.mock.method(Date, 'now', () => later);
  const refreshed = socialChannelPrompt({ ownerPrivate: true });
  assert.match(refreshed, /newly learned capability/);
  assert.doesNotMatch(refreshed, /first known capability/);
});
