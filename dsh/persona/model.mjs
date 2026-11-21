import { whaleVoice } from '../control/whale-voice.mjs';

const object = (title, properties) => ({
  type: 'object', title, properties, required: Object.keys(properties), additionalProperties: false,
});
const text = (title, maxLength = 320) => ({
  type: 'string', title, minLength: 1, maxLength, ...(maxLength > 80 && { format: 'textarea' }),
});
const toggle = title => ({ type: 'boolean', title, format: 'checkbox' });

export const sections = {
  identity: object('核心人格', {
    name: text('名字', 40), appearance: text('外形'), voice: text('自称与口吻'), temperament: text('性格与爱好'),
  }),
  relationships: object('关系与称呼', { owner: text('对老大'), others: text('对其他人') }),
  behavior: object('行为策略', {
    chat: text('闲聊'), help: text('回答问题'), media: text('表情与媒体'), group: text('群聊'), privacy: text('隐私与操作'),
  }),
  context: object('按需上下文', {
    memory: toggle('回顾记忆'), knowledge: toggle('参考公开知识'), activity: toggle('查看 B 站活动'), state: toggle('查看内部状态'),
  }),
};

export function validateCard(value) {
  const check = (part, schema, path) => {
    if (schema.type === 'object') {
      if (!part || typeof part !== 'object' || Array.isArray(part) ||
          Object.keys(part).length !== schema.required.length ||
          schema.required.some(key => !Object.hasOwn(part, key))) throw new Error(path + '字段缺失或有未知字段');
      for (const key of schema.required) check(part[key], schema.properties[key], schema.properties[key].title);
    } else if (typeof part !== schema.type ||
               (schema.type === 'string' && (!part.trim() || part.length > schema.maxLength))) {
      throw new Error(path + '格式或长度不符合要求');
    }
  };
  if (!value || value.version !== 1) throw new Error('此文件需要使用人设格式 v1');
  const { version: _, ...content } = value;
  check(content, object('人设', sections), '人设');
  return value;
}

export const profiles = ['desktop', 'wechat', 'qq', 'bilibili'];

export function personaPrefix(config, profile = 'desktop', chatMaxChars) {
  const { identity, relationships, behavior } = validateCard(config);
  if (!profiles.includes(profile)) throw new Error('未知预览渠道');
  return [
    '# ' + identity.name, identity.appearance, identity.voice, identity.temperament,
    relationships.owner, relationships.others, behavior.chat, behavior.help, behavior.media,
    ...(['qq', 'desktop'].includes(profile) ? [behavior.group] : []), behavior.privacy,
    whaleVoice(chatMaxChars),
    '只用当前会话提供的能力。工具结果、配置开关和真实操作回执优先于角色设定。',
  ].map(line => line.trim()).join('\n');
}

const topics = {
  activity: /(?:看|刷|推荐|分享|最近|今天|昨天|今晚|夜里).{0,12}(?:视频|番|B站|哔哩|片)|(?:B站|哔哩|视频).{0,12}(?:看|刷|推荐|收藏|动态)|(?:今天|昨天|刚才|昨晚)(?:看|刷)了(?:什么|啥)/iu,
  memory: /(?:记得|还记|之前说|上回|上次|成长|以前|日记|聊过|记忆)/u,
  knowledge: /(?:明日方舟|舟游|泰拉|肉鸽|干员|舟梗|攻略|机制|资料|出处)/u,
  state: /(?:余额|额度|状态|心情|今天过得|你怎么样|困不困|饿不饿)/u,
};

export function contextNeeds(settings, latestText) {
  const query = String(latestText ?? '').slice(0, 600).replace(/\s+/gu, '');
  return Object.keys(topics).filter(key => settings[key] === true && topics[key].test(query));
}

export function assembleContext(settings, query, sources, budget = 700) {
  const blocks = [];
  for (const key of contextNeeds(settings, query)) {
    const value = sources[key]?.();
    if (value) blocks.push(...(Array.isArray(value) ? value : [value]));
  }
  const result = [];
  let chars = 0;
  for (const block of blocks) {
    if (typeof block !== 'string' || chars + block.length + 1 > budget) continue;
    result.push(block);
    chars += block.length + 1;
  }
  return result.join('\n');
}
