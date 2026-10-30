// Runs only in the disposable profile created by scripts/dsh_native_smoke.py.
import assert from 'node:assert/strict';
import { writeFile, mkdir, readFile, rename } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';

export const name = 'fatfish-native-smoke';
export const inject = ['fatfishSettings', 'settings', 'llm', 'agents', 'sessions', 'tools', 'agentPresets', 'sessionPersistence', 'workspaceRegistry'];

export function apply(ctx) {
  queueMicrotask(async () => {
    const checks = [];
    let handle;
    let bridge;
    let connection;
    let socket;
    const record = (name, fn) => Promise.resolve().then(fn).then(() => checks.push(name));
    const finish = async result => {
      const target = process.env.FATFISH_SMOKE_REPORT;
      await writeFile(target + '.tmp', JSON.stringify(result));
      await rename(target + '.tmp', target);
    };
    try {
      await ctx.get('loader').await();
      assert.equal(ctx.fatfishSettings.behavior.voice.base, .15);
      assert.equal(ctx.fatfishSettings.policy.busyWindows.length, 2);
      checks.push('native-control-bundle-active');
      await record('native-settings-visible-and-live', async () => {
        const form = ctx.settings.describe().find(item => item.ns === 'fatfish-control');
        assert.ok(form?.autoGenerate);
        assert.match(JSON.stringify(form.schema), /"voice"/);
        assert.match(JSON.stringify(form.schema), /"busyWindows"/);
        const original = ctx.fatfishSettings.behavior.voice.base;
        await ctx.settings.update('fatfish-control', { voice: { basePercent: 16 } }, form.revision);
        for (let i = 0; i < 100 && ctx.fatfishSettings.behavior.voice.base !== .16; i++) await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(ctx.fatfishSettings.behavior.voice.base, .16);
        const saved = JSON.parse(await readFile(join(process.env.DSH_HOME, 'fatfish-settings/runtime-behavior.json'), 'utf8'));
        assert.equal(saved.voice.base, .16);
        await ctx.settings.update('fatfish-control', { voice: { basePercent: original * 100 } });
        for (let i = 0; i < 100 && ctx.fatfishSettings.behavior.voice.base !== original; i++) await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(ctx.fatfishSettings.behavior.voice.base, original);
        const refreshed = ctx.settings.describe().find(item => item.ns === 'fatfish-control');
        const reply = refreshed.value.reply;
        await ctx.settings.mutate('fatfish-control', [{ op: 'set', path: ['reply'], value: { ...reply, groupCooldownSeconds: 11 } }], refreshed.revision);
        for (let i = 0; i < 100 && ctx.fatfishSettings.policy.groupCooldownMs !== 11000; i++) await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(ctx.fatfishSettings.policy.groupCooldownMs, 11000);
        await ctx.settings.update('fatfish-control', { reply });
        for (let i = 0; i < 100 && ctx.fatfishSettings.policy.groupCooldownMs !== reply.groupCooldownSeconds * 1000; i++) await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(ctx.fatfishSettings.policy.groupCooldownMs, reply.groupCooldownSeconds * 1000);
      });
      if (process.env.FATFISH_COMMUNITY_REPORT) {
        const { check } = await import('./community-check.mjs');
        const community = await check({ live: true });
        await writeFile(process.env.FATFISH_COMMUNITY_REPORT, JSON.stringify(community, null, 2));
        assert.equal(community.videoMetadata.ok, true);
        assert.equal(community.discovery.ok, true);
        checks.push('native-community-readonly-tools');
      }
      const lib = dirname(fileURLToPath(import.meta.resolve('dsh-onebot-qq')));
      const load = file => import(pathToFileURL(join(lib, file)).href);
      const [{ ChatBridge }, { FatFishPolicy }, adapter, { defineTool }, { OneBotConnection }, { LlmAdapter }] = await Promise.all([
        load('bridge.js'), load('policy.mjs'), load('runtime-adapter.mjs'), import('@deepseek-ai/dsh-tools'), load('connection.js'), import('@deepseek-ai/dsh-llm'),
      ]);
      checks.push('native-peer-imports');
      const modelRequests = [];
      let modelScenario = 'normal';
      const finalText = '苹果派出炉啦，老板接好。';
      class LocalMockAdapter extends LlmAdapter {
        async *stream(options) {
          modelRequests.push(options);
          if (modelScenario === 'mute-before-final') policy.config.silent = true;
          if (modelScenario === 'work-before-final') time = Date.parse('2026-10-31T09:00:00+08:00');
          if (modelScenario === 'error') throw new Error('MOCK 402 Insufficient Balance: must stay local');
          yield { type: 'reasoning-delta', index: 0, text: 'PRIVATE_REASONING_DO_NOT_SEND' };
          yield { type: 'block-end', index: 0, block: { type: 'reasoning', text: 'PRIVATE_REASONING_DO_NOT_SEND' } };
          yield { type: 'text-delta', index: 1, text: finalText };
          yield { type: 'block-end', index: 1, block: { type: 'text', text: finalText } };
          yield { type: 'finish', reason: { kind: 'stop' } };
        }
      }
      ctx.llm.registerAdapter(['fatfish-local-mock'], new LocalMockAdapter());
      let time = Date.parse('2026-10-31T10:00:00+08:00');
      const policy = new FatFishPolicy({ adapterId: 'native-test-' + randomUUID(), botId: '10000001', ownerId: '10000002', silent: false }, { now: () => time });
      const sends = [], dispatches = [];
      const token = randomUUID();
      connection = new OneBotConnection({ mode: 'reverse', host: '127.0.0.1', port: 0, accessToken: token, callTimeoutMs: 3000, log: () => {} });
      const config = { fatfishPolicy: policy, botQQ: '10000001', ignoreSelf: true, requireMention: false,
        interimMessages: false, sendErrorNotice: false, deferredTimeoutMs: 0, restrictedMemberPrefix: false,
        rateLimitPerMinute: 0, sensitivePatterns: [], textImageThreshold: 100000,
        mediaDir: join(process.env.DSH_HOME, 'native-test-media', randomUUID()), workspacePath: process.env.DSH_HOME,
        maxImageBytes: 1e7, maxVoiceBytes: 1e7, maxFileBytes: 1e7, maxInboundFileBytes: 1e7,
        agentPreset: 'apple-social', fontFiles: [], fontFamilies: [], cardFooter: '' };
      await mkdir(config.mediaDir, { recursive: true });
      bridge = new ChatBridge({ ctx, config, fatfishPolicy: policy, connection, agents: ctx.agents, sessions: ctx.sessions,
        agentPresets: ctx.agentPresets, sessionPersistence: ctx.sessionPersistence, workspaceRegistry: ctx.workspaceRegistry,
        media: { cleanupExpired: async () => {} }, transcriber: {}, dshHome: process.env.DSH_HOME,
        policy: { groupPolicy: 'open', dmPolicy: 'open', adminUsers: ['10000002'], allowAllUsers: true },
        defaultModel: () => ({ provider: 'fatfish-local-mock', model: 'mock' }),
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
      // 忙碌时段只认真 @（2026-10-29 改），所以这里必须带真的 at 段
      const mention = (body, n, sender = 10000003) => ({ post_type: 'message', message_type: 'group', self_id: 10000001,
        group_id: 10000004, user_id: sender, message_id: n,
        message: [{ type: 'at', data: { qq: '10000001' } }, { type: 'text', data: { text: body } }] });
      await record('busy-bypasses-real-bridge-dispatch', async () => {
        await inbound(mention('大肥鲸', 1));
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
      await record('real-agent-roundtrip-carries-complete-persona', async () => {
        assert.equal(modelRequests.length, 0);
        delete bridge.dispatchFollowup; // Restore the upstream method, including real Agent creation and followup.
        const before = sends.length;
        await inbound(event('大肥鲸，苹果派做好了吗', 100));
        const deadline = Date.now() + 5000;
        const texts = () => sends.slice(before).flatMap(frame => frame.params?.message ?? [])
          .filter(segment => segment.type === 'text').map(segment => segment.data.text);
        while (!texts().includes(finalText) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
        assert.deepEqual(texts(), [finalText], 'Only the settled final text may reach OneBot');
        assert.equal(modelRequests.length, 1, 'One ordinary message must make one mock model request');
        const expected = (await readFile(join(process.env.DSH_HOME, 'expected-persona.txt'), 'utf8')).replace(/\r\n/g, '\n').trim();
        assert.ok(JSON.stringify(modelRequests[0]).includes(JSON.stringify(expected).slice(1,-1)), 'Complete persona must reach the model');
        // 2026-10-29：媒体发送改为复用桥上游的两个工具（qq_send_voice / qq_send_image）。
        // 除它们与内核的 run_code 外，社交请求不该带任何管理/文件/其它 QQ 工具。
        const socialTools = new Set(['run_code', 'qq_send_voice', 'qq_send_image']);
        const toolNames = (modelRequests[0].tools ?? []).map(tool => tool.name);
        assert.ok(toolNames.every(name => socialTools.has(name)),
          'Social requests must not inherit management tools: ' + toolNames.join(','));
        for (const forbidden of ['bash', 'read', 'write', 'qq_napcat_api', 'qq_send_file', 'qq_send_video']) {
          assert.ok(!toolNames.includes(forbidden), 'forbidden tool leaked into the social surface: ' + forbidden);
        }
      });
      const settled = async chatId => {
        await bridge.chats.get(chatId).agent.whenIdle();
        await bridge.outbound.chainTail(chatId);
      };
      await record('mute-during-real-model-turn-blocks-late-delivery', async () => {
        modelScenario = 'mute-before-final';
        const before = sends.length;
        await inbound({ ...event('大肥鲸，测试生成期间静默', 101), group_id: 10000005 });
        await settled('group:10000005');
        assert.equal(sends.length, before);
        policy.config.silent = false;
      });
      await record('work-window-during-real-model-turn-blocks-late-delivery', async () => {
        modelScenario = 'work-before-final';
        const before = sends.length;
        await inbound({ ...event('大肥鲸，测试生成期间进入忙碌窗口', 102), group_id: 10000006 });
        await settled('group:10000006');
        assert.equal(sends.length, before);
        time = Date.parse('2026-10-31T20:00:00+08:00');
      });
      await record('model-error-never-becomes-public-backend-notice', async () => {
        modelScenario = 'error';
        const before = sends.length;
        await inbound({ ...event('大肥鲸，测试模型错误', 103), group_id: 10000007 });
        await settled('group:10000007');
        assert.equal(sends.length, before);
      });
      await record('missing-persona-never-falls-back-to-generic-agent', async () => {
        modelScenario = 'normal';
        config.agentPreset = 'fatfish-deliberately-missing-preset';
        const before = sends.length, requests = modelRequests.length;
        await inbound({ ...event('大肥鲸，测试人设缺失', 104), group_id: 10000008 });
        assert.equal(modelRequests.length, requests);
        assert.equal(sends.length, before);
        assert.equal(bridge.chats.has('group:10000008'), false);
      });
      await finish({ ok: true, checks, mockModelRequests: modelRequests.length, paidRequests: 0, realPlatformSends: 0 });
    } catch (error) {
      await finish({ ok: false, checks, error: String(error.stack ?? error) });
    } finally {
      await handle?.dispose();
      await bridge?.stop();
      socket?.terminate();
      connection?.stop();
    }
  });
}
