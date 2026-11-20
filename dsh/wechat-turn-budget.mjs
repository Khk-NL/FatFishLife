// Use the host's native executor and guard; only the WeChat scope's schema view changes.
export function installWechatTextOnly(agentCtx, onStop = () => {}, { available = () => false } = {}) {
  const tools = agentCtx.get('tools');
  if (!tools?.guard || !tools.setExecutor || !tools.selectExecutor) {
    throw new Error('微信会话所需的 DSH 工具限制不可用。');
  }
  const executor = tools.selectExecutor();
  let steps = 0;
  tools.guard(exec => steps === 1 && available(exec.name) ? undefined : '当前微信回合没有开放这项工具。');
  tools.setExecutor({
    describe: definitions => {
      if (steps !== 0) return { schemas: [] };
      const allowed = definitions.filter(definition => available(definition.name));
      if (!allowed.length) return { schemas: [] };
      const descriptions = executor.describe(allowed);
      return { schemas: descriptions.schemas.filter(schema => allowed.some(tool => tool.name === schema.name)) };
    },
    execute: input => executor.execute({ ...input, maxParallelToolCalls: 1 }),
  });
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
