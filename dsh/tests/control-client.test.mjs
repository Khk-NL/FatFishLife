// Offline client contract checks; these do not replace desktop visual validation.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

function setup({ accepted = true } = {}) {
  const value = { reply: { silent: true, groupCooldownSeconds: 10, userCooldownSeconds: 60 },
    busyWindows: [{ start: '09:00', end: '12:00', weekdays: [0,1,2,3,4,5,6] }],
    voice: { basePercent: 15, maxPercent: 100, provider: 'siliconflow' },
    meme: { basePercent: 35, maxPercent: 90 }, workflows: { daily: { basePercent: 20, maxPercent: 100 } } };
  const writes = [], states = [];
  let cursor = 0, plugin, page;
  const scope = { getSnapshot: () => ({ value, revision: 17, writable: true }), subscribe: () => () => {},
    mutate: async (ops, revision) => { writes.push({ ops, revision }); return accepted; } };
  const React = { createElement: (type, props, ...children) => ({ type, props: props ?? {}, children }),
    useMemo: fn => fn(), useSyncExternalStore: (_subscribe, read) => read(),
    useState: initial => { const index = cursor++; if (!(index in states)) states[index] = initial;
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next; }]; } };
  runInNewContext(readFileSync(new URL('../control/client.js', import.meta.url), 'utf8'), {
    structuredClone, window: { __ModuleLoader__: { load: definition => { plugin = definition.factory(name => {
      assert.equal(name, 'react'); return React;
    }); } } },
  });
  plugin.apply({ effect: fn => fn(), configForms: { get: id => { assert.equal(id, 'fatfish-control'); return scope; },
    whileServed: (_ids, fn) => fn() }, slots: { inject: (_name, fn) => fn(),
    register: (options, component) => { page = { options, component }; return () => {}; } } });
  const render = () => { cursor = 0; return page.component({ scope, view: 'detail' }); };
  return { render, writes, page, value };
}
function find(node, predicate) {
  if (!node || typeof node !== 'object') return undefined;
  if (predicate(node)) return node;
  return node.children.flat(Infinity).map(child => find(child, predicate)).find(Boolean);
}

test('native page registers and exposes busy windows, probabilities and provider controls', () => {
  const ui = setup();
  assert.equal(ui.page.options.id, 'fatfish-control');
  const tree = ui.render();
  for (const id of ['fatfish-reply-groupCooldownSeconds', 'fatfish-busyWindows-0-start',
    'fatfish-voice-basePercent', 'fatfish-meme-basePercent', 'fatfish-voice-provider']) {
    assert.ok(find(tree, node => node.props.id === id), id);
  }
});

test('save writes only the edited group with the original revision fence', async () => {
  const ui = setup();
  find(ui.render(), node => node.props.id === 'fatfish-reply-groupCooldownSeconds').props.onChange({ target: { value: '11' } });
  await ui.render().props.onSubmit({ preventDefault() {} });
  assert.equal(ui.writes.length, 1);
  assert.equal(ui.writes[0].revision, 17);
  assert.equal(ui.writes[0].ops.length, 1);
  assert.deepEqual(Array.from(ui.writes[0].ops[0].path), ['reply']);
  assert.equal(ui.writes[0].ops[0].value.groupCooldownSeconds, 11);
  assert.equal(ui.value.voice.basePercent, 15);
});

test('conflict preserves the draft rather than overwriting a concurrent edit', async () => {
  const ui = setup({ accepted: false });
  find(ui.render(), node => node.props.id === 'fatfish-reply-groupCooldownSeconds').props.onChange({ target: { value: '11' } });
  await ui.render().props.onSubmit({ preventDefault() {} });
  const tree = ui.render();
  assert.equal(find(tree, node => node.props.id === 'fatfish-reply-groupCooldownSeconds').props.value, 11);
  assert.match(find(tree, node => node.props.role === 'status').children.join(''), /草稿已保留/);
});

test('invalid cross-field probabilities stay in the editor without a host write', async () => {
  const ui = setup();
  find(ui.render(), node => node.props.id === 'fatfish-meme-basePercent').props.onChange({ target: { value: '99' } });
  await ui.render().props.onSubmit({ preventDefault() {} });
  assert.equal(ui.writes.length, 0);
  assert.match(find(ui.render(), node => node.props.role === 'status').children.join(''), /基础概率不能高于上限/);
});
