// Runs only in the disposable profile created by scripts/dsh_native_smoke.py.
import assert from 'node:assert/strict';
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';

export const name = 'fatfish-native-smoke';
export const inject = ['agents', 'sessions', 'tools', 'agentPresets', 'sessionPersistence', 'workspaceRegistry'];

export function apply(ctx) {
  queueMicrotask(async () => {
    const checks = [];
    let handle;
    let bridge;
    let connection;
    let socket;
    const record = (name, fn) => Promise.resolve().then(fn).then(() => checks.push(name));
    try {
      await ctx.get('loader').await();
      const lib = dirname(fileURLToPath(import.meta.resolve('dsh-onebot-qq')));
      const load = file => import(pathToFileURL(join(lib, file)).href);
      const [{ ChatBridge }, { FatFishPolicy }, adapter, { defineTool }, { OneBotConnection }] = await Promise.all([
        load('bridge.js'), load('policy.mjs'), load('runtime-adapter.mjs'), import('@deepseek-ai/dsh-tools'), load('connection.js'),
      ]);
      checks.push('native-peer-imports');
      let time = Date.parse('2026-10-31T10:00:00+08:00');
      const policy = new FatFishPolicy({ adapterId: 'native-test', botId: '10000001', ownerId: '10000002', silent: false }, { now: () => time });
      const sends = [], dispatches = [];
      const token = randomUUID();
      connection = new OneBotConnection({ mode: 'reverse', host: '127.0.0.1', port: 0, accessToken: token, callTimeoutMs: 3000, log: () => {} });
      const config = { fatfishPolicy: policy, botQQ: '10000001', ignoreSelf: true, requireMention: false,
        interimMessages: false, sendErrorNotice: false, deferredTimeoutMs: 0, restrictedMemberPrefix: false,
        rateLimitPerMinute: 0, sensitivePatterns: [], textImageThreshold: 100000,
        mediaDir: join(process.env.DSH_HOME, 'native-test-media'), workspacePath: process.env.DSH_HOME,
        maxImageBytes: 1e7, maxVoiceBytes: 1e7, maxFileBytes: 1e7, maxInboundFileBytes: 1e7,
        agentPreset: 'apple-social', fontFiles: [], fontFamilies: [], cardFooter: '' };
      await mkdir(config.mediaDir, { recursive: true });
      bridge = new ChatBridge({ ctx, config, fatfishPolicy: policy, connection, agents: ctx.agents, sessions: ctx.sessions,
        agentPresets: ctx.agentPresets, sessionPersistence: ctx.sessionPersistence, workspaceRegistry: ctx.workspaceRegistry,
        media: { cleanupExpired: async () => {} }, transcriber: {}, dshHome: process.env.DSH_HOME,
        policy: { groupPolicy: 'open', dmPolicy: 'open', adminUsers: ['10000002'], allowAllUsers: true },
        log: () => {}, commands: { execute: async () => { throw new Error('Unexpected host command'); } },
      });
      bridge.dispatchFollowup = async (...args) => dispatches.push(args);
      bridge.start();
      await bridge.registry.mappingLoaded;
      connection.start();
      if (!connection.address()) await once(connection.server, 'listening');
      const { default: WebSocket } = await import(pathToFileURL(createRequire(pathToFileURL(join(lib, 'index.js'))).resolve('ws')).href);
      socket = new WebSocket(`ws://127.0.0.1:${connection.address().port}/ws`, { headers: { Authorization: 'Bearer ' + token } });
      socket.on('message', bytes => {
        const frame = JSON.parse(String(bytes));
        sends.push(frame);
        socket.send(JSON.stringify({ status: 'ok', retcode: 0, echo: frame.echo, data: { message_id: sends.length } }));
      });
      await once(socket, 'open');
      const inbound = payload => new Promise((resolve, reject) => {
        connection.onMessage = incoming => { bridge.handleInbound(incoming).then(resolve, reject); };
        socket.send(JSON.stringify(payload));
      });
      checks.push('authenticated-loopback-onebot');
      const event = (body, n, sender = 10000003) => ({ post_type: 'message', message_type: 'group', self_id: 10000001,
        group_id: 10000004, user_id: sender, message_id: n, message: [{ type: 'text', data: { text: body } }] });
      await record('busy-bypasses-real-bridge-dispatch', async () => {
        await inbound(event('苹果乐', 1));
        assert.equal(sends.length, 1); assert.equal(dispatches.length, 0);
        assert.match(sends[0].params.message[0].data.text, /12点/);
      });
      await record('targeted-poke-traverses-real-transport', async () => {
        time += 61000;
        await inbound({ post_type: 'notice', notice_type: 'notify', sub_type: 'poke', self_id: 10000001,
          target_id: 10000001, user_id: 10000003, group_id: 10000004 });
        assert.equal(sends.length, 2); assert.equal(dispatches.length, 0);
      });
      time = Date.parse('2026-10-31T20:00:00+08:00');
      await record('member-command-reaches-social-pipeline-without-refusal', async () => {
        for (const [i, word] of ['/help', '/stop', '/stats', '/provider', '/reset', '/new'].entries()) {
          const payload = event(word, i + 10);
          payload.message.unshift({ type: 'at', data: { qq: '10000001' } });
          await inbound(payload);
        }
        assert.equal(sends.length, 2); assert.equal(dispatches.length, 6);
      });
      await record('member-command-router-is-never-invoked', async () => {
        assert.equal(await bridge.tryHandleCommand('group:10000004', '/help', '10000003'), false);
        assert.equal(sends.length, 2);
      });
      await record('owner-command-router-remains-available', async () => {
        assert.equal(await bridge.tryHandleCommand('group:10000004', '/help', '10000002'), true);
        assert.ok(sends.length > 2);
      });
      let bodies = 0;
      await record('native-agent-and-scoped-tool-guard', async () => {
        handle = await ctx.agents.create({ sessionId: 'fatfish-native-scope-' + randomUUID(), agentOptions: {},
          meta: { cwd: process.env.DSH_HOME }, setup: async agentCtx => {
            agentCtx.tools.register(defineTool({ name: 'fatfish_denied_probe', description: 'Test only', parameters: {},
              output: { schema: { type: 'json' }, render: () => [] },
              execute: async () => { bodies++; return {}; } }));
            adapter.installSocialScope(agentCtx, bridge);
          } });
        const outcome = await ctx.tools.execute({ name: 'fatfish_denied_probe', arguments: {}, callId: 'test',
          agent: handle.agent, parent: { name: 'nested-test', callId: 'parent' }, signal: new AbortController().signal });
        assert.equal(bodies, 0);
        assert.equal(outcome.isError, true);
        assert.match(JSON.stringify(outcome), /outside this social capability set/);
      });
      await handle.dispose(); handle = undefined;
      await writeFile(process.env.FATFISH_SMOKE_REPORT, JSON.stringify({ ok: true, checks, paidRequests: 0, realPlatformSends: 0 }));
    } catch (error) {
      await writeFile(process.env.FATFISH_SMOKE_REPORT, JSON.stringify({ ok: false, checks, error: String(error.stack ?? error) }));
    } finally {
      await handle?.dispose();
      await bridge?.stop();
      socket?.terminate();
      connection?.stop();
    }
  });
}
