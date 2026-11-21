import { readRuntimeOptions } from '../control/runtime-options.mjs';

const workBuddy = { provider: 'workbuddy', model: 'deepseek-v4.1-flash' };
const codex = { provider: 'openai-codex', model: 'gpt-6.2-sol', reasoningEffort: 'medium' };
const sameAs = (actual, expected) => actual?.provider === expected.provider
  && actual?.model === expected.model && actual?.reasoningEffort === expected.reasoningEffort;
const snapshots = new WeakMap();
const fresh = (report, now) => Number.isFinite(report?.fetchedAt)
  && report.fetchedAt <= now && now - report.fetchedAt <= 120_000;

export function quotaAllowsCodex(report, limits, now = Date.now()) {
  const meets = (remaining, resetsAt, minimum) => Number.isFinite(remaining) && remaining >= minimum
    && remaining <= 100 && Number.isFinite(resetsAt) && resetsAt > now / 1000;
  return fresh(report, now) && report.modelAvailable === true
    && meets(report.remaining, report.resetsAt, limits.codexMinimum)
    && meets(report.weeklyRemaining, report.weeklyResetsAt, limits.codexWeeklyMinimum);
}

export function quotaAllowsWorkBuddy(report, minimum, now = Date.now()) {
  return fresh(report, now) && report.modelAvailable === true
    && Number.isFinite(report.giftCredits) && report.giftCredits > 0 && report.giftCredits >= minimum
    && (!report.expiresAt || report.expiresAt > now);
}

function warm(quota) {
  if (!quota) return;
  const generation = quota.generation();
  const now = Date.now();
  const previous = snapshots.get(quota);
  if (previous?.generation === generation && (previous.pending || now - previous.startedAt < 60_000)) {
    return previous.pending;
  }
  const state = { generation, startedAt: now, report: previous?.generation === generation ? previous.report : undefined };
  snapshots.set(quota, state);
  const timeout = AbortSignal.timeout(3500);
  const expired = new Promise(resolve => timeout.addEventListener('abort', () => resolve(undefined), { once: true }));
  state.pending = Promise.race([Promise.resolve().then(() => quota.read(timeout)), expired]).then(report => {
    state.report = quota.generation() === generation ? report : undefined;
  }).catch(() => { state.report = undefined; }).finally(() => { state.pending = undefined; });
  return state.pending;
}

function currentReport(quota) {
  const entry = quota && snapshots.get(quota);
  return entry?.generation === quota?.generation() ? entry?.report : undefined;
}

export async function prepareCodexRouting(ctx, prefersCodex = false) {
  const quota = provider => ctx.get(provider);
  const workBuddyQuota = quota('fatfishWorkBuddyQuota');
  const codexQuota = prefersCodex ? quota('fatfishCodexQuota') : undefined;
  // The WeChat adapter can wait before admitting its message. Both reads are quota-only.
  await Promise.all([warm(workBuddyQuota), warm(codexQuota)]);
}

export async function readProviderQuota(ctx, provider) {
  const quota = ctx.get(provider === 'codex' ? 'fatfishCodexQuota' : 'fatfishWorkBuddyQuota');
  await warm(quota);
  const report = currentReport(quota);
  return fresh(report, Date.now()) ? report : undefined;
}

export function installCodexRouting(ctx, { prefersCodex = () => false, onCodexUnavailable = () => {} } = {}) {
  const services = {};
  for (const key of ['fatfishWorkBuddyQuota', 'fatfishCodexQuota']) {
    ctx.inject([key], (scope) => {
      const quota = scope[key];
      services[key] = quota;
      if (key === 'fatfishWorkBuddyQuota' || prefersCodex()) warm(quota);
      scope.effect(() => () => {
        if (services[key] === quota) delete services[key];
      });
    });
  }

  const turns = new WeakMap();
  ctx.on('agent/inbox/inserted', () => {
    const quota = services.fatfishWorkBuddyQuota;
    warm(quota);
    if (prefersCodex()) {
      warm(services.fatfishCodexQuota);
    }
  });
  ctx.on('agent/inbox/claimed', ({ agent, message, turn }) => {
    if (!agent) return;
    const previous = turns.get(agent);
    if (previous?.turn === turn) return;
    if (previous?.fallback && sameAs(agent.model.current(), previous.selected)) agent.model.select(previous.fallback);
    const current = agent.model.current();
    const state = { turn, fallback: null };
    turns.set(agent, state);
    // Preserve manual choices and use one provider for the entire turn.
    if (current?.provider !== 'deepseek-official' || current.model !== 'deepseek-flash') return;
    if (Array.isArray(message?.content) && message.content.some(part => part.type !== 'text')) return;
    const limits = readRuntimeOptions();
    const manualCodex = prefersCodex();
    const codexReady = manualCodex && quotaAllowsCodex(currentReport(services.fatfishCodexQuota), limits);
    if (manualCodex && !codexReady) onCodexUnavailable();
    const selected = codexReady ? codex
      : quotaAllowsWorkBuddy(currentReport(services.fatfishWorkBuddyQuota), limits.workBuddyMinimum) ? workBuddy : null;
    if (!selected) return;
    agent.model.select(selected);
    state.fallback = current;
    state.selected = selected;
  });
  ctx.on('agent/turn-stopping', ({ agent }) => {
    if (!agent) return;
    const state = turns.get(agent);
    turns.delete(agent);
    if (state?.selected === workBuddy) {
      const quota = services.fatfishWorkBuddyQuota;
      if (quota) snapshots.delete(quota);
    }
    if (state?.fallback && sameAs(agent.model.current(), state.selected)) agent.model.select(state.fallback);
  });
}
