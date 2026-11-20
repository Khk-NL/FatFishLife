"""Build the FatFishLife adaptation from the pinned upstream dsh-wechat archive."""

import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/clawbot-20261114'
UPSTREAM = OUTPUT / 'dsh-wechat-0.3.7.tgz'
EXPECTED = '30c51947b071923dcd12673e600d399896b69068d673e8cb07a81d3a2e6dfaf7'
BRIDGE = 'package/lib/bridge.js'
CONTEXT = 'package/lib/fatfish-shared-context.mjs'
ENTRY = 'package/lib/index.js'
API = 'package/lib/ilink/api.js'
HARNESS = 'package/lib/harness.js'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Upstream anchor changed: {old[:70]}')
    return source.replace(old, new, 1)


def adapt_bridge(source):
    source = replace_once(source, "import { renderChoices, welcomeText } from './onboarding.js'",
                          "import { renderChoices } from './onboarding.js'\n"
                          "import { createWechatPrompt } from './fatfish-shared-context.mjs'")
    source, count = re.subn(r"const CHANNEL_PROMPT = \[.*?\]\.join\('\\n'\)\n", '', source, flags=re.S)
    if count != 1:
        raise ValueError('Unexpected upstream WeChat prompt')
    source = replace_once(source, '    if (!parsed) await this.#maybeWelcome(conversationKey, userId)\n', '')
    source, count = re.subn(r'  /\*\*\n   \* Send the onboarding message.*?(?=  /\*\* Turn raw iLink)',
                            '', source, flags=re.S)
    if count != 1 or source.count('await this.#mountPreset(agentCtx, presetId)') != 2:
        raise ValueError('Unexpected upstream setup or welcome implementation')
    source = source.replace('await this.#mountPreset(agentCtx, presetId)',
                            'await this.#mountPreset(agentCtx, presetId, conversationKey)')
    source = replace_once(source, 'async #mountPreset(agentCtx, presetId)',
                          'async #mountPreset(agentCtx, presetId, conversationKey)')
    source = replace_once(source, 'this.#registerChannelPrompt(agentCtx)',
                          'this.#registerChannelPrompt(agentCtx, conversationKey)')
    source = replace_once(source, '#registerChannelPrompt(agentCtx) {',
                          '#registerChannelPrompt(agentCtx, conversationKey) {')
    source = replace_once(source, '        text: CHANNEL_PROMPT,',
                          '        text: createWechatPrompt({ owner: this.#isBoundOwner(conversationKey) }),')
    source = replace_once(source, '  /** Mark one bot', '''  #isBoundOwner(conversationKey) {
    const sender = userIdOf(conversationKey)
    const credential = this.store.credentialsFor(this.#botOf(conversationKey))
    return Boolean(sender && credential?.ownerUserId === sender)
  }

  /** Mark one bot''')
    start = source.index('    const access = checkAccess(this.config, userId, {')
    end = source.index('    const content = await this.#normalizeInbound(message)', start)
    source = source[:start] + '''    if (!this.#isBoundOwner(conversationKey)) return
    if (typeof message.context_token !== 'string' || !message.context_token.trim()) return
    this.store.rememberContextToken(userId, message.context_token, botId)
    this.store.persistTokens(botId)

''' + source[end:]
    start = source.index('    if (this.interactions.tryConsume(conversationKey, content.text))')
    end = source.index('    const parsed = parseCommand(content.text)', start)
    source = source[:start] + source[end:]
    source = replace_once(source, '    if (parsed) {\n      const context', '''    if (parsed) {
      if (!['status', 'stop'].includes(parsed.name)) {
        await this.deliver(conversationKey, '微信只用来聊天。可以用 /status 查连接、用 /stop 停当前回复。其他操作请到 DSH。')
        await this.store.saveState()
        return
      }
      const context''')
    source = replace_once(source, '      void this.#followTurn(sessionId, event)\n', '')
    source = replace_once(source, '''      if (live) {
        this.#chatOf.set(boundSessionId, conversationKey)
        return { agent: live, sessionId: boundSessionId, created: false }
      }''', '''      if (live) throw new Error('微信绑定的会话正在由 DSH 使用，请在 DSH 中继续。')''')
    source = replace_once(source, '    this.#registerChannelPrompt(agentCtx, conversationKey)\n',
                          '''    installWechatTextOnly(agentCtx, stop => {
      const pending = this.#pending.get(this.store.sessionFor(conversationKey))?.[0]
      if (pending) pending.fatfishStop = stop.reason
      this.logger.warn?.(JSON.stringify({ event: 'wechat-turn-stop', at: new Date().toISOString(), ...stop }))
    })
    this.#registerChannelPrompt(agentCtx, conversationKey)
''')
    source = replace_once(source, 'export class WechatBridge {',
                          "import { installWechatTextOnly } from './fatfish-wechat-turn-budget.mjs'\n"
                          "export { installWechatTextOnly }\n\nexport class WechatBridge {")
    source = replace_once(source, '    if (kind === \'completed\') {\n      if (text.length === 0)',
                          '''    if (pending.fatfishStop) {
      const notices = {
        step_limit: '老大，本鱼这轮卡住啦，先停，别再花额度了。',
        quota: '老大，额度不够了，本鱼先停啦。',
        provider_error: '老大，模型这次没通，本鱼先停啦。',
      }
      parts.splice(0, parts.length, notices[pending.fatfishStop])
    } else if (kind === 'completed') {
      if (text.length === 0)''')
    source = replace_once(source, "import { realpath, stat } from 'node:fs/promises'", "import { realpath, stat } from 'node:fs/promises'\nimport { loadWechatImage } from './fatfish-wechat-media.mjs'")
    start = source.index('    if (this.config.media.enabled) {', source.index('  async #normalizeInbound('))
    end = source.index('    const parts = []', start)
    source = source[:start] + '''    const imageItem = items.find(item => itemType(item) === ITEM_TYPE.IMAGE)
    let image
    if (imageItem) {
      image = await loadWechatImage({ item: imageItem, download: downloadInboundItem,
        client: this.#clientFor(botId), directory: this.store.paths.media,
        attachments: service(this.ctx, 'attachments'), logger: this.logger })
      texts.push(image ? '（老大发来一张图片）' : '（图片未能读取，请告诉老大）')
    }
    if (items.some(item => itemType(item) === ITEM_TYPE.VOICE && !String(itemPayload(item).text ?? '').trim())) {
      texts.push('（收到语音，但微信未附转写。请告诉老大可以发文字。）')
    }
    if (items.some(item => [ITEM_TYPE.FILE, ITEM_TYPE.VIDEO].includes(itemType(item)))) {
      texts.push('（这个微信入口暂时不能读取文件或视频附件。）')
    }

''' + source[end:]
    source = replace_once(source, 'await this.#normalizeInbound(message)', 'await this.#normalizeInbound(message, botId)')
    source = replace_once(source, 'async #normalizeInbound(message) {', 'async #normalizeInbound(message, botId) {')
    source = replace_once(source, '    const files = []\n    let quote', '    let quote')
    start = source.index('    const fileNote = describeFilesForPrompt(')
    end = source.index('\n  }', start)
    source = source[:start] + "    return { text: parts.join('\\n\\n').trim(), image }" + source[end:]
    source = replace_once(source, 'import { describeFilesForPrompt, downloadInboundItem,', 'import { downloadInboundItem,')
    source = replace_once(source, 'agent.followup(createTextUserMessage(content.text))',
                          'agent.followup(createTextUserMessage(content.text, content.image))')
    source = replace_once(source, "import { checkAccess } from './config.js'\n", '')
    source = replace_once(source, '    if (!userId) throw new Error(`dsh-wechat: cannot address conversation ${conversationKey}`)\n    return this.#enqueueSend',
                          '    if (!userId || !this.#isBoundOwner(conversationKey)) return 0\n    return this.#enqueueSend')
    start = source.index('    if (!contextToken) {', source.index('  async #deliverNow('))
    end = source.index('\n  /**', source.index('  async #sendWithRetry(', start))
    return source[:start] + '''    if (!contextToken) return 0
    let sent = 0
    for (const [index, chunk] of chunks.entries()) {
      try {
        await this.#clientFor(botId).sendText({
          toUserId: userId, text: chunk, contextToken, clientId: newClientId(), botId,
        })
      } catch (error) {
        this.store.noteError(`微信回复第 ${index + 1} 段未确认送达，已停止：${error?.message ?? error}`)
        break
      }
      sent += 1
      this.store.rememberOutbound({ toUserId: userId, botId, text: redactOneTimeTokens(chunk).slice(0, 200) })
      if (this.config.chunkDelayMs > 0 && index < chunks.length - 1) {
        await new Promise((resolve) => setTimeout(resolve, this.config.chunkDelayMs))
      }
    }
    if (options.pending) this.#stopTyping(options.pending)
    await this.store.saveState()
    return sent
  }
''' + source[end:]


def adapt_entry(source):
    source = replace_once(source, 'ownsInteraction: (sessionId) => bridge?.isDrivingTurn(sessionId) ?? false,',
                          'ownsInteraction: () => false,')
    source = replace_once(source, 'watchesInteraction: (sessionId) => bridge?.watchesInteraction(sessionId) ?? false,',
                          'watchesInteraction: () => false,')
    source = replace_once(source, "import { createWechatTools, registerTools } from './tools.js'\n", '')
    start = source.index('    // Tools arrive only if this profile')
    end = source.index('    const bound = store.botIds', start)
    return source[:start] + source[end:]


def adapt_harness(source):
    source = replace_once(source, 'createTextUserMessage(text) {', 'createTextUserMessage(text, image) {')
    return replace_once(source, "content: [{ type: 'text', text }],", "content: [{ type: 'text', text }, ...(image ? [{ type: 'image', attachment: image }] : [])],")


def adapt_api(source):
    source = replace_once(source, 'this.baseUrl = assertUsableBaseUrl(options.baseUrl || DEFAULT_BASE_URL)',
                          'this.baseUrl = assertOfficialBotBaseUrl(options.baseUrl || DEFAULT_BASE_URL)')
    source = replace_once(source, 'this.baseUrl = assertUsableBaseUrl(baseUrl)',
                          'this.baseUrl = assertOfficialBotBaseUrl(baseUrl)')
    return replace_once(source, '/** `ret`/`errcode` meaning', '''export function assertOfficialBotBaseUrl(value) {
  const url = new URL(String(value))
  if (url.origin !== DEFAULT_BASE_URL || !/^\\/*$/.test(url.pathname)
      || url.username || url.password || url.search || url.hash) {
    throw new TypeError('ilink: FatFishLife only connects to the official WeChat ClawBot endpoint')
  }
  return DEFAULT_BASE_URL
}

/** `ret`/`errcode` meaning''')


def main():
    if hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError('Unexpected upstream archive SHA256')
    output = io.BytesIO()
    transforms = {BRIDGE: adapt_bridge, ENTRY: adapt_entry, API: adapt_api, HARNESS: adapt_harness}
    with (tarfile.open(UPSTREAM, 'r:gz') as source,
          gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed,
          tarfile.open(fileobj=compressed, mode='w') as result):
        for member in source:
            data = source.extractfile(member).read() if member.isfile() else None
            transform = transforms.pop(member.name, None)
            if transform:
                data = transform(data.decode()).encode()
                member.size = len(data)
            result.addfile(member, io.BytesIO(data) if data is not None else None)
        if transforms:
            raise ValueError(f'Missing upstream WeChat files: {list(transforms)}')
        for filename, target in [('wechat-shared-context.mjs', CONTEXT),
                                 ('wechat-turn-budget.mjs', 'package/lib/fatfish-wechat-turn-budget.mjs'),
                                 ('fatfish-wechat-media.mjs', 'package/lib/fatfish-wechat-media.mjs'),
                                 ('fatfish-bili-learning.mjs', 'package/lib/fatfish-bili-learning.mjs')]:
            module = (ROOT / 'dsh' / filename).read_bytes()
            info = tarfile.TarInfo(target)
            info.size = len(module)
            info.mode = 0o644
            result.addfile(info, io.BytesIO(module))
    data = output.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    archive = OUTPUT / f'dsh-wechat-0.3.7-fatfish-{sha[:12]}.tgz'
    archive.write_bytes(data)
    print(archive)


if __name__ == '__main__':
    main()
