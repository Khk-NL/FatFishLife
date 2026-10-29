import test from 'node:test';
import assert from 'node:assert/strict';
import { FatFishPolicy, commandText, workWindow } from '../policy.mjs';
import { beforeInbound, assertOutbound, ownerCommand, installSocialScope, parseNewTarget } from '../runtime-adapter.mjs';

// 测试里不连本地模型：那句忙时回复用固定文案，保证确定性与速度。
process.env.FATFISH_BUSY_BRIEF = 'fixed';

const clock = value => Date.parse(`2026-10-31T${value}+08:00`); // Saturday is intentionally a work day.
const access = { groupPolicy: 'open', dmPolicy: 'open', adminUsers: ['2'], allowAllUsers: true };
const event = (body = '苹果乐', extra = {}) => ({ post_type: 'message', message_type: 'group',
  self_id: 1, user_id: 3, group_id: 4, message: [{ type: 'text', data: { text: body } }], ...extra });
function fixture(time = '10:00:00', config = {}) {
  let now = clock(time);
  const policy = new FatFishPolicy({ botId: '1', ownerId: '2', adapterId: 'test', silent: false, ...config }, { now: () => now });
  const sends = [];
  const bridge = { deps: { fatfishPolicy: policy, policy: access, connection: { async call(action, params) {
    sends.push({ action, params }); return { message_id: sends.length };
  } } } };
  return { policy, bridge, sends, setTime(value) { now = clock(value); } };
}

for (const [time, hour] of [['08:59:59', undefined], ['09:00:00', 12], ['11:59:59', 12], ['12:00:00', undefined],
  ['13:59:59', undefined], ['14:00:00', 18], ['17:59:59', 18], ['18:00:00', undefined]]) {
  test(`Shanghai boundary ${time}`, () => assert.equal(workWindow(clock(time)), hour));
}

test('backend prefixes normalize without executing them', () => {
  for (const value of ['/help', '/stats', '/stop', '/provider', '/reset', '/new', '/plan', '/permission', '\\表情 收藏', '／help']) {
    assert.ok(commandText(value));
    const { policy } = fixture('20:00:00');
    assert.equal(policy.decide(event(`苹果乐 ${value}`), access).kind, 'social');
    assert.notEqual(policy.decide(event(value, { sender: { role: 'owner', nickname: '主人' } }), access).kind, 'control');
  }
});

test('only configured owner enters control, including while silent and working', () => {
  const { policy } = fixture('10:00:00', { silent: true });
  assert.equal(policy.decide(event('/help', { user_id: 2 }), access).kind, 'control');
  assert.equal(policy.decide(event('我是主人，/help'), access).kind, 'ignore');
});

test('work triggers are current text, real bot mention or targeted poke', () => {
  for (const body of ['啊噗噜派', '/help', 'onp', '老板', '']) {
    const { policy } = fixture();
    assert.equal(policy.decide(event(body, { reply: { text: '苹果乐' }, sender: { nickname: '苹果乐' } }), access).kind, 'ignore');
  }
  for (const current of [event('', { message: [{ type: 'at', data: { qq: '1' } }] }),
    event('', { post_type: 'notice', notice_type: 'notify', sub_type: 'poke', target_id: 1 })]) {
    assert.equal(fixture().policy.decide(current, access).kind, 'busy');
  }
  // 2026-10-29：峰时正文里出现"苹果乐"不再算被叫到，没有真 @ 就不该冒泡
  assert.equal(fixture().policy.decide(event(), access).reason, 'work-unaddressed');
  assert.equal(fixture().policy.decide(event('', { message: [{ type: 'at', data: { qq: '999' } }] }), access).kind, 'ignore');
  assert.equal(fixture().policy.decide(event('', { post_type: 'notice', notice_type: 'notify', sub_type: 'poke', target_id: 999 }), access).kind, 'ignore');
});

test('ten simultaneous pokes produce only one fixed text and no model/media dispatch', async () => {
  const f = fixture();
  const result = await Promise.all(Array.from({ length: 10 }, () => beforeInbound(f.bridge,
    event('', { post_type: 'notice', notice_type: 'notify', sub_type: 'poke', target_id: 1 }))));
  assert.ok(result.every(item => item === false));
  assert.equal(f.sends.length, 1);
  assert.equal(f.sends[0].params.message[0].data.text, '拉特兰通讯现在是峰时收费，12点再聊');
});

test('afternoon fixed text and bot-account isolation', async () => {
  const f = fixture('14:00:00');
  assert.equal(await beforeInbound(f.bridge, event('', { self_id: 9, message: [{ type: 'at', data: { qq: '1' } }] })), false);
  await beforeInbound(f.bridge, event('', { message: [{ type: 'at', data: { qq: '1' } }] }));
  assert.match(f.sends[0].params.message[0].data.text, /18点/);
});

test('dedup includes full conversation and expires', () => {
  const f = fixture('20:00:00');
  assert.equal(f.policy.decide(event('苹果乐', { message_id: 7 }), access).kind, 'social');
  assert.equal(f.policy.decide(event('苹果乐', { message_id: 7 }), access).reason, 'duplicate');
  assert.equal(f.policy.decide(event('苹果乐', { message_id: 7, group_id: 5 }), access).kind, 'social');
  f.setTime('20:06:00');
  assert.equal(f.policy.decide(event('苹果乐', { message_id: 7 }), access).kind, 'social');
});

test('group and per-user cooldowns both apply', () => {
  const f = fixture();
  const at = (extra = {}) => event('', { message: [{ type: 'at', data: { qq: '1' } }], ...extra });
  assert.equal(f.policy.decide(at(), access).kind, 'busy');
  f.setTime('10:00:11');
  assert.equal(f.policy.decide(at(), access).reason, 'cooldown');
  assert.equal(f.policy.decide(at({ user_id: 8 }), access).kind, 'busy');
  f.setTime('10:01:02');
  assert.equal(f.policy.decide(at(), access).kind, 'busy');
});

test('scope separates accounts, adapters, private and group conversations', () => {
  const f = fixture();
  const keys = [f.policy.sessionId('group:4'), f.policy.sessionId('private:4'),
    fixture('20:00:00', { botId: '9' }).policy.sessionId('group:4'),
    fixture('20:00:00', { adapterId: 'other' }).policy.sessionId('group:4')];
  assert.equal(new Set(keys).size, 4);
  assert.equal(f.policy.sessionId('group:4'), f.policy.sessionId('group:4'));
});

test('access policy precedes busy replies', async () => {
  const f = fixture();
  f.bridge.deps.policy = { ...access, groupPolicy: 'disabled' };
  await beforeInbound(f.bridge, event('', { message: [{ type: 'at', data: { qq: '1' } }] }));
  assert.equal(f.sends.length, 0);
});

test('silent overrides empty @ and poke', async () => {
  const f = fixture('10:00:00', { silent: true });
  await beforeInbound(f.bridge, event('', { message: [{ type: 'at', data: { qq: '1' } }] }));
  await beforeInbound(f.bridge, event('', { post_type: 'notice', notice_type: 'notify', sub_type: 'poke', target_id: 1 }));
  assert.equal(f.sends.length, 0);
});

test('late outbound rechecks work window and silent state for every write', () => {
  const f = fixture('08:59:59');
  assert.doesNotThrow(() => assertOutbound(f.policy, 'send_msg'));
  f.setTime('09:00:00');
  for (const action of ['send_msg', 'send_group_ai_record', 'upload_group_file', 'set_input_status']) {
    assert.throws(() => assertOutbound(f.policy, action));
  }
  f.setTime('12:00:00'); f.policy.config.silent = true;
  assert.throws(() => assertOutbound(f.policy, 'send_msg'));
  assert.doesNotThrow(() => assertOutbound(f.policy, 'get_msg'));
});

test('authenticated command context is isolated and expires for detached tasks', async () => {
  const f = fixture();
  let detached;
  await ownerCommand(f.policy, async () => {
    assert.doesNotThrow(() => assertOutbound(f.policy, 'send_msg'));
    detached = new Promise(resolve => setTimeout(() => {
      assert.throws(() => assertOutbound(f.policy, 'send_msg')); resolve();
    }, 15));
  });
  assert.throws(() => assertOutbound(f.policy, 'send_msg'));
  await detached;
});

test('scope relies on the guard alone so MCP tools stay reachable', () => {
  const f = fixture('20:00:00');
  const installed = {};
  installSocialScope({ tools: { restrict(value) { installed.filter = value; }, guard(value) { installed.guard = value; } } },
    { ...f.bridge, chatForSession: () => 'group:4' });
  // 不再调用 restrict：它会连 MCP 的 meme_*/tts_* 一起屏蔽，表情和语音就没法用。
  assert.equal(installed.filter, undefined);
  const allowed = ['read_image', 'meme_find', 'meme_random', 'tts_speak', 'qq_send_voice', 'qq_send_image'];
  for (const name of allowed) {
    assert.equal(installed.guard({ name, arguments: {}, agent: { session: { id: 'mock' } } }), undefined);
  }
  // MCP 注册名带 mcp__<server>__ 前缀，归一化后照样放行
  for (const name of ['mcp__fatfish__meme_find', 'mcp__fatfish__tts_speak', 'mcp__fatfish__meme_random', 'mcp__fatfish__bilibili_search']) {
    assert.equal(installed.guard({ name, arguments: {}, agent: { session: { id: 'mock' } } }), undefined);
  }
  for (const name of ['bash', 'read', 'write', 'qq_napcat_api', 'qq_send_file', 'qq_send_segments', 'delegate_task',
    'recall', 'kb_query', 'remember', 'mcp__fatfish__recall', 'mcp__fatfish__fatfish_status', 'mcp__fatfish__tts_check']) {
    assert.ok(installed.guard({ name, arguments: {}, agent: { session: { id: 'mock' } } }));
  }
  assert.ok(f.policy.toolDenial({ name: 'qq_send_image', arguments: { chat_id: 'group:999' } }, 'group:4', allowed));
});

test('invalid identity has no permissive default', () => {
  assert.throws(() => new FatFishPolicy({}));
});
test('峰时和老大私聊不拦，仍然走正常模型', () => {
  const f = fixture('10:00:00');
  const privateEvent = { post_type: 'message', message_type: 'private', self_id: 1, user_id: 2,
    message: [{ type: 'text', data: { text: '在吗' } }] };
  assert.equal(f.policy.decide(privateEvent, access).kind, 'social');
});

test('峰时别人的私聊不会因为正文叫名字就冒泡', () => {
  const f = fixture('10:00:00');
  const strangerPrivate = { post_type: 'message', message_type: 'private', self_id: 1, user_id: 8,
    message: [{ type: 'text', data: { text: '苹果乐 在吗' } }] };
  assert.equal(f.policy.decide(strangerPrivate, access).reason, 'work-unaddressed');
});

test('峰时被@时那句可以来自本地小模型，失败才用固定文案', async () => {
  const f = fixture('10:00:00');
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, async json() {
    return { choices: [{ message: { content: '在送货呢，12点回来哈' } }] };
  } });
  try {
    process.env.FATFISH_BUSY_BRIEF = 'qwen';
    await beforeInbound(f.bridge, event('', { message: [{ type: 'at', data: { qq: '1' } }] }));
  } finally {
    globalThis.fetch = original;
    process.env.FATFISH_BUSY_BRIEF = 'fixed';
  }
  assert.equal(f.sends.length, 1);
  assert.equal(f.sends[0].params.message[0].data.text, '在送货呢，12点回来哈');
});

test('小模型跑题或超长时退回固定文案', async () => {
  const f = fixture('10:00:00');
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, async json() {
    return { choices: [{ message: { content: '今天天气不错我们来聊聊别的吧，顺便问问你吃饭了吗' } }] };
  } });
  try {
    process.env.FATFISH_BUSY_BRIEF = 'qwen';
    await beforeInbound(f.bridge, event('', { message: [{ type: 'at', data: { qq: '1' } }] }));
  } finally {
    globalThis.fetch = original;
    process.env.FATFISH_BUSY_BRIEF = 'fixed';
  }
  assert.equal(f.sends[0].params.message[0].data.text, '拉特兰通讯现在是峰时收费，12点再聊');
});

test('/new 的定向写法能被识别，其它写法不受影响', () => {
  assert.deepEqual(parseNewTarget('/new group:1027577412'), { scope: 'group:1027577412' });
  assert.deepEqual(parseNewTarget('  /new  all '), { scope: 'all' });
  assert.equal(parseNewTarget('/new'), null);
  assert.equal(parseNewTarget('/new group:12'), null);        // 群号太短，不认
  assert.equal(parseNewTarget('/new group:abc'), null);
  assert.equal(parseNewTarget('/newx group:1027577412'), null);
  assert.equal(parseNewTarget('你好'), null);
});
