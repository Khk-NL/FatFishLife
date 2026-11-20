// Product capabilities only. The native registry remains authoritative for schemas and permissions.
const groups = {
  knowledge: ['查公开资料', ['lore_search', 'lore_context', 'bilibili_search', 'bilibili_video', 'bilibili_subtitles', 'web_search', 'anysearch_search', 'steam_search', 'steam_price']],
  memory: ['查授权记忆', ['recall', 'recent', 'style_terms', 'recall_all']],
  notes: ['查笔记', ['obsidian_search', 'obsidian_read', 'kb_query']],
  activity: ['查看近期活动', ['journal_recent', 'day_digest']],
  state: ['查看状态', ['operations_overview', 'mood_get', 'deepseek_balance']],
  media: ['图片与表情', ['read_image', 'sticker_search', 'meme_find', 'image_generate']],
};

export function visibleCapabilities(schemas, enabled = {}, { publicOnly = false } = {}) {
  const result = [];
  for (const [id, [label, candidates]] of Object.entries(groups)) {
    if (enabled[id] === false || (publicOnly && id !== 'knowledge')) continue;
    const tools = schemas
      .map(schema => schema.name)
      .filter(name => typeof name === 'string' && /^[\w-]+$/.test(name)
        && candidates.includes(name.split('__').at(-1)))
      .slice(0, 4);
    if (tools.length) result.push({ id, label, tools: [...new Set(tools)] });
  }
  return result;
}
