import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { compileSettings, persistSettings, DEFAULT_WINDOWS } from '../control/settings.mjs';
import { FatFishPolicy, workWindow } from '../policy.mjs';

function config() {
  return { identity:{botId:'1',ownerId:'2',adapterId:'test'}, reply:{silent:false,normalKeywords:[],groupCooldownSeconds:10,userCooldownSeconds:60,dedupSeconds:300},
    busyWindows: structuredClone(DEFAULT_WINDOWS), voice:{enabled:true,basePercent:15,stepPercent:0,maxPercent:100,cooldownSeconds:0,maxTextLength:0,manualTrigger:false,textAlongsideVoice:false,provider:'elevenlabs',providers:{elevenlabs:{modelId:'eleven_multilingual_v2'}}},
    meme:{enabled:true,basePercent:35,stepPercent:10,maxPercent:90,manualTrigger:true,maxPerMessage:1},
    workflows:{recommend:{enabled:true,times:['12:30'],commentEnabled:true,maxVideos:3},study:{enabled:true,time:'21:00'},comments:{enabled:true,ownerOnly:false},daily:{enabled:true,publishEnabled:true,time:'23:50',basePercent:20,stepPercent:20,maxPercent:100}} };
}

test('percent controls compile into existing behavior units without changing provider probability', () => {
  const result=compileSettings(config());
  assert.equal(result.behavior.voice.base,.15); assert.equal(result.behavior.voice.provider,'elevenlabs');
  assert.equal(result.behavior.meme.step,.1); assert.equal(result.behavior.life.base,.2);
  assert.equal(result.policy.groupCooldownMs,10000);
});

test('custom windows really control the message gate, including precise return time', () => {
  const value=config(); value.busyWindows=[{start:'10:15',end:'12:30',weekdays:[6]}];
  const policy=new FatFishPolicy(compileSettings(value).policy,{now:()=>Date.parse('2026-10-31T10:30:00+08:00')});
  const decision=policy.decide({post_type:'message',message_type:'group',self_id:1,user_id:3,group_id:4,message:[{type:'text',data:{text:'苹果乐'}}]},
    {groupPolicy:'open'});
  assert.equal(decision.kind,'busy'); assert.match(decision.text,/12:30再聊/);
  assert.equal(workWindow(Date.parse('2026-11-01T10:30:00+08:00'),value.busyWindows),undefined);
});

test('overnight windows use the weekday on which the interval began', () => {
  const windows=[{start:'23:00',end:'01:00',weekdays:[6]}];
  assert.equal(workWindow(Date.parse('2026-11-01T00:30:00+08:00'),windows),1);
  assert.equal(workWindow(Date.parse('2026-11-01T01:00:00+08:00'),windows),undefined);
});

test('invalid cross-field settings are rejected', () => {
  const value=config(); value.voice.basePercent=99; value.voice.maxPercent=50;
  assert.throws(()=>compileSettings(value));
  const second=config(); second.busyWindows=[{start:'10:00',end:'10:00'}];
  assert.throws(()=>compileSettings(second));
});

test('applied JSON files match the revision and changed values change that revision', async t => {
  const directory=await mkdtemp(join(tmpdir(),'fatfish-control-'));
  assert.ok(resolve(directory).startsWith(resolve(tmpdir())+sep));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const value=config(); value.dataDirectory=directory;
  const first=await persistSettings(value);
  assert.deepEqual(JSON.parse(await readFile(join(directory,'runtime-behavior.json'),'utf8')),first.behavior);
  value.voice.basePercent=25; const second=await persistSettings(value);
  assert.notEqual(first.revision,second.revision); assert.equal(second.behavior.voice.base,.25);
});
