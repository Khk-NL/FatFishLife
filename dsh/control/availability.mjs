import { createRequire } from 'node:module';

// 2026-10-31 老大要求用现成库判节假日：chinese-days 覆盖法定节假日、调休上班与周末，
// 每年国务院公布次年安排后作者会更新；没装这个包时退回「周末＝闲时」的简化判断。
const requireFromBundle = createRequire(import.meta.url);
let chineseDays;
try {
  // 仓库里随源码带一份（dsh/vendor/chinese-days），打包进桥后路径一致，避免线上缺依赖。
  chineseDays = requireFromBundle('./vendor/chinese-days');
} catch {
  try {
    chineseDays = requireFromBundle('../vendor/chinese-days');
  } catch {
    chineseDays = undefined;
  }
}

// 2026-10-31 老大要求：周末和节假日没有峰时，全天都按闲时算。
export function localDate(now) {
  return new Date(Number(now) + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export function restDay(now, { holidays = [], makeupWorkdays = [] } = {}) {
  const local = new Date(Number(now) + 8 * 60 * 60 * 1000);
  const date = local.toISOString().slice(0, 10);
  // 手写名单优先：官方安排没跟上或想临时改，直接写日期就行。
  if (makeupWorkdays.includes(date)) return false;
  if (holidays.includes(date)) return true;
  if (chineseDays?.isHoliday) {
    try {
      return Boolean(chineseDays.isHoliday(date));
    } catch {
      // 日期超出库的覆盖范围时落到下面的兜底判断。
    }
  }
  const day = local.getUTCDay();
  return day === 0 || day === 6;
}

/** 当天在节假日库里的名字（周一/周六这种也算），用于日志与自检。 */
export function dayLabel(now) {
  const date = localDate(now);
  try {
    return chineseDays?.getDayDetail?.(date)?.name ?? '';
  } catch {
    return '';
  }
}

export function workWindow(now, windows = [{ start: '09:00', end: '12:00' }, { start: '14:00', end: '18:00' }], calendar = {}) {
  const local = new Date(Number(now) + 8 * 60 * 60 * 1000);
  const minute = local.getUTCHours() * 60 + local.getUTCMinutes();
  const day = local.getUTCDay();
  const toMinutes = value => typeof value === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)
    ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3)) : NaN;
  for (const window of windows) {
    const start = toMinutes(window?.start), end = toMinutes(window?.end);
    const days = Array.isArray(window?.weekdays) && window.weekdays.length ? window.weekdays : [0, 1, 2, 3, 4, 5, 6];
    const afterMidnight = start > end && minute < end;
    const active = start < end ? minute >= start && minute < end : start > end && (minute >= start || afterMidnight);
    if (!active || !days.includes(afterMidnight ? (day + 6) % 7 : day)) continue;
    const startDate = Number(now) - (afterMidnight ? 86_400_000 : 0);
    if (!restDay(startDate, calendar)) return end % 60 === 0 ? end / 60 : window.end;
  }
  return undefined;
}
