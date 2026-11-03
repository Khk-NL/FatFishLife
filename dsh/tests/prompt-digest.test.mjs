import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('prompt provider refreshes growth digest after cache expiry without reimporting', async t => {
  const folder = await mkdtemp(join(tmpdir(), 'fatfish-digest-'));
  t.after(() => rm(folder, { recursive: true, force: true }));
  const oldGrowth = process.env.FATFISH_GROWTH_DIGEST;
  const oldPeak = process.env.FATFISH_PEAK_DIGEST;
  process.env.FATFISH_GROWTH_DIGEST = join(folder, 'growth.txt');
  process.env.FATFISH_PEAK_DIGEST = join(folder, 'missing-peak.txt');
  t.after(() => {
    if (oldGrowth === undefined) delete process.env.FATFISH_GROWTH_DIGEST;
    else process.env.FATFISH_GROWTH_DIGEST = oldGrowth;
    if (oldPeak === undefined) delete process.env.FATFISH_PEAK_DIGEST;
    else process.env.FATFISH_PEAK_DIGEST = oldPeak;
  });
  await writeFile(process.env.FATFISH_GROWTH_DIGEST, 'first known capability');
  const { socialChannelPrompt } = await import('../runtime-adapter.mjs');
  assert.match(socialChannelPrompt(), /first known capability/);
  await writeFile(process.env.FATFISH_GROWTH_DIGEST, 'newly learned capability');
  assert.match(socialChannelPrompt(), /first known capability/);
  const later = Date.now() + 301_000;
  t.mock.method(Date, 'now', () => later);
  const refreshed = socialChannelPrompt();
  assert.match(refreshed, /newly learned capability/);
  assert.doesNotMatch(refreshed, /first known capability/);
});
