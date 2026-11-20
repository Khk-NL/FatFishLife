import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { setTimeout } from 'node:timers/promises';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { apply as installPersona } from './fatfish-persona/runtime.mjs';
import { installWechatTextOnly } from './node_modules/dsh-wechat/lib/fatfish-wechat-turn-budget.mjs';

export const name = 'fatfish-persona-probe';
export const inject = ['tools', 'llm', 'agents', 'agentPresets'];

export function apply(ctx) {
  void (async () => {
    await setTimeout(750);
    const requests = [];
    class Mock extends LlmAdapter {
      async *stream(options) {
        requests.push(options);
        yield { type: 'text-delta', index: 0, text: '本鱼在' };
        yield { type: 'block-end', index: 0, block: { type: 'text', text: '本鱼在' } };
        yield { type: 'finish', reason: { kind: 'stop' } };
      }
    }
    ctx.llm.registerAdapter(['persona-local-mock'], new Mock());
    for (const name of ['mcp__fatfish__lore_search', 'compress']) {
      ctx.tools.register(defineTool({
        name, description: 'Isolated test fixture', parameters: {},
        output: { schema: { type: 'string' }, render: () => [] },
        execute: async () => assert.fail('unexpected tool execution'),
      }));
    }
    for (const channel of ['desktop', 'wechat']) {
      const handle = await ctx.agents.create({
        sessionId: randomUUID(), agentOptions: { provider: 'persona-local-mock', model: 'test' },
        meta: { cwd: process.env.DSH_HOME },
        setup: async scoped => {
          if (channel === 'desktop') await ctx.agentPresets.mount(scoped, 'whale-local');
          else {
            installWechatTextOnly(scoped);
            installPersona(scoped, { channel });
          }
        },
      });
      try {
        handle.agent.followup(createUserMessage({
          source: { kind: 'test-fixture' }, content: [{ type: 'text', text: '在吗' }],
        }));
        await handle.agent.whenIdle();
        if (channel === 'desktop') {
          const result = await ctx.tools.execute({ agent: handle.agent, signal: AbortSignal.timeout(3000),
            calls: [{ type: 'tool-call', id: 'hidden-house-tool', name: 'compress', arguments: '{}' }] });
          assert.equal(result.results[0].result.isError, true);
        }
      } finally { await handle.dispose(); }
    }
    assert.equal(requests.length, 2);
    const desktop = JSON.stringify(requests[0]);
    const wechat = JSON.stringify(requests[1]);
    assert.ok(desktop.includes('吞饭之鲸') && wechat.includes('吞饭之鲸'));
    assert.ok(desktop.includes('查公开资料'), 'ready DSH tool must be visible');
    assert.ok(!wechat.includes('查公开资料'));
    assert.ok(!(requests[0].tools ?? []).some(tool => tool.name === 'compress'), 'internal tool schema must stay hidden');
    assert.equal(requests[1].tools?.length ?? 0, 0);
    await writeFile(process.env.FATFISH_PERSONA_RECEIPT, JSON.stringify({
      modelRequests: requests.length, registryCapVisible: true, nativeControlInBrief: false,
      wechatBriefLocalOnly: true, paidRequests: 0, platformWrites: 0,
    }));
    process.exit(0);
  })().catch(error => { console.error(error.stack); process.exit(1); });
}
