import assert from 'node:assert/strict'
import { test } from 'node:test'
import { reportVisuals } from '../wechat-bili-report.mjs'

test('B站报告把原生画面交给一次视觉请求，正文时间来自分镜', async () => {
  const bvid = 'BV1abcdefgh1'
  const frame = { mediaType: 'image/png', bytes: 3 }
  const tools = {
    get: () => true,
    async execute({ calls: [call] }) {
      const args = JSON.parse(call.arguments)
      const result = call.name === 'bilibili_video'
        ? { value: { bvid: args.bvid, pages: [{ duration: args.bvid === bvid ? 48 : 900 }] } }
        : { value: { text: 'cell 1 (r1 c1) = 00:18.50-00:34.20 frame@00:27.50' },
          content: [{ type: 'image', attachment: frame }] }
      return { results: [{ callId: call.id, result }] }
    },
  }
  const services = { tools, attachments: { async readImage(ref) {
    assert.equal(ref, frame)
    return { data: Uint8Array.of(1, 2, 3) }
  } } }
  let calls = 0
  const visuals = await reportVisuals({ get: name => services[name] }, [
    { bvid, subtitles: ['已有字幕'] },
    { bvid: 'BV1abcdefgh2', subtitles: [] },
  ], AbortSignal.timeout(2_000), { async chat(messages) {
    calls++
    assert.equal(messages[1].content.filter(row => row.type === 'image_url').length, 1)
    assert.match(messages[1].content[1].image_url.url, /^data:image\/png;base64,/)
    return JSON.stringify({ videos: [
      { bvid, points: [{ cell: 1, detail: '画面演示了插件安装选项', second: 200 },
        { cell: 99, detail: '画面不存在的步骤' }] },
      { bvid: 'BV1abcdefgh2', points: [{ cell: 1, detail: '未读取的视频' }] },
    ] })
  } })
  assert.equal(calls, 1)
  assert.deepEqual(visuals, { [bvid]: [{ second: 27, detail: '画面演示了插件安装选项' }] })
})
