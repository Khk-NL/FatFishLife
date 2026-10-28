import { existsSync, readFileSync } from 'node:fs';
import { AsyncLocalStorage } from 'node:async_hooks';
import { FatFishPolicy } from './policy.mjs';

const controlContext = new AsyncLocalStorage();

export async function ownerCommand(policy, run) {
  const state = { policy, active: true };
  try { return await controlContext.run(state, run); }
  finally { state.active = false; }
}

export function loadPolicy(settings) {
  if (settings?.policy) return new FatFishPolicy(settings.policy);
  // 环境变量优先；否则读项目内固定路径（DSH 主进程不方便注入 env）
  const candidates = [
    process.env.FATFISH_POLICY_FILE,
    'D:/Code/Projects/FatFishLife/dsh/policy.json',
  ].filter(Boolean);
  const hit = candidates.find(candidate => existsSync(candidate));
  if (!hit) throw new Error('FatFish policy not found; set FATFISH_POLICY_FILE or add dsh/policy.json');
  return new FatFishPolicy(JSON.parse(readFileSync(hit, 'utf8').replace(/^\uFEFF/, '')));
}

export function scopedSessionId(policy, chatId) { return policy.sessionId(chatId); }

export async function beforeInbound(bridge, event) {
  const policy = bridge.deps.fatfishPolicy;
  const decision = policy.decide(event, bridge.deps.policy);
  if (decision.kind === 'ignore') return false;
  if (decision.kind === 'busy') {
    if (policy.canSend({ busy: true, returnHour: decision.returnHour })) {
      const [kind, target] = decision.chatId.split(':');
      const receipt = await bridge.deps.connection.call('send_msg', {
        message_type: kind, [kind === 'group' ? 'group_id' : 'user_id']: Number(target),
        message: [{ type: 'text', data: { text: decision.text } }],
      });
      if (receipt?.message_id == null) throw new Error('Busy reply has no OneBot message_id');
    }
    return false;
  }
  if (decision.poke) {
    // The upstream pipeline supports messages only. Give the targeted poke a
    // safe user-text representation after policy checks, without forging an @.
    event = { ...event, post_type: 'message', message_type: decision.chatId.split(':')[0],
      message: [{ type: 'text', data: { text: '（戳了戳苹果乐）' } }], raw_message: '（戳了戳苹果乐）' };
  } else if (decision.kind === 'control') {
    event = { ...event, message: [{ type: 'text', data: { text: decision.command } }] };
  }
  return event;
}

export function installSocialScope(ctx, bridge) {
  // P1 exposes no model tools. P2/P3 add reviewed capabilities explicitly;
  // backend commands remain a separate authenticated route.
  ctx.tools.restrict({ allow: [] });
  ctx.tools.guard(exec => bridge.deps.fatfishPolicy.toolDenial(exec, bridge.chatForSession(exec.agent?.session.id), []));
}

export function assertOutbound(policy, action) {
  const control = controlContext.getStore();
  if (control?.policy === policy && control.active) return;
  // Read operations may continue while silent; every transport write is gated.
  if (!/^(get_|can_)/.test(action) && !policy.canSend()) throw new Error('FatFish outbound paused');
}
