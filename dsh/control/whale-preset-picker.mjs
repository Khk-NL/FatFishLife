const social = 'whale-social';
const desktop = 'whale-lifepilot';

export function whalePresetRoster(roster) {
  if (!Array.isArray(roster?.presets)) return roster;
  const shared = roster.presets.find(preset => preset.id === social);
  const local = roster.presets.find(preset => preset.id === desktop);
  if (!shared || !local || local.broken !== undefined || shared.isDefault) return roster;
  return {
    ...roster,
    presets: roster.presets.filter(preset => preset.id !== social).map(preset => preset.id === desktop
      ? { ...preset, name: '鲸鲸', description: '与鲸鲸聊天，使用记忆、知识库和日常工具。' }
      : preset),
  };
}

export function installWhalePresetPicker(ctx) {
  ctx.inject(['agentPresets'], scope => {
    const registry = scope.agentPresets;
    const original = registry.remoteExportList;
    if (typeof original !== 'function') return;
    scope.effect(() => {
      const show = async function (...args) {
        return whalePresetRoster(await original.apply(this, args));
      };
      registry.remoteExportList = show;
      return () => {
        if (registry.remoteExportList === show) registry.remoteExportList = original;
      };
    });
  });
}
