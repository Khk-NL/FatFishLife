import test from 'node:test';
import assert from 'node:assert/strict';
import { setImmediate as tick } from 'node:timers/promises';
import { createLocalBriefClient } from '../local-brief-client.mjs';

const ok = data => ({ ok: true, json: async () => data });
const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};

test('mount is idle; cold/concurrent messages do not wait for or duplicate loading', async () => {
  const load = deferred();
  const calls = [];
  const client = createLocalBriefClient({ fetchImpl: (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return load.promise;
  } });
  assert.equal(calls.length, 0);
  assert.equal(await client.chat([], {}), null);
  assert.equal(await client.chat([], {}), null);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.prompt, '');
  assert.equal(calls[0].body.keep_alive, '5m');
  load.resolve(ok({ done: true }));
  await tick();
});

test('warm replies expire after five idle minutes and never queue concurrent requests', async () => {
  let time = 100;
  const reply = deferred();
  const calls = [];
  const client = createLocalBriefClient({ now: () => time, fetchImpl: (url, init) => {
    calls.push(JSON.parse(init.body));
    return url.endsWith('/api/chat') ? reply.promise : Promise.resolve(ok({ done: true }));
  } });
  await client.chat([], {});
  await tick();
  const first = client.chat([{ role: 'user', content: 'test' }], { num_ctx: 1024 });
  assert.equal(await client.chat([], {}), null);
  assert.equal(calls.length, 2);
  reply.resolve(ok({ message: { content: 'local reply' } }));
  assert.equal((await first).message.content, 'local reply');
  time += 300_001;
  assert.equal(await client.chat([], {}), null);
  assert.equal(calls.length, 3);
  assert.equal(calls[2].prompt, '');
  await tick();
});

test('failed HTTP load can be retried instead of caching a fulfilled failure forever', async () => {
  let count = 0;
  const client = createLocalBriefClient({ fetchImpl: async () => {
    count++;
    return count === 1 ? { ok: false } : ok({ done: true });
  } });
  await client.chat([], {});
  await tick();
  await client.chat([], {});
  await tick();
  assert.equal(count, 2);
});

test('load, chat, and response-body stalls are aborted; later messages can recover', async () => {
  for (const stall of ['load', 'chat', 'body']) {
    let stalled = false;
    let aborts = 0;
    const client = createLocalBriefClient({ loadTimeoutMs: 20, replyTimeoutMs: 20,
      fetchImpl: async (url, { signal }) => {
        if (stalled || (stall !== 'load' && url.endsWith('/api/generate'))) return ok({ done: true });
        stalled = true;
        const hang = () => new Promise((resolve, reject) => signal.addEventListener('abort', () => {
          aborts++;
          reject(new Error('aborted'));
        }, { once: true }));
        return stall === 'body' ? { ok: true, json: hang } : hang();
      } });
    await client.chat([], {});
    if (stall !== 'load') {
      await tick();
      assert.equal(await client.chat([], {}), null);
    } else {
      await new Promise(r => setTimeout(r, 40));
    }
    assert.equal(aborts, 1, stall);
    await client.chat([], {});
    await tick();
    assert.deepEqual(await client.chat([], {}), { done: true }, stall);
  }
});
