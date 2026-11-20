// Use the host's native executor and guard; only the WeChat scope's schema view changes.
export function installWechatTextOnly(agentCtx, onStop = () => {}) {
  const tools = agentCtx.get('tools');
  if (!tools?.guard || !tools.setExecutor || !tools.selectExecutor) {
    throw new Error('微信会话所需的 DSH 工具限制不可用。');
  }
  const executor = tools.selectExecutor();
  tools.guard(() => '微信只回复文字，桌面工具请在 DSH 使用。');
  tools.setExecutor({
    describe: () => ({ schemas: [] }),
    execute: input => executor.execute(input),
  });
  let steps = 0;
  agentCtx.on('session/event', (_session, event) => {
    if (event.type === 'turn/start') steps = 0;
  });
  agentCtx.on('agent/pre-step', (_payload, next) => {
    if (steps < 2) {
      steps++;
      return next();
    }
    onStop({ reason: 'step_limit', steps });
    return { kind: 'reject' };
  });
  agentCtx.on('agent/request-error', ({ failure }, _next) => {
    // No second provider call for a text-only chat's failed request.
    onStop({ reason: /QUOTA/.test(failure?.code ?? '') ? 'quota' : 'provider_error', steps });
    return undefined;
  });
}
