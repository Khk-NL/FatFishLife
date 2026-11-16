import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises'
import { join } from 'node:path'

export async function loadWechatImage({ item, download, client, directory, attachments, logger }) {
  if (!attachments?.saveImage) return null
  let temporary
  try {
    await mkdir(directory, { recursive: true })
    temporary = await mkdtemp(join(directory, 'inbound-'))
    const file = await download({ item, client, dir: temporary, maxBytes: 4 * 1024 * 1024, logger })
    if (!file || file.name.endsWith('.enc')) return null
    const data = await readFile(file.path)
    if (data.length < 12 || data.length > 4 * 1024 * 1024) return null
    const png = data.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))
    const jpeg = data.subarray(0, 3).equals(Buffer.from('ffd8ff', 'hex'))
    if (!png && !jpeg) return null
    return await attachments.saveImage({ data, mediaType: png ? 'image/png' : 'image/jpeg', name: png ? 'wechat.png' : 'wechat.jpg' })
  } catch {
    logger?.warn?.('WeChat inbound image could not be attached')
    return null
  } finally {
    if (temporary) await rm(temporary, { recursive: true, force: true }).catch(() => logger?.warn?.('Could not clean WeChat inbound image'))
  }
}
