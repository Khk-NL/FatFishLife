import { readFileSync } from 'node:fs';
import { DEFAULT_WHALE_LENGTH } from './whale-voice.mjs';

export function readRuntimeOptions(path = process.env.FATFISH_BEHAVIOR_FILE
  || 'D:/Code/Projects/FatFishLife/data/dsh/runtime-behavior.json') {
  let state;
  try {
    state = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    if (!(error instanceof SyntaxError) && !['ENOENT', 'EACCES', 'EPERM'].includes(error.code)) throw error;
  }
  const length = value => Number.isInteger(value) && value >= 1 && value <= 1000 ? value : DEFAULT_WHALE_LENGTH;
  const views = state?.bili?.min_views;
  const workBuddyMinimum = state?.model_routing?.workbuddy_min_credits;
  const codexMinimum = state?.model_routing?.codex_min_remaining_percent;
  const codexWeeklyMinimum = state?.model_routing?.codex_min_weekly_remaining_percent;
  const percent = (value, fallback) => Number.isFinite(value) && value >= 0 && value <= 100 ? value : fallback;
  return {
    chatMaxChars: length(state?.style?.chat_max_chars),
    commentMaxChars: length(state?.style?.comment_max_chars),
    minimumViews: Number.isSafeInteger(views) && views >= 0 ? views : 100_000,
    workBuddyMinimum: Number.isSafeInteger(workBuddyMinimum) && workBuddyMinimum >= 0 ? workBuddyMinimum : 50,
    codexMinimum: percent(codexMinimum, 80),
    codexWeeklyMinimum: percent(codexWeeklyMinimum, 50),
  };
}
