import { createHash, randomUUID } from 'node:crypto';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

export const DEFAULT_WINDOWS = [{ start: '09:00', end: '12:00', weekdays: [0, 1, 2, 3, 4, 5, 6] },
  { start: '14:00', end: '18:00', weekdays: [0, 1, 2, 3, 4, 5, 6] }];

export function compileSettings(config) {
  for (const channel of ['voice', 'meme']) {
    const item = config[channel];
    if (item.basePercent > item.maxPercent) throw new Error(`${channel}: 基础概率不能大于上限`);
  }
  if (config.workflows.daily.basePercent > config.workflows.daily.maxPercent) throw new Error('动态基础概率不能大于上限');
  for (const window of config.busyWindows) if (window.start === window.end) throw new Error('忙碌窗口开始和结束不能相同');
  const policy = { ...config.identity, silent: config.reply.silent, normalKeywords: config.reply.normalKeywords,
    groupCooldownMs: config.reply.groupCooldownSeconds * 1000, userCooldownMs: config.reply.userCooldownSeconds * 1000,
    dedupMs: config.reply.dedupSeconds * 1000, busyWindows: config.busyWindows };
  const channel = item => ({ enabled: item.enabled, base: item.basePercent / 100, step: item.stepPercent / 100, max: item.maxPercent / 100 });
  const behavior = { version: 1,
    voice: { ...channel(config.voice), text_alongside_voice: config.voice.textAlongsideVoice,
      provider: config.voice.provider, providers: config.voice.providers,
      allow_synthesis: config.voice.allowSynthesis ?? false,
      cooldown_seconds: config.voice.cooldownSeconds, max_text_length: config.voice.maxTextLength || null,
      manual_trigger: config.voice.manualTrigger, fallback_to_text: true },
    meme: { ...channel(config.meme), manual_trigger: config.meme.manualTrigger, max_per_message: config.meme.maxPerMessage },
    life: { enabled: config.workflows.daily.enabled, publish_enabled: config.workflows.daily.publishEnabled,
      reflection_time: config.workflows.daily.time, base: config.workflows.daily.basePercent / 100,
      step: config.workflows.daily.stepPercent / 100, max: config.workflows.daily.maxPercent / 100,
      requires_share_intent_and_public_evidence: true },
    bili: { auto_scroll_enabled: config.workflows.recommend.enabled, auto_scroll_times: config.workflows.recommend.times.join(','),
      auto_scroll_count: config.workflows.recommend.maxVideos,
      auto_scroll_comment_enabled: config.workflows.recommend.commentEnabled, study_enabled: config.workflows.study.enabled,
      study_time: config.workflows.study.time, auto_reply: config.workflows.comments.enabled,
      auto_reply_owner_only: config.workflows.comments.ownerOnly },
    proactive: { enabled: false },
  };
  const revision = createHash('sha256').update(JSON.stringify({ policy, behavior })).digest('hex');
  return { policy, behavior, revision };
}

export async function persistSettings(config) {
  const compiled = compileSettings(config);
  await mkdir(config.dataDirectory, { recursive: true });
  for (const [name, value] of [['runtime-policy.json', compiled.policy], ['runtime-behavior.json', compiled.behavior]]) {
    const path = join(config.dataDirectory, name);
    const temporary = `${path}.${randomUUID()}.tmp`;
    await writeFile(temporary, JSON.stringify(value, null, 2) + '\n');
    await rename(temporary, path);
  }
  return compiled;
}
