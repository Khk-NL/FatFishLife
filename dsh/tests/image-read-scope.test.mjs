import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { FatFishPolicy } from '../policy.mjs';
import { installSocialScope } from '../runtime-adapter.mjs';

test('native image reads use real media roots and owner-only workspace access', t => {
  const root = mkdtempSync(join(tmpdir(), 'fatfish-image-read-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const media = join(root, 'media'), outside = join(root, 'private'), gallery = join(root, 'gallery');
  for (const folder of [media, outside, gallery]) {
    mkdirSync(folder);
    writeFileSync(join(folder, 'sample.png'), 'synthetic image path; native decoder not executed');
  }
  const policy = new FatFishPolicy({ botId: '1', ownerId: '2', adapterId: 'mock', silent: false },
    { accountPaused: () => false });
  let guard;
  const settings = new Map([['group:4', {recentImagePaths: [join(media, 'sample.png')]}]]);
  installSocialScope({ tools: { guard(value) { guard = value; } } }, {
    deps: { config: { mediaDir: media, extraMediaRoots: [gallery] }, fatfishPolicy: policy },
    chatForSession: session => ({group: 'group:4', member: 'private:8', owner: 'private:2'})[session],
    effectiveCwd: () => outside, sendToChat: async () => [],
    registry: {getSettings: chat => settings.get(chat)},
  });
  const read = (file_path, session = 'group') => guard({name: 'read_image', arguments: {file_path},
    agent: {session: {id: session}}});
  assert.equal(read(join(media, 'sample.png')), undefined);
  assert.ok(read(join(media, 'sample.png'), 'member'), 'same account cache must not grant cross-chat reads');
  settings.set('private:8', {recentImagePaths: [join(media, 'sample.png')]});
  assert.equal(read(join(media, 'sample.png'), 'member'), undefined, 'same actual image can be received in two chats');
  assert.equal(read(join(gallery, 'sample.png')), undefined);
  assert.ok(read(join(outside, 'sample.png')));
  assert.ok(read(join(media, '..', 'private', 'sample.png')));
  assert.ok(read(join(outside, 'sample.png'), 'member'));
  assert.equal(read(join(outside, 'sample.png'), 'owner'), undefined);
  assert.ok(read(join(media, 'sample.png'), 'unknown'));
  assert.ok(read('file://' + join(media, 'sample.png')));
  assert.ok(read('sample.png'));
  assert.ok(read(join(media, 'missing.png')));
  const alias = join(media, 'outside-link');
  symlinkSync(outside, alias, process.platform === 'win32' ? 'junction' : 'dir');
  assert.ok(read(join(alias, 'sample.png')), 'a link cannot turn private files into public media');
});
