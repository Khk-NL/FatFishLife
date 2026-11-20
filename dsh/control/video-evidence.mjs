import { randomUUID } from 'node:crypto'

async function videoTool(ctx, name, args, signal) {
  const id = randomUUID()
  const batch = await ctx.tools.execute({
    calls: [{ type: 'tool-call', id, name, arguments: JSON.stringify(args) }],
    signal, maxParallelToolCalls: 1,
  })
  const result = batch.results.find(row => row.callId === id)?.result
  return result?.isError ? null : result
}

/** Use the installed Bilibili and video-storyboard tools and their native attachment store. */
export async function recommendationEvidence(ctx, bvid, { signal: parent, allowAnonymous = false } = {}) {
  if (!/^BV[\da-z]{10}$/i.test(bvid)) return null
  const timeout = (ms) => parent ? AbortSignal.any([parent, AbortSignal.timeout(ms)]) : AbortSignal.timeout(ms)
  const info = await videoTool(ctx, 'bilibili_video', { bvid }, timeout(15_000))
  const detail = info?.value
  // The storyboard plugin may fetch the full first part at low resolution.
  // Check its actual duration before any media request.
  const duration = detail?.pages?.[0]?.duration ?? detail?.duration
  if (detail?.bvid !== bvid || !Number.isFinite(duration) || duration <= 0 || duration > 300) return null
  const signal = timeout(90_000)
  const storyboard = await videoTool(ctx, 'video_storyboard', {
    input: `https://www.bilibili.com/video/${bvid}`, cells: 6, sheets: 1,
    detail: 'low', transcript: 'off', scanHeight: 360, ...(allowAnonymous ? { allowAnonymous: true } : {}),
  }, signal)
  const frame = storyboard?.content?.find(block => block.type === 'image')?.attachment
  if (frame?.mediaType !== 'image/png' || !(frame.bytes > 0 && frame.bytes <= 4 * 1024 * 1024)) return null
  const { data } = await ctx.attachments.readImage(frame, signal)
  if (data.byteLength !== frame.bytes) return null
  const manifest = String(storyboard.value?.text ?? '').split('\n')
    .filter(line => /^cell \d+\b/i.test(line)).slice(0, 6).map(line => line.slice(0, 200)).join('\n')
  if (!manifest) return null
  return {
    title: String(detail.title ?? '').slice(0, 100),
    description: String(detail.description ?? '').slice(0, 380),
    manifest,
    imageUrl: 'data:image/png;base64,' + Buffer.from(data).toString('base64'),
  }
}
