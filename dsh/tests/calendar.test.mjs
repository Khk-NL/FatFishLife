import test from 'node:test';
import assert from 'node:assert/strict';
import { dayLabel, restDay, workWindow } from '../policy.mjs';

// 2026-10-31 老大要求：节假日直接查现成库（dsh/vendor/chinese-days），周末和法定节假日全天算闲时。
const at = value => Date.parse(`2026-${value}+08:00`);

test('法定节假日全天算闲时', () => {
  for (const day of ['10-01T09:30:00', '10-03T15:00:00', '02-17T10:00:00', '09-27T10:00:00']) {
    assert.equal(restDay(at(day)), true, day);
    assert.equal(workWindow(at(day)), undefined, day);
  }
});

test('调休上班的周末按工作日算', () => {
  // 2026-10-10 是国庆调休的周六，官方要求上班。
  assert.equal(restDay(at('10-10T09:30:00')), false);
  assert.equal(workWindow(at('10-10T09:30:00')), 12);
});

test('普通周末仍然全天闲时，工作日按窗口判断', () => {
  assert.equal(restDay(at('10-31T09:30:00')), true);
  assert.equal(workWindow(at('11-02T09:30:00')), 12);
  assert.equal(workWindow(at('11-02T13:00:00')), undefined);
  assert.equal(workWindow(at('11-02T15:00:00')), 18);
});

test('手写名单可以覆盖库里没有的年份', () => {
  const future = Date.parse('2028-01-01T10:00:00+08:00');
  assert.equal(restDay(future, { holidays: ['2028-01-01'] }), true);
  const makeup = Date.parse('2028-01-02T10:00:00+08:00'); // 周日
  assert.equal(restDay(makeup, { makeupWorkdays: ['2028-01-02'] }), false);
});

test('节假日名字可用于自检日志', () => {
  assert.match(dayLabel(at('10-01T09:30:00')), /国庆/);
  assert.match(dayLabel(at('10-31T09:30:00')), /Saturday/);
});
