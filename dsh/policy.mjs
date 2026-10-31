import { createHash } from 'node:crypto';

const id = value => /^(?:[1-9][0-9]*)$/.test(String(value ?? '')) ? String(value) : '';
// 正文里点得到她的名字（非忙时才认；忙时只认真 @ 和戳）。
export const NAMES = ['吞星鲸鲸', '鲸鲸', '大肥鲸', '肥鲸', '小鲸鱼', '鲸鱼娘', 'DEEPSEEK'];

/** 群级模式：老大单独控制每个群怎么对待她。 */
export const GROUP_MODES = ['talk', 'listen', 'mention', 'owner', 'quiet'];
export const GROUP_MODE_LABELS = {
  talk: '既听又说',
  listen: '只听不说',
  mention: '只回@或叫名字',
  owner: '只回老大',
  quiet: '完全不理',
};
const text = event => Array.isArray(event.message)
  ? event.message.filter(segment => segment.type === 'text').map(segment => String(segment.data?.text ?? '')).join('')
  : String(event.message ?? event.raw_message ?? '').replace(/\[CQ:[^\]]*\]/g, '');

export function commandText(value) {
  const candidate = String(value).normalize('NFKC').trimStart();
  return /^[\/\\][\p{L}\p{N}_-]/u.test(candidate) ? candidate.replace(/^\\/, '/') : undefined;
}

// 2026-10-31 老大要求：周末和节假日没有峰时，全天都按闲时算。
export function localDate(now) {
  return new Date(Number(now) + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export function restDay(now, { holidays = [], makeupWorkdays = [] } = {}) {
  const local = new Date(Number(now) + 8 * 60 * 60 * 1000);
  const date = local.toISOString().slice(0, 10);
  if (makeupWorkdays.includes(date)) return false;
  if (holidays.includes(date)) return true;
  const day = local.getUTCDay();
  return day === 0 || day === 6;
}

export function workWindow(now, windows = [{ start: '09:00', end: '12:00' }, { start: '14:00', end: '18:00' }], calendar = {}) {
  if (restDay(now, calendar)) return undefined;
  // Fixed UTC+8 avoids host timezone and daylight-saving differences.
  const local = new Date(Number(now) + 8 * 60 * 60 * 1000);
  const minute = local.getUTCHours() * 60 + local.getUTCMinutes();
  const day = local.getUTCDay();
  const toMinutes = value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  for (const window of windows) {
    const start = toMinutes(window.start), end = toMinutes(window.end);
    const days = window.weekdays ?? [0, 1, 2, 3, 4, 5, 6];
    const active = start < end ? minute >= start && minute < end && days.includes(day)
      : start > end && (minute >= start && days.includes(day) || minute < end && days.includes((day + 6) % 7));
    if (active) return end % 60 === 0 ? end / 60 : window.end;
  }
  return undefined;
}

export class FatFishPolicy {
  constructor(config, { now = Date.now, getConfig } = {}) {
    if (!id(config.ownerId) || !id(config.botId) || !config.adapterId?.trim()) {
      throw new Error('FatFish requires explicit ownerId, botId and adapterId');
    }
    this.config = { silent: true, groupCooldownMs: 10000, userCooldownMs: 60000,
      dedupMs: 300000, normalKeywords: [], groupModes: {}, groupDefaultMode: 'talk', ...config };
    this.now = now;
    this.getConfig = getConfig;
    this.seen = new Map();
    this.cooldowns = new Map();
  }

  scope(chatId) {
    if (!/^(group|private):[1-9][0-9]*$/.test(chatId)) throw new Error('Invalid QQ conversation');
    return JSON.stringify(['qq', this.config.adapterId, this.config.botId, chatId]);
  }

  sessionId(chatId) {
    return 'fatfish-qq-' + createHash('sha256').update(this.scope(chatId)).digest('hex');
  }

  calendar() { return { holidays: this.config.holidays ?? [], makeupWorkdays: this.config.makeupWorkdays ?? [] }; }

  owner(userId) { return id(userId) === String(this.config.ownerId); }

  /** 某个群当前的模式；没单独设过就用 groupDefaultMode。 */
  groupMode(groupId) {
    const table = this.config.groupModes;
    const explicit = table && Object.prototype.hasOwnProperty.call(table, String(groupId))
      ? table[String(groupId)] : undefined;
    const value = explicit ?? this.config.groupDefaultMode ?? 'talk';
    return GROUP_MODES.includes(value) ? value : 'talk';
  }

  /** 设置某个群的模式，返回设置前的值。 */
  setGroupMode(groupId, mode) {
    if (!GROUP_MODES.includes(mode)) throw new Error('未知群模式: ' + mode);
    const target = String(groupId);
    if (!id(target)) throw new Error('群号不合法: ' + target);
    const before = this.groupMode(target);
    this.config.groupModes = { ...(this.config.groupModes ?? {}), [target]: mode };
    return before;
  }

  /** 当前所有单独设过模式的群。 */
  modeTable() {
    return Object.entries(this.config.groupModes ?? {})
      .filter(([, mode]) => GROUP_MODES.includes(mode))
      .map(([groupId, mode]) => ({ groupId, mode, label: GROUP_MODE_LABELS[mode] }));
  }

  decide(event, access) {
    if (this.getConfig) Object.assign(this.config, this.getConfig());
    if (id(event.self_id) !== String(this.config.botId)) return { kind: 'ignore', reason: 'account' };
    const userId = id(event.user_id);
    if (!userId || userId === String(this.config.botId)) return { kind: 'ignore', reason: 'sender' };
    const poke = event.post_type === 'notice' && event.notice_type === 'notify' && event.sub_type === 'poke';
    const message = event.post_type === 'message' && ['group', 'private'].includes(event.message_type);
    if (!poke && !message) return { kind: 'ignore', reason: 'event' };
    if (poke && id(event.target_id) !== String(this.config.botId)) return { kind: 'ignore', reason: 'poke-target' };
    const kind = id(event.group_id) ? 'group' : 'private';
    const target = kind === 'group' ? id(event.group_id) : userId;
    if (!target) return { kind: 'ignore', reason: 'target' };
    if (kind === 'group' ? access.groupPolicy === 'disabled' ||
      access.groupPolicy === 'allowlist' && !access.groupAllowFrom.includes(target)
      : access.dmPolicy === 'disabled' || (access.dmPolicy === 'allowlist'
        ? !access.allowFrom.includes(userId) : !access.allowAllUsers && !access.adminUsers.includes(userId))) {
      return { kind: 'ignore', reason: 'access' };
    }
    const chatId = `${kind}:${target}`;
    const scope = this.scope(chatId);
    const now = this.now();
    this.prune(this.seen, now, this.config.dedupMs);
    const messageId = event.message_id == null ? undefined : `${scope}:${event.message_id}`;
    if (messageId && this.seen.has(messageId)) return { kind: 'ignore', reason: 'duplicate' };
    if (messageId) this.seen.set(messageId, now);
    const body = poke ? '' : text(event);
    const command = commandText(body);
    // Only a trusted, current sender may enter the backend router. This is
    // independent of group roles, nicknames, message text and the model.
    if (this.owner(userId) && command) return { kind: 'control', chatId, userId, command };
    const mentioned = Array.isArray(event.message) && event.message.some(segment =>
      segment.type === 'at' && id(segment.data?.qq) === String(this.config.botId));
    // 群级开关：老大可以在私聊里给每个群单独定「既听又说 / 只听不说 / 只回@ / 只回老大 / 完全不理」。
    // observe=true 表示这条不进模型，但值得记下来（她的"听"）。
    if (kind === 'group') {
      const mode = this.groupMode(target);
      if (mode === 'quiet') return { kind: 'ignore', reason: 'group-quiet' };
      if (mode === 'listen') return { kind: 'ignore', reason: 'group-listen', observe: true };
      if (mode === 'owner' && !this.owner(userId)) return { kind: 'ignore', reason: 'group-owner-only', observe: true };
      if (mode === 'mention' && !(poke || mentioned)) return { kind: 'ignore', reason: 'group-mention-only', observe: true };
    }
    if (this.config.silent) return { kind: 'ignore', reason: 'silent' };
    // 非忙碌时仍然认「正文叫名字」；忙碌时的判定见下面 addressed。
    const named = NAMES.some(name => body.includes(name));
    const explicit = poke || mentioned || named;
    const returnHour = workWindow(now, this.config.busyWindows, this.calendar());
    // 和老大本人的私聊不受忙碌窗口限制：峰时也用正常模型回他。
    const ownerPrivate = kind === 'private' && this.owner(userId);
    if (returnHour !== undefined && !ownerPrivate) {
      // 忙碌时段只认「真 @」和「戳」：正文里出现名字、被引用、被提及都不算。
      // 2026-10-29 按老大要求改的 —— 峰时不该因为别人提到关键词就冒泡。
      const addressed = poke || mentioned;
      if (!addressed) return { kind: 'ignore', reason: 'work-unaddressed' };
      this.prune(this.cooldowns, now, Math.max(this.config.groupCooldownMs, this.config.userCooldownMs));
      const groupKey = `chat:${scope}`;
      const userKey = `user:${scope}:${userId}`;
      if (now - (this.cooldowns.get(groupKey) ?? -Infinity) < this.config.groupCooldownMs ||
          now - (this.cooldowns.get(userKey) ?? -Infinity) < this.config.userCooldownMs) {
        return { kind: 'ignore', reason: 'cooldown' };
      }
      // Reserve synchronously before awaiting delivery, preventing a burst of pokes.
      this.cooldowns.set(groupKey, now);
      this.cooldowns.set(userKey, now);
      return { kind: 'busy', chatId, userId, returnHour,
        text: this.busyText(returnHour) };
    }
    if (kind === 'group' && !explicit && !this.config.normalKeywords.some(word => word && body.includes(word))) {
      return { kind: 'ignore', reason: 'unaddressed' };
    }
    return { kind: 'social', chatId, userId, poke };
  }

  prune(map, now, ttl) {
    for (const [key, timestamp] of map) if (now - timestamp >= ttl) map.delete(key);
    while (map.size >= 4096) map.delete(map.keys().next().value);
  }

  /** 忙时文案：模板里的 {hour} 换成 12 / 18，或窗口结束时刻。 */
  busyText(returnHour) {
    const template = String(this.config.busyText || 'DeepSeek这会儿峰时，{hour}再来找我');
    const value = typeof returnHour === 'number' ? returnHour + '点' : String(returnHour ?? '');
    return template.replace(/\{hour\}点/g, value).replace(/\{hour\}/g, value);
  }

  /**
   * 能不能往外发。
   * 2026-10-30 修：以前无参调用（busy=false）在忙时窗口里返回 false，把主人私聊的
   * 正常回复也一起拦了（trace 里是 "FatFish outbound paused"）。忙时该不该说话由
   * decide() 判：闲人消息得到 busy/ignore，主人私聊和真实 @ 仍然要回。主动开口的
   * 时段由 control/proactive.mjs 的 inBusyWindow 把门，所以这里只看全局静音；
   * busy=true 仅表示"这是忙时那句模板回复"，要落在对应整点窗口里才发。
   */
  canSend({ busy = false, returnHour } = {}) {
    if (this.getConfig) Object.assign(this.config, this.getConfig());
    if (this.config.silent) return false;
    if (!busy) return true;
    const hour = workWindow(this.now(), this.config.busyWindows, this.calendar());
    return hour !== undefined && hour === returnHour;
  }

  toolDenial(exec, chatId, allowed = []) {
    if (!this.canSend()) return 'FatFish social activity is paused';
    // Guard covers both inherited tools and tools registered by this scope.
    // MCP 工具注册名带 mcp__<server>__ 前缀，白名单写的是短名，先归一化再比。
    const name = String(exec.name ?? '');
    const short = name.includes('__') ? name.split('__').pop() : name;
    if (!allowed.includes(name) && !allowed.includes(short)) return 'Tool is outside this social capability set';
    if (exec.arguments?.chat_id !== undefined && exec.arguments.chat_id !== chatId) return 'Cross-conversation target denied';
    return undefined;
  }
}
