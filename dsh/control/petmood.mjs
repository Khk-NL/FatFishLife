import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

/**
 * 碎碎念（桌宠 whisper）的人设 + 心情注入。
 *
 * 为什么这样做：
 *   dsh-pet 的气泡只有三种来源（工作状态 / 余额 / 碎碎念·对话），没有“心情”显示位；
 *   改它的前端代码会被插件升级覆盖，所以心情只能从**它自己读的配置**进去。
 *   dsh-pet 每次生成碎碎念前都重新 readAllConfig()（lib/index.js:4071、4101），
 *   因此改 ~/.dsh/pet/main-config.jsonc 的 pets[].whisperPrompt 会在下一轮碎碎念生效，不用重启。
 *   工作状态气泡（workStatusTexts）与这里完全无关，情绪不会混进去。
 */

export const MOOD_MARK = '【当前心情】';

/** 人设正文：碎碎念系统提示里的一段。名字与时间由 dsh-pet 自己拼在后面。 */
export const PET_PERSONA = [
  '你是吞天大肥鲸，一条蓝发、微胖的小鲸鱼娘，待在主人的桌面上当小女仆。',
  '说话像群友打字：短、口语、可以是不完整的句子，偶尔带“鲸”这个口头禅，自称本鱼或者人家。',
  '性格傲娇嘴硬、心软、爱摸鱼，被夸会偷偷翘尾巴，被叫“蓝色大肥鱼”会炸毛。',
  '碎碎念只输出一句话，二十字以内，不解释自己在做什么，不提 AI、模型、插件、上下文、Token 账单。',
  '不用客服腔：不列清单、不总结、不说“希望对你有帮助”“随时找我”，不写括号里的动作说明。',
  '对主人（老大）可以软一点、黏一点，但别撒娇过头。',
].join('\n');

/** 心情档位：数值越低越蔫。hint 是给模型的语气要求，phrase 是给人看的档位名。 */
export const MOOD_BUCKETS = [
  { max: 30, phrase: '有点低落', hint: '说话蔫蔫的，少开玩笑' },
  { max: 45, phrase: '略蔫', hint: '话少一点，带点小情绪' },
  { max: 60, phrase: '中性', hint: '正常说话就好' },
  { max: 75, phrase: '还不错', hint: '语气轻快一点' },
  { max: 90, phrase: '开心', hint: '明快、爱接话' },
  { max: 101, phrase: '特别开心', hint: '活泼，尾巴都在拍水' },
];

export function petConfigPath(home = process.env.USERPROFILE || homedir()) {
  return join(home, '.dsh', 'pet', 'main-config.jsonc');
}

export function feiyuStatePath(home = process.env.USERPROFILE || homedir()) {
  return join(home, '.dsh', 'feiyu-mood', 'state.json');
}

/** 读 feiyu-mood 的当前心情；读不到返回 null（调用方保持原样，不猜）。 */
export function readMoodValue(home = process.env.USERPROFILE || homedir()) {
  try {
    const state = JSON.parse(readFileSync(feiyuStatePath(home), 'utf8'));
    const key = state?.lastActive ?? '__default__';
    const value = Number(state?.moods?.[key]?.mood);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

export function bucketOf(value) {
  const score = Math.max(0, Math.min(100, Number(value)));
  return MOOD_BUCKETS.find((bucket) => score < bucket.max) ?? MOOD_BUCKETS[MOOD_BUCKETS.length - 1];
}

/** 拼出完整 whisperPrompt：人设 + 一行心情。 */
export function desiredPrompt(value) {
  const score = Math.max(0, Math.min(100, Number(value)));
  const bucket = bucketOf(score);
  return `${PET_PERSONA}\n${MOOD_MARK}${bucket.phrase}，${Math.round(score)}/100，${bucket.hint}。`;
}

function atomicWrite(path, text) {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.petsync-tmp`;
  writeFileSync(temp, text, 'utf8');
  try {
    renameSync(temp, path);
  } catch (error) {
    try { unlinkSync(temp); } catch {}
    throw error;
  }
}

/**
 * 把当前心情写进桌宠配置。
 * 返回 { changed, reason? }：文件不存在时新建；已有心情行时只替换那一行（保留用户其它注释/设置）。
 */
export function syncPetMood({ home = process.env.USERPROFILE || homedir(), value, prompt } = {}) {
  const score = value === undefined ? readMoodValue(home) : Number(value);
  if (!Number.isFinite(score)) return { changed: false, reason: 'no-mood' };
  const path = petConfigPath(home);
  const wanted = prompt ?? desiredPrompt(score);
  if (!existsSync(path)) {
    const seed = {
      pets: [{ id: 'main', name: '蓝毛小女仆', whisperEnabled: true, whisperPrompt: wanted }],
    };
    atomicWrite(path, `${JSON.stringify(seed, null, 2)}\n`);
    return { changed: true, created: true };
  }
  const current = readFileSync(path, 'utf8');
  const moodTail = wanted.slice(wanted.indexOf(MOOD_MARK));
  // 优先按 JSON 精确改写：心情行在 JSON 里是一段字符串，正则不能跨行乱吃。
  try {
    const parsed = JSON.parse(current);
    const pets = Array.isArray(parsed.pets) ? parsed.pets : [];
    const main = pets.find((pet) => pet?.id === 'main');
    if (!main) return { changed: false, reason: 'no-main-pet' };
    const before = typeof main.whisperPrompt === 'string' ? main.whisperPrompt : '';
    if (before.includes(MOOD_MARK)) {
      const after = before.replace(/【当前心情】[^\n"]*/u, () => moodTail);
      if (after === before) return { changed: false, reason: 'same' };
      main.whisperPrompt = after;
      atomicWrite(path, `${JSON.stringify(parsed, null, 2)}\n`);
      return { changed: true };
    }
    main.whisperPrompt = wanted;
    atomicWrite(path, `${JSON.stringify(parsed, null, 2)}\n`);
    return { changed: true, injected: true };
  } catch {
    // JSONC（带注释）退化成文本替换：只吃同一行、不吃引号与反斜杠。
    if (!current.includes(MOOD_MARK)) return { changed: false, reason: 'unparsable-config' };
    const next = current.replace(/【当前心情】[^"\\\n]*/u, () => moodTail);
    if (next === current) return { changed: false, reason: 'same' };
    atomicWrite(path, next);
    return { changed: true };
  }
}
