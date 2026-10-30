import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire, registerHooks } from 'node:module';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Opt in with the installed SDK; ordinary offline tests need no DSH installation.
const profile = process.env.FATFISH_DSH_TEST_PROFILE;
test('control reads native volatile settings on each tick and disposes its timers', { skip: !profile }, async t => {
  const require = createRequire(join(profile, 'package.json'));
  const sdk = Object.fromEntries(['@deepseek-ai/schemastery', '@deepseek-ai/dsh-tools', '@deepseek-ai/cosmokit']
    .map(name => [name, require.resolve(name)]));
  const hook = registerHooks({ resolve(specifier, context, next) {
    if (sdk[specifier]) {
      const resolved = sdk[specifier];
      return { url: pathToFileURL(resolved.endsWith('index.cjs') ? resolved.replace(/\.cjs$/, '.mjs') : resolved).href, shortCircuit: true };
    }
    return next(specifier, context);
  } });
  t.after(() => hook.deregister());
  const { Config, apply } = await import('../control/index.mjs');
  const { updateVolatile } = await import('@deepseek-ai/cosmokit');
  const directory = await mkdtemp(join(tmpdir(), 'fatfish-runtime-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const timers = new Map();
  const cleared = [];
  t.mock.method(globalThis, 'setInterval', (callback, delay) => {
    const handle = { callback, unref() {} };
    timers.set(delay, handle);
    return handle;
  });
  t.mock.method(globalThis, 'clearInterval', handle => cleared.push(handle));
  let statusTool;
  let dispose;
  const ctx = new Proxy({
    logger: { info() {}, warn() {} },
    provide() {}, on() {},
    effect(setup) { dispose = setup(); },
    tools: { register(tool) { statusTool = tool; } },
  }, { get(target, key) {
    if (['timer', 'setInterval', 'setTimeout'].includes(key)) throw new Error('timer accessed without inject');
    return target[key];
  } });
  const now = new Date();
  const at = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const raw = { dataDirectory: directory, identity: { botId: '10001', ownerId: '10002' },
    tasks: [{ id: 'disabled-runner', kind: 'test-only', at }],
    runner: { enabled: false, ownerChat: 'private:10003' }, proactive: { enabled: false } };
  const config = Config(raw);
  await apply(ctx, config);
  const read = async file => JSON.parse(await readFile(join(directory, file), 'utf8'));
  assert.equal((await read('control-mount.json')).stage, 'done');
  assert.equal((await read('control-mount.json')).tasks, 1);
  assert.equal((await read('scheduler-heartbeat.json')).tasks, 1);
  assert.equal((await read('schedule-state.json')).results['disabled-runner'].reason, 'runner-disabled');
  assert.equal((await statusTool.execute({})).runner.ownerChat, 'private:10003');
  await timers.get(300_000).callback();
  await assert.rejects(readFile(join(directory, 'proactive-heartbeat.json')), { code: 'ENOENT' });

  // A live edit must replace the task table, including an intentionally empty table.
  const changed = Config({ ...raw, tasks: [], runner: { enabled: true } });
  updateVolatile(config.tasks, changed.tasks);
  updateVolatile(config.runner, changed.runner);
  await timers.get(30_000).callback();
  assert.equal((await read('scheduler-heartbeat.json')).tasks, 0);
  assert.equal((await statusTool.execute({})).runner.ownerChat, 'private:10002');

  // Unknown tasks exercise execution without network, model, media or account access.
  const enabled = Config({ ...raw, tasks: [{ id: 'enabled-runner', kind: 'test-only', at }] });
  updateVolatile(config.tasks, enabled.tasks);
  await timers.get(30_000).callback();
  // The timer callback deliberately detaches runDue; allow its await to finish.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await read('schedule-state.json')).results['enabled-runner'].reason, 'unknown-kind:test-only');
  dispose();
  assert.deepEqual(cleared, [timers.get(30_000), timers.get(300_000)]);
});
