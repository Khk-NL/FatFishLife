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
STORE = 'package/lib/store.js'
COMMANDS = 'package/lib/commands.js'
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
                          "import { createWechatPrompt, queryDiaryStatus } from './fatfish-shared-context.mjs'")
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
    source = replace_once(source, '        text: CHANNEL_PROMPT,', '''        interpolate: false,
        text: createWechatPrompt({
          owner: this.#isBoundOwner(conversationKey),
          currentText: () => this.#pending.get(this.store.sessionFor(conversationKey))?.[0]?.fatfishQuery ?? '',
        }),''')
    source = replace_once(source, '      queue.push(pending)', '''      pending.fatfishQuery = String(content.text ?? '').slice(0, 600)
      pending.fatfishPrivate = Boolean(botId && !message.group_id)
      const parts = Array.isArray(message.item_list) ? message.item_list : []
      const direct = parts.filter(item => itemType(item) === ITEM_TYPE.TEXT && !item.ref_msg)
      const permissions = service(this.ctx, 'permissionPresets')
      const isNative = this.#isOwnerAgent(conversationKey) && permissions
        && !parts.some(item => item.ref_msg) && direct.length === 1
      if (isNative && !['workspace-write', 'read-only'].includes(permissions.current(agent.session))) {
        permissions.set(agent.session, 'workspace-write')
      }
      pending.fatfishNative = Boolean(isNative && ['workspace-write', 'read-only'].includes(permissions.current(agent.session)))
      if (pending.fatfishNative) pending.fatfishDirect = itemPayload(direct[0]).text
      if (pending.fatfishPrivate && parts.length === 1 && itemType(parts[0]) === ITEM_TYPE.TEXT && !parts[0].ref_msg) {
        pending.fatfishDirect = itemPayload(parts[0]).text
        pending.fatfishMemory = ownerMemory(pending.fatfishDirect)
        pending.fatfishApp = ownerDesktopApp(pending.fatfishDirect)
        pending.fatfishWorkflow = ownerWorkflow(pending.fatfishDirect)
      }
      const sourceId = message.message_id ?? message.messageId
      if (typeof sourceId === 'string' || Number.isSafeInteger(sourceId)) pending.fatfishSource = String(sourceId).slice(0, 250)
      queue.push(pending)
      if (this.#isBoundOwner(conversationKey)) {
        void Promise.resolve(stageWechatNote(this.ctx, conversationKey, pending))
          .catch(() => this.logger.warn?.('WeChat note staging failed'))
      }''')
    source = replace_once(source, '  /** Mark one bot', '''  #isBoundOwner(conversationKey) {
    const sender = userIdOf(conversationKey)
    const credential = this.store.credentialsFor(this.#botOf(conversationKey))
    return Boolean(sender && credential?.ownerUserId === sender)
  }

  #isOwnerAgent(conversationKey) {
    return this.#isBoundOwner(conversationKey) && pinnedWechatOwner(
      path.join(this.store.paths.root, 'owner-agent.json'),
      this.#botOf(conversationKey), userIdOf(conversationKey), readFileSync)
  }

  isDrivingOwnerTurn(sessionId) {
    const pending = this.#pending.get(this.#rootSessionIdOf(sessionId))?.[0]
    return Boolean(pending?.fatfishNative && this.#isOwnerAgent(pending.conversationKey)
      && this.isDrivingTurn(sessionId))
  }

  /** Mark one bot''')
    start = source.index('    const access = checkAccess(this.config, userId, {')
    end = source.index('    const content = await this.#normalizeInbound(message)', start)
    source = source[:start] + '''    if (!this.#isBoundOwner(conversationKey)) return
    if (typeof message.context_token !== 'string' || !message.context_token.trim()) return
    this.store.rememberContextToken(userId, message.context_token, botId)
    this.store.persistTokens(botId)

''' + source[end:]
    source = replace_once(source, '    if (content.text.length === 0) {', '''    if (protectedWechatContent(content.text)) {
      await this.deliver(conversationKey, '这条消息像是含有凭据，本鱼没有交给模型')
      return
    }
    if (content.text.length === 0) {''')
    start = source.index('    if (this.interactions.tryConsume(conversationKey, content.text))')
    end = source.index('    const parsed = parseCommand(content.text)', start)
    source = source[:start] + source[end:]
    source = replace_once(source, '    if (parsed) {\n      const context', '''    if (parsed) {
      const startsNewSession = parsed.name === 'session' && /^new$/i.test(String(parsed.args ?? '').trim())
      const help = '/status 查连接 · /permission 查权限 · /model 查模型 · /quota 查额度 · /stop 停当前回复 · /new 开新对话'
      const permission = parsed.name === 'permission' && this.#isOwnerAgent(conversationKey)
        && /^(?:|read-only|workspace-write)$/u.test(String(parsed.args ?? '').trim())
      if (parsed.name === 'help' || (!['status', 'stop', 'new'].includes(parsed.name) && !startsNewSession && !permission)) {
        await this.deliver(conversationKey, help)
        await this.store.saveState()
        return
      }
      const context''')
    source = replace_once(source, '      void this.#followTurn(sessionId, event)\n', '')
    source = replace_once(source, '''      if (live) {
        this.#chatOf.set(boundSessionId, conversationKey)
        return { agent: live, sessionId: boundSessionId, created: false }
      }
      try {''', '''      // An agent opened by Desktop does not carry this channel's capability guards.
      // Leave its session intact and bind a new scoped session only after creation succeeds.
      if (!live) {
      try {''')
    source = replace_once(source, '''        this.logger.warn?.(`failed to resume session ${boundSessionId}, starting a new one: ${error?.message ?? error}`)
        await this.store.setSession(conversationKey, null)''',
                          "        this.logger.warn?.('WeChat session resume failed; creating a fresh scoped session')")
    resume_start = source.index('      if (!live) {\n      try {') + len('      if (!live) {\n')
    resume_end = source.index('\n    }\n\n    const sessionId = newSessionId()', resume_start)
    resume = '\n'.join('  ' + line for line in source[resume_start:resume_end].split('\n'))
    source = source[:resume_start] + resume + '\n      }' + source[resume_end:]
    source = replace_once(source,
                          '          `❌ 无法为这个微信会话打开 DSH 会话：${detail}\\n请检查工作区路径是否存在（/workspace），或发送 /new 重试。`,',
                          "          '老大，本鱼没能打开新的微信会话，这条消息没交给模型。',")
    source = replace_once(source, '    const parsed = parseCommand(content.text)', """    const rawItem = message.item_list[0]
    const query = message.item_list.length === 1 && itemType(rawItem) === ITEM_TYPE.TEXT && !rawItem.ref_msg
      ? parseWechatServiceQuery(String(itemPayload(rawItem).text ?? '')) : undefined
    if (query) {
      let answer
      if (query === 'model') {
        answer = this.#lastReplyModel(conversationKey)
      } else if (query === 'use-deepseek') {
        delete this.store.state.modelPreferences[conversationKey]
        await this.store.saveState()
        answer = '本鱼切回 DeepSeek 了'
      } else if (query === 'use-codex') {
        const report = await readProviderQuota(this.ctx, 'codex')
        if (quotaAllowsCodex(report, readRuntimeOptions())) {
          this.store.state.modelPreferences[conversationKey] = 'codex'
          await this.store.saveState()
          answer = '本鱼切到 GPT-6.2 Sol 中档了'
        } else {
          delete this.store.state.modelPreferences[conversationKey]
          await this.store.saveState()
          answer = 'Codex 插件或额度暂时不可用，本鱼会先用 DeepSeek'
        }
      } else {
        answer = await formatWechatQuota(this.ctx, query)
      }
      await this.deliver(conversationKey, answer)
      return
    }
    const diary = message.item_list.length === 1 && itemType(rawItem) === ITEM_TYPE.TEXT && !rawItem.ref_msg
      ? queryDiaryStatus(String(itemPayload(rawItem).text ?? '')) : undefined
    if (diary) {
      await this.deliver(conversationKey, diary)
      return
    }
    const directText = message.item_list.length === 1 && itemType(rawItem) === ITEM_TYPE.TEXT && !rawItem.ref_msg
      ? String(itemPayload(rawItem).text ?? '') : ''
    if (directText && this.#isOwnerAgent(conversationKey)) {
      if (this.interactions?.tryConsume(conversationKey, directText)) return
      const source = message.message_id ?? message.messageId
      if ((Number.isSafeInteger(source) || typeof source === 'string' && source) && ownerDesktopTextFile(directText)) {
        await this.deliver(conversationKey, await createOwnerDesktopText(this.ctx, conversationKey, String(source)))
        return
      }
    }
    const parsed = directText ? parseCommand(directText) : undefined""")
    source = replace_once(source, '  /** Mark one bot', '''  #lastReplyModel(conversationKey) {
    const source = this.store.state.lastReplyModels[conversationKey]
    const isModelId = value => typeof value === 'string' && /^[a-z0-9._:/-]{1,120}$/i.test(value)
    if (!isModelId(source?.provider) || !isModelId(source?.model)) {
      return '本鱼还没记到这个会话的模型回复'
    }
    const names = new Map([['workbuddy', 'WorkBuddy'], ['workbuddy-global', 'WorkBuddy 国际版'],
      ['openai-codex', 'Codex 订阅'], ['deepseek-official', 'DeepSeek 官方 API']])
    return `最近一次回复：${names.get(source.provider) ?? source.provider} · ${source.model}`
  }

  /** Mark one bot''')
    source = replace_once(source, 'if (text.length > 0) pending.durableText = text', '''if (text.length > 0) {
          pending.durableText = text
          const source = event.data?.message?.source
          pending.fatfishReplyModel = pending.turn !== null && event.data?.turn === pending.turn
            && source?.kind === 'model' && typeof source.provider === 'string' && typeof source.model === 'string'
            ? { provider: source.provider, model: source.model } : undefined
        }''')
    source = replace_once(source, '    this.#registerChannelPrompt(agentCtx, conversationKey)\n',
                          '''    if (this.#isBoundOwner(conversationKey)) installCodexRouting(agentCtx, {
      prefersCodex: () => this.store.state.modelPreferences[conversationKey] === 'codex',
      onCodexUnavailable: () => { delete this.store.state.modelPreferences[conversationKey] },
    })
    const current = () => this.#pending.get(this.store.sessionFor(conversationKey))?.[0]
    const capabilities = installWechatCapabilities(agentCtx, this.ctx, {
      conversation: conversationKey, owner: () => this.#isBoundOwner(conversationKey), current,
    })
    const onStop = stop => {
      const pending = current()
      if (pending && pending.fatfishStop?.reason === stop.reason) return
      if (pending) pending.fatfishStop = stop
      this.logger.warn?.(JSON.stringify({ event: 'wechat-turn-stop', at: new Date().toISOString(), ...stop }))
    }
    if (this.#isOwnerAgent(conversationKey)) installWechatOwnerAgent(agentCtx, {
      owner: () => this.#isOwnerAgent(conversationKey), current, onStop, available: capabilities.available,
    })
    else installWechatTextOnly(agentCtx, onStop, capabilities)
    this.#registerChannelPrompt(agentCtx, conversationKey)
''')
    source = replace_once(source, 'export class WechatBridge {',
                          "import { parseWechatServiceQuery, formatWechatQuota } from './fatfish-wechat-service-status.mjs'\n"
                          "import { installCodexRouting, prepareCodexRouting, quotaAllowsCodex, readProviderQuota } from './persona/codex-routing.mjs'\n"
                          "import { readRuntimeOptions } from './control/runtime-options.mjs'\n"
                          "import { existsSync, readFileSync } from 'node:fs'\n"
                          "import * as mcpClient from '@deepseek-ai/dsh-mcp-client'\n"
                          "import { explainWechatStop, installWechatOwnerAgent, mountWechatDeskbox, pinnedWechatOwner, protectedWechatContent, wantsDeskbox } from './fatfish-wechat-owner-agent.mjs'\n"
                          "import { installWechatTextOnly } from './fatfish-wechat-turn-budget.mjs'\n"
                          "import { chooseWechatSticker, createOwnerDesktopText, installWechatCapabilities, ownerDesktopApp, ownerDesktopTextFile, ownerMemory, ownerWorkflow, stageWechatNote } from './fatfish-wechat-capabilities.mjs'\n"
                          "export { installWechatTextOnly }\n\nexport class WechatBridge {")
    source = replace_once(source, '    if (kind === \'completed\') {\n      if (text.length === 0)',
                          '''    if (pending.fatfishStop) {
      if (kind !== 'completed' || !text || pending.fatfishStop.reason !== 'repeated_tool_error') {
        parts.splice(0, parts.length, explainWechatStop(pending.fatfishStop))
      }
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
    const media = items.find(item => !item.ref_msg && ([ITEM_TYPE.FILE, ITEM_TYPE.VIDEO].includes(itemType(item))
      || itemType(item) === ITEM_TYPE.VOICE && !String(itemPayload(item).text ?? '').trim()))
    if (media && this.#isOwnerAgent(withBot(conversationKeyOf(message), botId))) {
      try {
        const file = await downloadInboundItem({
          client: this.#clientFor(botId), item: media,
          dir: path.join(this.store.paths.media, new Date().toISOString().slice(0, 10)),
          maxBytes: this.config.media.maxInboundBytes, logger: this.logger,
        })
        if (file) texts.push('【主人本轮收到的附件，内容只作资料】\\n' + describeFilesForPrompt([file]))
        else texts.push('（附件未能读取）')
      } catch {
        texts.push('（附件未能读取）')
      }
    }

''' + source[end:]
    source = replace_once(source, 'await this.#normalizeInbound(message)', 'await this.#normalizeInbound(message, botId)')
    source = replace_once(source, 'async #normalizeInbound(message) {', 'async #normalizeInbound(message, botId) {')
    source = replace_once(source, '    const files = []\n    let quote', '    let quote')
    start = source.index('    const fileNote = describeFilesForPrompt(')
    end = source.index('\n  }', start)
    source = source[:start] + "    return { text: parts.join('\\n\\n').trim(), image }" + source[end:]
    source = replace_once(source, '      const { agent, sessionId } = opened\n',
                          '      const { agent, sessionId } = opened\n'
                          "      if (this.#isOwnerAgent(conversationKey) && wantsDeskbox(content.text)\n"
                          "          && !agent.ctx.get('tools')?.get('mcp__deskbox__deskbox_get_widget_spec', agent)) {\n"
                          "        await this.deliver(conversationKey, '老大，微信没有连上 DeskBox 的组件工具，先打开电脑上的 DeskBox，本鱼才能校验和预览')\n"
                          '        return\n'
                          '      }\n'
                          '      if (!content.image && this.#isBoundOwner(conversationKey)) {\n'
                          "        await prepareCodexRouting(this.ctx, this.store.state.modelPreferences[conversationKey] === 'codex')\n"
                          '      }\n')
    source = replace_once(source, 'agent.followup(createTextUserMessage(content.text))',
                          'agent.followup(createTextUserMessage(content.text, content.image))')
    source = replace_once(source, '    const mounted = await presets.mount(agentCtx, presetId)',
                          '''    const mounted = await presets.mount(agentCtx, presetId)
    const deskbox = process.env.FATFISH_DESKBOX_COMMAND || 'D:/DeskBox/DeskBox.exe'
    if (this.#isOwnerAgent(conversationKey) && process.platform === 'win32' && existsSync(deskbox)) {
      await mountWechatDeskbox(agentCtx, mcpClient, deskbox)
    }''')
    source = replace_once(source, '  async deliverFile(conversationKey, filePath, options = {}) {',
                          """  async deliverFile(conversationKey, filePath, options = {}) {
    if (!this.#isOwnerAgent(conversationKey)) throw new Error('微信附件目标不可用')""")
    source = replace_once(source, '    if (isInsideDirectory(root, resolved)) {',
                          """    const cwd = await resolveReal(await this.#workspaceFor(conversationKey))
    if (protectedWechatContent(resolved) || !isInsideDirectory(cwd, resolved)
        || isInsideDirectory(root, resolved) && cwd !== path.join(root, 'workspace')) {""")
    source = replace_once(source, "import { checkAccess } from './config.js'\n", '')
    source = replace_once(source, '    if (!userId) throw new Error(`dsh-wechat: cannot address conversation ${conversationKey}`)\n    return this.#enqueueSend',
                          '''    if (!userId || !this.#isBoundOwner(conversationKey)) return 0
    if (protectedWechatContent(text)) text = '这段内容涉及凭据，本鱼留在本机了'
    return this.#enqueueSend''')
    source = replace_once(source, "    await this.deliver(pending.conversationKey, parts.join('\\n\\n'), { pending })",
                          """    await this.deliver(pending.conversationKey, parts.join('\\n\\n'), { pending,
      fatfishReplyModel: (kind === 'completed' || kind === 'max-tokens') && !pending.fatfishStop && text
        ? pending.fatfishReplyModel : undefined,
      fatfishSticker: kind === 'completed' && !pending.fatfishStop ? text : '' })""")
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
    if (sent > 0 && sent === chunks.length && options.fatfishReplyModel && this.#isBoundOwner(conversationKey)) {
      this.store.state.lastReplyModels[conversationKey] = options.fatfishReplyModel
    }
    await this.store.saveState()
    if (sent > 0 && sent === chunks.length && options.pending && options.fatfishSticker) {
      try {
        const sticker = await chooseWechatSticker(this.ctx, conversationKey, options.pending, options.fatfishSticker)
        if (sticker && this.#isBoundOwner(conversationKey) && this.store.contextTokenFor(userId, botId) === contextToken
            && mediaTypeFor(sticker) === 1) {
          const client = this.#clientFor(botId)
          const result = await uploadLocalFile({ client, filePath: sticker, toUserId: userId,
            maxBytes: 4 * 1024 * 1024, mediaType: 1 })
          if (!this.#isBoundOwner(conversationKey) || this.store.contextTokenFor(userId, botId) !== contextToken) return sent
          await client.sendMessage({ toUserId: userId, contextToken, clientId: newClientId(), item: result.item })
          this.logger.info?.(JSON.stringify({ event: 'wechat-sticker-sent' }))
        }
      } catch {
        this.logger.warn?.(JSON.stringify({ event: 'wechat-sticker-unconfirmed' }))
      }
    }
    return sent
  }
''' + source[end:]


def adapt_entry(source):
    source = replace_once(source, "import { createWechatTools, registerTools } from './tools.js'\n",
                          "import { createWechatTools, registerTools } from './tools.js'\n"
                          "import { startWechatMemoryClock } from './fatfish-wechat-capabilities.mjs'\n")
    source = replace_once(source, "    const bound = store.botIds",
                          "    cleanups.push(startWechatMemoryClock(ctx, logger))\n    const bound = store.botIds")
    source = replace_once(source, 'ownsInteraction: (sessionId) => bridge?.isDrivingTurn(sessionId) ?? false,',
                          'ownsInteraction: (sessionId) => bridge?.isDrivingOwnerTurn(sessionId) ?? false,')
    source = replace_once(source, 'watchesInteraction: (sessionId) => bridge?.watchesInteraction(sessionId) ?? false,',
                          'watchesInteraction: () => false,')
    return source


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


def adapt_store(source):
    source = replace_once(source, '    sessions: {},', '    sessions: {},\n    lastReplyModels: {},\n    modelPreferences: {},')
    return replace_once(source, "['sessions', 'follow', 'contextTokens', 'welcomed', 'pendingSwitch']",
                        "['sessions', 'follow', 'contextTokens', 'welcomed', 'pendingSwitch', 'lastReplyModels', 'modelPreferences']")


def adapt_commands(source):
    return replace_once(source, "          ['模型', info.model ?? '（跟随 DSH 默认）'],\n", "")


def main():
    if hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError('Unexpected upstream archive SHA256')
    output = io.BytesIO()
    transforms = {BRIDGE: adapt_bridge, STORE: adapt_store, COMMANDS: adapt_commands,
                  ENTRY: adapt_entry, API: adapt_api, HARNESS: adapt_harness}
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
                                 ('persona/model.mjs', 'package/lib/persona/model.mjs'),
                                 ('persona/codex-routing.mjs', 'package/lib/persona/codex-routing.mjs'),
                                 ('wechat-service-status.mjs', 'package/lib/fatfish-wechat-service-status.mjs'),
                                 ('wechat-turn-budget.mjs', 'package/lib/fatfish-wechat-turn-budget.mjs'),
                                 ('wechat-capabilities.mjs', 'package/lib/fatfish-wechat-capabilities.mjs'),
                                 ('wechat-owner-agent.mjs', 'package/lib/fatfish-wechat-owner-agent.mjs'),
                                 ('wechat-bili-report.mjs', 'package/lib/fatfish-wechat-bili-report.mjs'),
                                 ('control/video-evidence.mjs', 'package/lib/control/video-evidence.mjs'),
                                 ('control/whale-voice.mjs', 'package/lib/control/whale-voice.mjs'),
                                 ('control/runtime-options.mjs', 'package/lib/control/runtime-options.mjs'),
                                 ('control/llm.mjs', 'package/lib/control/llm.mjs'),
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
