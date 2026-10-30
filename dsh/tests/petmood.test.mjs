import { strict as assert } from 'node:assert';
import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { MOOD_MARK, desiredPrompt, readMoodValue, syncPetMood } from '../control/petmood.mjs';

function sandbox() {
  const root = mkdtempSync(join(tmpdir(), 'petmood-'));
  mkdirSync(join(root, '.dsh', 'pet'), { recursive: true });
  mkdirSync(join(root, '.dsh', 'feiyu-mood'), { recursive: true });
  return root;
}

function configPath(root) {
  return join(root, '.dsh', 'pet', 'main-config.jsonc');
}

test('首次同步会新建配置并带上心情行', () => {
  const home = sandbox();
  try {
    const outcome = syncPetMood({ home, value: 82 });
    assert.equal(outcome.changed, true);
    assert.equal(outcome.created, true);
    const parsed = JSON.parse(readFileSync(configPath(home), 'utf8'));
    const prompt = parsed.pets[0].whisperPrompt;
    assert.ok(prompt.includes(MOOD_MARK));
    assert.ok(prompt.includes('82/100'));
    assert.equal(parsed.pets[0].whisperEnabled, true);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test('心情变了只改那一行，其余 JSON 保持合法', () => {
  const home = sandbox();
  try {
    syncPetMood({ home, value: 82 });
    const second = syncPetMood({ home, value: 24 });
    assert.equal(second.changed, true);
    const text = readFileSync(configPath(home), 'utf8');
    const parsed = JSON.parse(text);
    assert.ok(parsed.pets[0].whisperPrompt.includes('24/100'));
    assert.ok(!parsed.pets[0].whisperPrompt.includes('82/100'));
    // 尾巴没被吃掉：文件必须以 } 收尾且 pets 数组仍在
    assert.equal(text.trimEnd().endsWith('}'), true);
    assert.equal(parsed.pets.length, 1);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test('同一个心情重复同步不写盘', () => {
  const home = sandbox();
  try {
    syncPetMood({ home, value: 55 });
    const again = syncPetMood({ home, value: 55 });
    assert.deepEqual(again, { changed: false, reason: 'same' });
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test('带注释的 JSONC 走文本替换，不破坏其余内容', () => {
  const home = sandbox();
  try {
    const raw = `{\n  // 用户自己写的注释\n  "pets": [\n    { "id": "main", "whisperPrompt": "旧人设\\n${MOOD_MARK}中性，50/100" }\n  ]\n}\n`;
    writeFileSync(configPath(home), raw, 'utf8');
    const outcome = syncPetMood({ home, value: 91 });
    assert.equal(outcome.changed, true);
    const text = readFileSync(configPath(home), 'utf8');
    assert.ok(text.includes('// 用户自己写的注释'));
    assert.ok(text.includes('91/100'));
    assert.ok(!text.includes('50/100'));
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test('读不到心情就不动配置', () => {
  const home = sandbox();
  try {
    assert.equal(readMoodValue(home), null);
    assert.deepEqual(syncPetMood({ home }), { changed: false, reason: 'no-mood' });
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test('人物设定里不带工作状态文案', () => {
  const prompt = desiredPrompt(60);
  assert.ok(!prompt.includes('workStatusTexts'));
  assert.ok(!prompt.includes('正在写代码'));
  assert.ok(prompt.includes('二十字以内'));
});
