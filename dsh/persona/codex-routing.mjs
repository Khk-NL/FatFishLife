import { readRuntimeOptions } from '../control/runtime-options.mjs';

const preferred = { provider: 'openai-codex', model: 'gpt-6.2-sol', reasoningEffort: 'medium' };
const sameAs = (actual, expected) => actual?.provider === expected.provider
  && actual?.model === expected.model && actual?.reasoningEffort === expected.reasoningEffort;

export function quotaAllowsCodex(report, minimum, now = Date.now()) {
  return Boolean(report?.modelAvailable === true && Number.isFinite(report.fetchedAt)
    && report.fetchedAt <= now && now - report.fetchedAt <= 120_000
    && Number.isFinite(report.remaining) && report.remaining <= 100 && report.remaining > minimum
    && Number.isFinite(report.resetsAt) && report.resetsAt > now / 1000);
}

export function installCodexRouting(ctx) {
  ctx.inject(['fatfishCodexQuota'], (scope) => {
    const quota = scope.fatfishCodexQuota;
    const turns = new WeakMap();
    let latest;
    let pending;
    const warm = () => {
      if (pending) return;
      const generation = quota.generation();
      pending = Promise.resolve().then(() => quota.read(AbortSignal.timeout(3500))).then(report => {
        if (quota.generation() === generation) latest = { report, generation };
      }).catch(() => {
        latest = undefined;
      }).finally(() => { pending = undefined; });
    };
    warm();
    scope.on('agent/inbox/inserted', () => warm());
    scope.on('agent/inbox/claimed', ({ agent, turn }) => {
      if (!agent || turns.get(agent)?.turn === turn) return;
      const current = agent.model.current();
      const state = { turn, fallback: null };
      turns.set(agent, state);
      // Only override the standard DeepSeek route. A manual model selection stays in control.
      if (current?.provider !== 'deepseek-official' || current.model !== 'deepseek-flash') return;
      if (latest?.generation !== quota.generation()
        || !quotaAllowsCodex(latest?.report, readRuntimeOptions().codexMinimum)) return;
      agent.model.select(preferred);
      state.fallback = current;
    });
    scope.on('agent/turn-stopping', ({ agent }) => {
      const state = turns.get(agent);
      turns.delete(agent);
      if (state?.fallback && sameAs(agent.model.current(), preferred)) agent.model.select(state.fallback);
    });
  });
}
