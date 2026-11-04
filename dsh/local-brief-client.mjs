/** Peak-hour local replies share one model request; cold loading never blocks QQ. */
export function createLocalBriefClient({
  baseUrl = 'http://127.0.0.1:11434',
  model = 'qwen2.5:1.5b',
  fetchImpl = (...args) => globalThis.fetch(...args),
  now = Date.now,
  loadTimeoutMs = 45_000,
  replyTimeoutMs = 3500,
} = {}) {
  const base = baseUrl.replace(/\/+$/, '');
  let readyUntil = 0;
  let pending = null;

  async function post(path, body, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(base + path, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({ model, stream: false, keep_alive: '5m', ...body }),
      });
      if (!response.ok) return null;
      const data = await response.json();
      return data?.error ? null : data;
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    async chat(messages, options) {
      // Keep concurrent groups from queueing behind a cold load or another reply.
      if (pending) return null;
      if (now() >= readyUntil) {
        pending = post('/api/generate', { prompt: '', options: { num_ctx: 1024 } }, loadTimeoutMs)
          .then(data => { readyUntil = data ? now() + 300_000 : 0; })
          .finally(() => { pending = null; });
        return null;
      }
      pending = post('/api/chat', { messages, options }, replyTimeoutMs);
      try {
        const data = await pending;
        readyUntil = data ? now() + 300_000 : 0;
        return data;
      } finally {
        pending = null;
      }
    },
  };
}
