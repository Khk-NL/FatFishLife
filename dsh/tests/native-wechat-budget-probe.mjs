import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { installWechatTextOnly } from './fatfish-wechat-turn-budget.mjs';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';

export const name = 'fatfish-wechat-budget-probe';
export const inject = ['tools', 'agents', 'llm', 'fatfishSettings'];

export function apply(ctx) {
  void (async () => {
    let requests = 0, toolBodies = 0, latestOptions, entered = 0, loop = false;
    const stops = [];
    class Mock extends LlmAdapter {
      async *stream(options) {
        requests++;
        latestOptions = options;
        if (loop) {
          const block = { type: 'tool-call', id: 'repeat-' + requests,
            name: 'fatfish_wechat_forbidden_fixture', arguments: '{}' };
          yield { type: 'block-end', index: 0, block };
          yield { type: 'finish', reason: { kind: 'tool-calls' } };
          return;
        }
        yield { type: 'text-delta', index: 0, text: '本机模拟回复' };
        yield { type: 'block-end', index: 0, block: { type: 'text', text: '本机模拟回复' } };
        yield { type: 'finish', reason: { kind: 'stop' } };
      }
    }
    ctx.llm.registerAdapter(['wechat-budget-mock'], new Mock());
    ctx.tools.register(defineTool({
      name: 'fatfish_wechat_forbidden_fixture', description: 'Fixture',
      parameters: {}, output: { schema: { type: 'json' }, render: () => [] },
      execute: async () => { toolBodies++; return {}; },
    }));
    const handle = await ctx.agents.create({
      sessionId: 'fatfish-native-wechat-' + randomUUID(),
      agentOptions: { provider: 'wechat-budget-mock', model: 'test' },
      meta: { cwd: process.env.DSH_HOME },
      setup: async scoped => {
        installWechatTextOnly(scoped, row => stops.push(row));
      },
    });
    try {
      handle.agent.followup(createUserMessage({ source: { kind: 'plugin:dsh-wechat' },
        content: [{ type: 'text', text: '本机测试' }] }));
      await handle.agent.whenIdle();
      assert.equal(requests, 1);
      assert.ok(latestOptions);
      assert.deepEqual(latestOptions.tools ?? [], []);
      const run = await ctx.tools.execute({ agent: handle.agent, signal: AbortSignal.timeout(3000),
        calls: [{ type: 'tool-call', id: 'probe', name: 'fatfish_wechat_forbidden_fixture', arguments: '{}' }] });
      assert.equal(run.results[0].result.isError, true);
      assert.equal(toolBodies, 0);
      assert.ok(ctx.tools.get('fatfish_wechat_forbidden_fixture'));
      loop = true;
      handle.agent.followup(createUserMessage({ source: { kind: 'plugin:dsh-wechat' },
        content: [{ type: 'text', text: '测试重复调用' }] }));
      await handle.agent.whenIdle();
      assert.equal(requests, 3);
      assert.equal(toolBodies, 0);
      assert.deepEqual(stops.at(-1), { reason: 'step_limit', steps: 2 });
      const fake = { get: () => ({ guard() {}, selectExecutor: () => ({ execute() {} }), setExecutor() {} }),
        hooks: {}, on(name, fn) { this.hooks[name] = fn; } };
      installWechatTextOnly(fake, row => stops.push(row));
      fake.hooks['session/event']({}, { type: 'turn/start' });
      const enter = () => ++entered;
      fake.hooks['agent/pre-step']({}, enter);
      fake.hooks['agent/pre-step']({}, enter);
      assert.deepEqual(fake.hooks['agent/pre-step']({}, enter), { kind: 'reject' });
      assert.equal(entered, 2);
      assert.deepEqual(stops.at(-1), { reason: 'step_limit', steps: 2 });
      fake.hooks['agent/request-error']({ failure: { code: 'QUOTA' } }, () => assert.fail('retry'));
      assert.equal(stops.at(-1).reason, 'quota');
      assert.ok(ctx.tools.get('fatfish_status'));
      await writeFile(process.env.FATFISH_OPS_RECEIPT, JSON.stringify({
        mockRequests: requests, loopingTurnRequests: 2, exposedWechatTools: latestOptions.tools?.length ?? 0,
        deniedToolBodyRuns: toolBodies, desktopToolRetained: true, blockedStep: 3,
        providerRetry: false, paidRequests: 0, platformWrites: 0,
      }));
    } finally { await handle.dispose(); }
    process.exit(0);
  })().catch(error => { console.error(error.stack); process.exit(1); });
}
