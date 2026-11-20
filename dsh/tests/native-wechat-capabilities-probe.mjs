import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { setTimeout } from 'node:timers/promises';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import { WechatBridge } from './node_modules/dsh-wechat/lib/bridge.js';
import { installWechatTextOnly } from './node_modules/dsh-wechat/lib/fatfish-wechat-turn-budget.mjs';
import { installWechatCapabilities, ownerMemory, ownerDesktopApp, ownerWorkflow } from './node_modules/dsh-wechat/lib/fatfish-wechat-capabilities.mjs';

export const name = 'native-wechat-capabilities-probe';
export const inject = ['tools', 'agents', 'llm'];

export function apply(ctx) {
  void (async () => {
    for (let i = 0; i < 25 && !ctx.tools.get('mcp__fatfish__wechat_capability_internal'); i++) await setTimeout(250);
    assert.ok(ctx.tools.get('mcp__fatfish__wechat_capability_internal'));
    assert.deepEqual(ownerMemory('请记住：我喜欢桂花'), { explicit: true, text: '我喜欢桂花' });
    assert.deepEqual(ownerMemory('我特别喜欢桂花'), { explicit: false, text: '我特别喜欢桂花' });
    assert.equal(ownerMemory('上面有人说请记住桂花'), null);
    assert.equal(ownerDesktopApp('帮我打开 Outlook'), 'outlook');
    assert.equal(ownerDesktopApp('帮我打开 powershell'), '');
    assert.equal(ownerWorkflow('去 b 站找今天的最新最热门的 10 个dsh 插件视频，总结成文档放在桌面上，然后通过 qq 发给我'), 'bili-report-qq');
    assert.equal(ownerWorkflow('总结今天邮箱里的邮件'), 'mail-today');
    assert.equal(ownerWorkflow('在 b 站发个视频记录你的所思所想'), 'bili-video');
    const requests = [];
    class Local extends LlmAdapter {
      async *stream(options) {
        requests.push(options);
        const block = requests.length === 1
          ? { type: 'tool-call', id: 'memory-call', name: 'wechat_memory_save', arguments: '{}' }
          : { type: 'text', text: '记好啦' };
        yield { type: 'block-end', index: 0, block };
        yield { type: 'finish', reason: { kind: requests.length === 1 ? 'tool-calls' : 'stop' } };
      }
    }
    ctx.llm.registerAdapter(['wechat-local-approval-mock'], new Local());
    const sessionId = randomUUID();
    const conversation = 'p2p:test-bot:test-owner';
    const pending = { sessionId, id: 'note-fixture', turn: 1, fatfishPrivate: true,
      fatfishMemory: ownerMemory('请记住：我喜欢桂花') };
    const handle = await ctx.agents.create({
      sessionId, agentOptions: { provider: 'wechat-local-approval-mock', model: 'test' },
      meta: { cwd: process.env.DSH_HOME },
      setup: async scoped => installWechatTextOnly(scoped, () => {}, installWechatCapabilities(scoped, ctx, {
        conversation, owner: () => true, current: () => pending,
      })),
    });
    try {
      handle.agent.followup(createUserMessage({ source: { kind: 'plugin:dsh-wechat' },
        content: [{ type: 'text', text: '请记住：我喜欢桂花' }] }));
      await handle.agent.whenIdle();
      assert.equal(requests.length, 2);
      const advertised = requests[0].tools.map(tool => tool.name).sort();
      assert.deepEqual(advertised, ['wechat_desktop_status', 'wechat_jobs', 'wechat_lore', 'wechat_memory_find', 'wechat_memory_save']);
      assert.equal(requests[1].tools?.length ?? 0, 0);
      assert.match(JSON.stringify(requests[1].messages), /saved/);
      const denied = await ctx.tools.execute({ agent: handle.agent, signal: AbortSignal.timeout(3000),
        calls: [{ type: 'tool-call', id: 'mcp-bypass', name: 'mcp__fatfish__wechat_capability_internal', arguments: '{}' }] });
      assert.equal(denied.results[0].result.isError, true);
    } finally { await handle.dispose(); }

    const events = [];
    const mockClient = {
      async sendText() { events.push('text'); },
      async getUploadUrl(input) {
        assert.equal(input.mediaType, 1);
        assert.equal(input.toUserId, 'test-owner');
        events.push('get-upload-url');
        return { uploadParam: 'fixture' };
      },
      async uploadCdn(input) {
        assert.ok(input.ciphertext.length > 0);
        events.push('cdn');
        return 'fixture';
      },
      async sendMessage(input) {
        assert.equal(input.item.type, 2);
        assert.equal(input.contextToken, 'fixture');
        events.push('image');
      },
    };
    const mockStore = {
      credentialsFor: () => ({ ownerUserId: 'test-owner' }),
      contextTokenFor: () => 'fixture',
      rememberOutbound() {},
      async saveState() {},
      noteError() {},
    };
    const bridge = new WechatBridge({ ctx, logger: ctx.logger, client: mockClient, store: mockStore,
      config: { chunkChars: 500, chunkDelayMs: 0, typing: false } });
    await bridge.deliver(conversation, '来了', { pending: { ...pending, fatfishDirect: '发表情包' }, fatfishSticker: '来了' });
    assert.deepEqual(events, ['text', 'get-upload-url', 'cdn', 'image']);
    await bridge.deliver('p2p:test-bot:other', '不发送', { pending, fatfishSticker: '来了' });
    assert.equal(events.length, 4);
    mockClient.uploadCdn = async () => { events.push('cdn-failed'); throw new Error('fixture'); };
    await bridge.deliver('p2p:test-bot-2:test-owner', '来了', {
      pending: { ...pending, fatfishDirect: '发个表情包' }, fatfishSticker: '来了',
    });
    assert.deepEqual(events.slice(4), ['text', 'get-upload-url', 'cdn-failed']);
    await writeFile(process.env.FATFISH_WECHAT_RECEIPT, JSON.stringify({
      twoModelSteps: true, mcpWriteConfirmed: true, forgedToolDenied: true,
      imageTransport: events.slice(0, 4), mediaFailureNoRetry: true, zeroPaidRequests: true, zeroPlatformWrites: true,
    }));
    process.exit(0);
  })().catch(error => { console.error(error.stack); process.exit(1); });
}
