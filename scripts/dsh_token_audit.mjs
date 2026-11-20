// Report only numeric usage and timings from recent DSH session logs.
import { createReadStream, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { createZstdDecompress } from 'node:zlib';

const root = process.argv[2] ?? 'D:/DSHData/sessions';
const folders = path => readdirSync(path, { withFileTypes: true }).filter(row => row.isDirectory());
const files = folders(root).flatMap(workspace => folders(join(root, workspace.name)).flatMap(entry => {
  const path = join(root, workspace.name, entry.name, 'session.v4.jsonl.zstd');
  try {
    const { size, mtimeMs } = statSync(path);
    const scope = workspace.name.includes('wechat') ? 'wechat'
      : workspace.name.includes('whale-work') ? 'whale-work' : 'other';
    return [{ path, scope, size, mtimeMs }];
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return [];
  }
})).sort((a, b) => b.mtimeMs - a.mtimeMs).slice(0, 12);
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const summaries = [];
for (const { path, scope, size } of files) {
  if (size > 16 * 1024 * 1024) {
    summaries.push({ scope, skipped: 'compressed-size-limit' });
    continue;
  }
  const input = createReadStream(path);
  const decoder = createZstdDecompress();
  input.on('error', error => decoder.destroy(error));
  const reader = createInterface({ input: input.pipe(decoder), crlfDelay: Infinity });
  const turns = [];
  const headers = [];
  let lines = 0, active, complete = true;
  try {
    for await (const line of reader) {
      if (++lines > 20000) { complete = false; break; }
      const row = JSON.parse(line);
      const data = row.data;
      if (row.type === 'request/header' && Array.isArray(data?.header?.tools)) {
        headers.push(data.header.tools.length);
      } else if (row.type === 'turn/start') {
        active = { steps: 0, total_tokens: 0, input_tokens: 0, cache_read_tokens: 0,
          cache_write_tokens: 0, output_tokens: 0,
          at: Number.isSafeInteger(row.time) ? new Date(row.time).toISOString() : null };
      } else if (row.type === 'step/start' && active) {
        active.steps++;
      } else if (row.type === 'assistant/message' && active && data?.usage) {
        active.total_tokens += count(data.usage.totalTokens);
        active.input_tokens += count(data.usage.inputTokens);
        active.cache_read_tokens += count(data.usage.cacheReadTokens);
        active.cache_write_tokens += count(data.usage.cacheWriteTokens);
        active.output_tokens += count(data.usage.outputTokens);
      } else if (row.type === 'turn/end' && active) {
        turns.push(active);
        active = undefined;
      }
    }
    if (active) complete = false;
  } catch { complete = false; } // Active logs can end mid-frame; discard the unfinished turn.
  finally { reader.close(); input.destroy(); decoder.destroy(); }
  summaries.push({ scope, complete, turns: turns.length, latest_schema_tools: headers.at(-1) ?? null,
    largest_schema_tools: headers.length ? Math.max(...headers) : null,
    max_steps: Math.max(0, ...turns.map(turn => turn.steps)),
    total_tokens: turns.reduce((sum, turn) => sum + turn.total_tokens, 0),
    input_tokens: turns.reduce((sum, turn) => sum + turn.input_tokens, 0),
    cache_read_tokens: turns.reduce((sum, turn) => sum + turn.cache_read_tokens, 0),
    cache_write_tokens: turns.reduce((sum, turn) => sum + turn.cache_write_tokens, 0),
    output_tokens: turns.reduce((sum, turn) => sum + turn.output_tokens, 0),
    highest_token_turn: [...turns].sort((a, b) => b.total_tokens - a.total_tokens)[0] ?? null });
}
console.log(JSON.stringify({ files: summaries, includes_automatic_titles: false, billing_reconciled: false }, null, 2));
