// P1 端到端冒烟：假 OneBot + 假模型，验证 beforeInbound/outbound 整条链路。
// 不连接真实 QQ，不调用真实模型。
import test from 'node:test';
import assert from 'node:assert/strict';
import { FatFishPolicy } from '../policy.mjs';
import { beforeInbound, assertOutbound, ownerCommand } from '../runtime-adapter.mjs';

const clock = value => Date.parse(`2026-11-02T${value}+08:00`); // 周一，周末不算忙时
const OWNER = '3124904460';
const BOT = '1670515707';
const ADAPTER = 'napcat';

function policyAt(value, extra = {}) {
  return new FatFishPolicy(
    { ownerId: OWNER, botId: BOT, adapterId: ADAPTER, silent: false, ...extra },
    { now: () => clock(value) },
  );
}

function fakeBridge(policy) {
  const calls = [];
  return {
    calls,
    deps: {
      fatfishPolicy: policy,
      policy: { groupPolicy: 'open', dmPolicy: 'open', adminUsers: [OWNER], allowAllUsers: true },
      connection: {
        call: async (action, params) => {
          calls.push({ action, params });
          return { message_id: calls.length };
        },
      },
      log: () => {},
    },
    chatForSession: () => 'group:774053915',
  };
}

const groupText = (body, extra = {}) => ({
  post_type: 'message',
  message_type: 'group',
  group_id: 774053915,
  user_id: 2584815905,
  self_id: Number(BOT),
  message_id: 900 + Math.floor(Math.random() * 100),
  message: [{ type: 'text', data: { text: body } }],
  ...extra,
});

test('工作时段的 @ 只发一条固定文案，且不带模型输出', async () => {
  const policy = policyAt('10:30');
  const bridge = fakeBridge(policy);
  const result = await beforeInbound(bridge, groupText('大肥鲸你在吗', {
    message: [
      { type: 'at', data: { qq: BOT } },
      { type: 'text', data: { text: '你在吗' } },
    ],
  }));
  assert.equal(result, false, '工作时段被拦截，不再进入 Agent');
  assert.equal(bridge.calls.length, 1, '只发一条');
  assert.match(bridge.calls[0].params.message[0].data.text, /12点/);
  assert.equal(bridge.calls[0].action, 'send_msg');
});

test('工作时段非 @ 的闲聊完全不发声', async () => {
  const policy = policyAt('15:10');
  const bridge = fakeBridge(policy);
  const result = await beforeInbound(bridge, groupText('今天好热'));
  assert.equal(result, false);
  assert.equal(bridge.calls.length, 0);
});

test('正常时段 @ 会进入 Agent，不预先回复', async () => {
  const policy = policyAt('19:30');
  const bridge = fakeBridge(policy);
  const event = await beforeInbound(bridge, groupText('在吗', {
    message: [
      { type: 'at', data: { qq: BOT } },
      { type: 'text', data: { text: '在吗' } },
    ],
  }));
  assert.equal(bridge.calls.length, 0, '正常时段不代发文案');
  assert.ok(event, '事件继续向下游传递');
  assert.equal(event.post_type, 'message');
});

test('戳一戳在工作时段换成一跳文字表示，不伪造 @', async () => {
  const policy = policyAt('09:05');
  const bridge = fakeBridge(policy);
  await beforeInbound(bridge, {
    post_type: 'notice',
    notice_type: 'notify',
    sub_type: 'poke',
    target_id: Number(BOT),
    user_id: 2584815905,
    group_id: 774053915,
    self_id: Number(BOT),
  });
  assert.equal(bridge.calls.length, 1);
  assert.match(bridge.calls[0].params.message[0].data.text, /12点/);
});

test('静默时任何 inbound 都不产生发送', async () => {
  const policy = policyAt('19:30', { silent: true });
  const bridge = fakeBridge(policy);
  const result = await beforeInbound(bridge, groupText('大肥鲸'));
  assert.equal(result, false);
  assert.equal(bridge.calls.length, 0);
});

test('普通用户的后台命令当作正文，不触发控制路由', async () => {
  const policy = policyAt('19:30');
  const bridge = fakeBridge(policy);
  const event = await beforeInbound(bridge, groupText('/reset', {
    message: [{ type: 'at', data: { qq: BOT } }, { type: 'text', data: { text: '/reset' } }],
  }));
  assert.ok(event, '有效 @ 下非主人命令作为社交正文继续传递');
  assert.equal(event.message.at(-1).data.text, '/reset');
  assert.equal(bridge.calls.length, 0, '非主人不回复拒绝模板');
});

test('临时任务脱离 ownerCommand 后失去控制权限', async () => {
  // 用全局静音来体现差别：控制通道内可以发，脱离后不可发
  const policy = policyAt('10:30', { silent: true });
  const parked = [];
  await ownerCommand(policy, async () => {
    assert.doesNotThrow(() => assertOutbound(policy, 'send_private_msg'));
    parked.push(() => assertOutbound(policy, 'send_private_msg'));
  });
  assert.throws(() => parked[0](), /paused/);
});

test('进入工作时段不会拦住已经决定要回的普通外发', () => {
  let current = clock('19:30');
  const policy = new FatFishPolicy(
    { ownerId: OWNER, botId: BOT, adapterId: ADAPTER, silent: false },
    { now: () => current },
  );
  assert.doesNotThrow(() => assertOutbound(policy, 'send_group_msg'));
  current = clock('10:00');
  // 2026-10-30 修：忙时拦话由 decide() 负责，外发闸门只认全局静音；
  // 以前这里会抛 "FatFish outbound paused"，把主人私聊的正常回复也拦掉了。
  assert.doesNotThrow(() => assertOutbound(policy, 'send_group_msg'));
  policy.config.silent = true;
  assert.throws(() => assertOutbound(policy, 'send_group_msg'), /paused/);
});

test('读操作在静默和工作时段仍允许', () => {
  const policy = policyAt('10:00', { silent: true });
  assert.doesNotThrow(() => assertOutbound(policy, 'get_group_list'));
  assert.doesNotThrow(() => assertOutbound(policy, 'can_send_image'));
  assert.throws(() => assertOutbound(policy, 'send_msg'), /paused/);
});

test('重复 message_id 只处理一次', async () => {
  const policy = policyAt('19:30');
  const bridge = fakeBridge(policy);
  const event = groupText('在吗', {
    message_id: 4242,
    message: [
      { type: 'at', data: { qq: BOT } },
      { type: 'text', data: { text: '在吗' } },
    ],
  });
  const first = await beforeInbound(bridge, event);
  const second = await beforeInbound(bridge, { ...event });
  assert.ok(first);
  assert.equal(second, false, '重复消息被丢弃');
});

test('别的 QQ 帐号的事件全部忽略', async () => {
  const policy = policyAt('19:30');
  const bridge = fakeBridge(policy);
  const result = await beforeInbound(bridge, groupText('大肥鲸', { self_id: 999999 }));
  assert.equal(result, false);
  assert.equal(bridge.calls.length, 0);
});
