/**
 * speak-up 的「目标会话」自动校正。
 *
 * 背景（2026-11-05 实测）：
 *   QQ 桥给一个聊天建的会话 id 是 `<基础id>-<实例后缀>`（例如
 *   `fatfish-qq-c83c…-mvxdynm2`），后缀**每次宿主启动都会变**。
 *   而设置页里勾的是不带后缀的 `<基础id>`，那条记录只是历史残留、没有 agent。
 *   结果 speak-up 每一轮都判定「目标会话不能说话」，直接跳过——不是概率问题，
 *   也不是安静时段问题，是 id 对不上，它一句话都发不出来。
 *
 * 这个模块只做一件事：算出老大私聊的**基础 id**，在 ~/.dsh/sessions 里找它下面
 * 最新、且有内容的实例目录，把 `speak-up-config.json` 的「目标会话」改成那个实例 id。
 * 幂等：已经对上了就不写文件。
 */
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

/** 和 dsh/runtime-adapter.mjs 的 scope() 保持同一口径（改这里要一起改）。 */
export function scopeKey(chatId, { adapterId, botId }) {
  return JSON.stringify(['qq', adapterId, botId, chatId]);
}

export function sessionBaseId(chatId, identity) {
  return 'fatfish-qq-' + createHash('sha256').update(scopeKey(chatId, identity)).digest('hex');
}

export function ownerChatId(ownerId) {
  return `private:${ownerId}`;
}

/**
 * 在会话根目录里找 `<base>-*` 的实例，按目录里 session.v4.jsonl.zstd 的修改时间取最新。
 * 找不到返回 undefined（此时不动配置，避免把设置改坏）。
 */
export const QQ_WORKSPACE = 'D:/Code/Projects/FatFishLife/data/dsh/qq-work';

/** DSH 的会话桶名由工作区路径生成，例如 `--D-Code-Projects-FatFishLife-data-dsh-qq-work--`。 */
export function workspaceBucket(workspace = QQ_WORKSPACE) {
  const flat = String(workspace).replace(/^([A-Za-z]):/, '$1').replace(/[\\/]+/g, '-');
  return '--' + flat + '--';
}

export function newestInstance(sessionsRoot, baseId, { bucket } = {}) {
  let best;
  const buckets = bucket ? [bucket] : safeReaddir(sessionsRoot);
  for (const name of buckets) {
    const bucketPath = join(sessionsRoot, name);
    for (const name of safeReaddir(bucketPath)) {
      if (!name.startsWith(`${baseId}-`)) continue;
      const file = join(bucketPath, name, 'session.v4.jsonl.zstd');
      if (!existsSync(file)) continue;
      let mtime = 0;
      try {
        mtime = statSync(file).mtimeMs;
      } catch {
        continue;
      }
      if (!best || mtime > best.mtime) best = { id: name, mtime };
    }
  }
  return best?.id;
}

function safeReaddir(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

export function speakUpConfigPath(home = process.env.USERPROFILE || homedir()) {
  return join(home, '.dsh', 'speak-up-config.json');
}

/**
 * 把配置里的目标会话换成最新实例 id；已经是它就不写盘。
 * @returns {{ok: boolean, changed: boolean, target?: string, reason?: string}}
 */
export function ensureSpeakUpTarget({
  home = process.env.USERPROFILE || homedir(),
  sessionsRoot,
  identity,
  ownerId,
  now = Date.now(),
} = {}) {
  const root = sessionsRoot ?? join(home, '.dsh', 'sessions');
  const file = speakUpConfigPath(home);
  if (!existsSync(file)) return { ok: false, changed: false, reason: 'no-config' };
  if (!identity?.adapterId || !identity?.botId || !ownerId) {
    return { ok: false, changed: false, reason: 'no-identity' };
  }
  const base = sessionBaseId(ownerChatId(ownerId), identity);
  const live = newestInstance(root, base, { bucket: workspaceBucket() });
  // 只用 qq-work 这个工作区的会话，避免把她主界面/别的项目的会话也当成目标。
  if (!live) return { ok: false, changed: false, reason: 'no-instance' };
  const label = '私聊 · 老大';


  let config;
  try {
    config = JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return { ok: false, changed: false, reason: 'bad-config' };
  }
  const current = Array.isArray(config.目标会话) ? config.目标会话.map(String) : [];
  if (current.length === 1 && current[0] === live) {
    return { ok: true, changed: false, target: live, at: now };
  }
  config.目标会话 = [live];
  try {
    writeFileSync(file, JSON.stringify(config, null, 2) + '\n', 'utf8');
  } catch (error) {
    return { ok: false, changed: false, target: live, reason: error?.message ?? 'write-failed' };
  }
  return { ok: true, changed: true, target: live, previous: current, at: now };
}

/** 从 dsh/policy.json 读身份（adapterId/botId/ownerId），读不到返回 undefined。 */
export function identityFromPolicyFile(file) {
  try {
    const data = JSON.parse(readFileSync(file, 'utf8'));
    if (!data?.adapterId || !data?.botId || !data?.ownerId) return undefined;
    return { adapterId: String(data.adapterId), botId: String(data.botId), ownerId: String(data.ownerId) };
  } catch {
    return undefined;
  }
}
