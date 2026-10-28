/** Check installed plugin entry points without calling an LLM or writing to Bilibili. */
import assert from 'node:assert/strict';

// Copied into a disposable native profile by dsh_native_smoke.py --community.
// Internal peers must resolve through the official host, not plain Node.
export async function check({ live = false } = {}) {
  const load = name => import(name);
  const registered = new Map();
  const sections = [];
  const ctx = { tools: { register: tool => registered.set(tool.name, tool) },
    systemPrompt: { section: value => sections.push(value) }, get: () => undefined };
  const bili = await load('dsh-plugin-bilibili');
  bili.apply(ctx, { cookieEnv: 'FATFISH_TEST_UNUSED_COOKIE', requestTimeoutMs: 15000,
    searchMaxPageSize: 10, subtitleMaxChars: 12000, timeoutMs: 20000 });
  assert.deepEqual([...registered.keys()].sort(), ['bilibili_search','bilibili_subtitles','bilibili_video']);
  assert.ok(!sections.some(section => /bilibili_frames|bilibili_playurl/.test(section.text)));
  const find = await load('dsh-find-plugin');
  find.apply(ctx);
  assert.equal(registered.size, 4);
  const report = { registeredTools: [...registered.keys()], textOnly: true, paidCalls: 0, platformWrites: 0 };
  if (live) {
    try {
      const video = await registered.get('bilibili_video').execute({ bvid: 'BV1GJ411x7h7' }, { signal: new AbortController().signal });
      assert.ok(video.title && video.pages.length);
      report.videoMetadata = { ok: true, pages: video.pages.length };
    } catch (error) {
      report.videoMetadata = { ok: false, code: error.code ?? error.name };
    }
    try {
      const discovery = await registered.get('find_dsh_plugin').execute({ query: 'bilibili', limit: 3, lang: 'zh' });
      assert.ok(Array.isArray(discovery.results));
      const rendered = registered.get('find_dsh_plugin').output.render({}, discovery).map(block => block.text).join('');
      assert.ok(!/--profile web\b/.test(rendered));
      report.discovery = { ok: true, matches: discovery.results.length, degraded: /Falling back/.test(discovery.note) };
    } catch (error) {
      report.discovery = { ok: false, code: error.code ?? error.name };
    }
  }
  return report;
}
