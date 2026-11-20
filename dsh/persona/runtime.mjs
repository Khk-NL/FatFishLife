import { readFileSync } from 'node:fs';
import { visibleCapabilities } from './capabilities.mjs';
import { personaPrefix, validateCard } from './model.mjs';

export const name = 'fatfish-persona';
export const inject = ['systemPrompt', 'tools'];

const houseTools = new Set(['compress', 'decompress', 'search_context', 'acp_status']);
const isHouseTool = tool => houseTools.has(tool?.split('__').at(-1));

export function apply(ctx, config = {}) {
  const source = config.cardFile || new URL('./whale.json', import.meta.url);
  const card = validateCard(JSON.parse(readFileSync(source, 'utf8').replace(/^\uFEFF/, '')));
  const profile = config.channel || 'desktop';
  ctx.systemPrompt.section({
    name: 'fatfish-persona-core', order: 7800, interpolate: false, text: personaPrefix(card, profile),
  });
  // List capabilities only for the local preset, and only from this step's admission.
  // Channel-specific guards can narrow tool access beyond the native registry.
  if (profile !== 'desktop') return;
  const base = ctx.tools.selectExecutor();
  const describe = definitions => base.describe(definitions.filter(definition => !isHouseTool(definition.name)));
  ctx.tools.setExecutor({ describe, execute: input => base.execute(input) });
  ctx.tools.guard(exec => isHouseTool(exec.name) ? '这项由宿主维护。' : undefined);
  const accepted = new WeakMap();
  ctx.systemPrompt.context({
    name: 'fatfish-visible-capabilities', order: 85, interpolate: false,
    text: ({ agent, scope, toolSet }) => {
      if (!agent) return '';
      // rc.5 refreshes accepted contexts without passing toolSet a second time.
      if (!toolSet) return accepted.get(agent) ?? '';
      const definitions = ctx.tools.definitions(scope, toolSet);
      const { schemas } = describe(definitions);
      const capabilities = visibleCapabilities(schemas ?? [], card.context);
      const text = capabilities.length ? '按任务选择本轮可用能力；参数以工具定义为准。\n' + JSON.stringify(capabilities) : '';
      accepted.set(agent, text);
      return text;
    },
  });
}
