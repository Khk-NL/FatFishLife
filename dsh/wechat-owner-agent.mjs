const internalTools = /(?:^mcp__fatfish__.*_internal$|^(?:compress|decompress|acp_status|search_context)$)/u
const deskboxPrefix = 'mcp__deskbox__deskbox_'
const deskboxTools = new Set(['get_widget_spec', 'get_capability_spec', 'validate_manifest', 'upsert_widget', 'capture_widget_preview'])
const directOutput = /(?:发|传|交|给).{0,10}(?:我|微信)|发回|传回/u
const credential = /(?:^|[\\/\s"'=])(?:\.env(?:[.\w-]*)?|\.credentials\.ya?ml|credentials\.json|owner-agent\.json|wechat-capability\.key|id_(?:rsa|ed25519)|\.npmrc|\.netrc)(?=[\\/\s"'=]|$)|\b(?:sk-[a-z0-9_-]{16,}|ghp_[a-z0-9]{20,}|bearer\s+[a-z0-9._-]{12,})\b|(?:\b(?:api[_ -]?key|password|client[_ -]?secret)|密码|密钥)\s*[:=：]\s*["']?[a-z0-9._+\/-]{6,}/iu

export const protectedWechatContent = value => {
  const text = String(value ?? '')
  return credential.test(text) || /(?:^|[\\/])(?:\.lark-cli|private[\\/]+feishu-cli)(?:[\\/]|$)|\b(?:LARKSUITE_CLI_CONFIG_DIR|app-secret-stdin)\b/iu.test(text)
}
export const wantsDeskbox = text => /desk\s*box|桌面.{0,8}小组件|桌面格子/iu.test(String(text ?? ''))

export async function mountWechatDeskbox(ctx, client, command) {
  await client.apply(ctx, client.Config({ serverName: 'deskbox', transport: 'stdio', command, args: ['--mcp'],
    failOnStartupError: false, startupTimeoutMs: 12000, toolCallTimeoutMs: 20000, reconnect: { enabled: false } }))
}

export function explainWechatStop({ reason, code, tool, steps }) {
  const subject = tool?.startsWith(deskboxPrefix) ? 'DeskBox 的' + ({
    validate_manifest: '组件校验', upsert_widget: '草稿暂存', capture_widget_preview: '预览渲染',
  }[tool.slice(deskboxPrefix.length)] ?? '工具调用') : tool ? `工具 ${tool}` : '这轮任务'
  if (reason === 'quota') return `老大，本鱼在第 ${steps} 步遇到模型额度不足${code ? `（${code}）` : ''}，额度恢复后再接着做`
  if (reason === 'provider_error') return `老大，第 ${steps} 步的模型请求失败${code ? `（${code}）` : ''}，先检查 DSH 的模型连接，本鱼把这轮停住了`
  if (reason === 'step_limit') return `老大，本鱼用完这个会话的 ${steps} 步，操作结果还没确认，下一轮从上一步接着做`
  const advice = {
    permission: '这一步被权限拦住了，先到 DSH 核对审批，DeskBox 草稿可以在桌面工坊确认',
    timeout: '连续超时了，先看看对应应用是否还在线，再从这一步继续',
    unavailable: '这个会话找不到它，先检查 DSH 里对应工具的连接状态',
  }
  return `老大，${subject}${advice[code] ?? '连续执行失败了，具体结果还没确认，从这一步查起'}，本鱼把后面的操作停了`
}

export function pinnedWechatOwner(file, botId, ownerId, readFile) {
  try {
    const identity = JSON.parse(readFile(file, 'utf8'))
    return Boolean(botId && ownerId && identity.botId === botId && identity.ownerId === ownerId)
  } catch (error) {
    if (error instanceof SyntaxError || ['ENOENT', 'EACCES', 'EPERM'].includes(error.code)) return false
    throw error
  }
}

export function installWechatOwnerAgent(ctx, { owner, current, onStop, available }) {
  const tools = ctx.get('tools')
  const native = tools.selectExecutor()
  let steps = 0
  let lastCall, lastFailure, consecutiveFailures, reportOnly, reporting
  const reset = () => {
    steps = 0
    lastCall = lastFailure = undefined
    consecutiveFailures = 0
    reportOnly = reporting = false
  }
  reset()
  const stop = (reason, code) => ({ reason, code, steps, tool: lastFailure?.tool })
  ctx.get('systemPrompt')?.section?.({ name: 'fatfish-wechat:turn-result', order: 10105, interpolate: false,
    text: () => reportOnly
      ? `本轮的工具操作已停止。工具 ${lastFailure.tool} 连续失败，类别 ${lastFailure.code}。用鲸鲸自己的话说清实际完成到哪一步、卡在哪里、老大怎样继续。根据已有结果作答，未知就说尚未确认。`
      : '' })
  const allows = name => {
    const pending = current()
    const nativeWechat = ['wechat_chat_info', 'wechat_send_file'].includes(name)
    return Boolean(!reportOnly && owner() && pending?.fatfishNative && !pending.abandoned && !internalTools.test(name)
      && (!name.startsWith(deskboxPrefix) || wantsDeskbox(pending.fatfishDirect) && deskboxTools.has(name.slice(deskboxPrefix.length)))
      && (!name.startsWith('wechat_') || nativeWechat || available(name))
      && (name !== 'wechat_send_file' || directOutput.test(pending.fatfishDirect ?? ''))
      && name !== 'wechat_send_text')
  }
  tools.guard(call => {
    const args = call.args ?? call.arguments ?? {}
    if (!allows(call.name) || call.agent?.session?.id !== current()?.sessionId || protectedWechatContent(JSON.stringify(args))) {
      return '当前回合没有授权此项操作'
    }
    if (call.name === deskboxPrefix + 'upsert_widget' && (args.commit === true || /"commit"\s*:\s*true/u.test(JSON.stringify(args)))) {
      return '微信可以暂存和预览，提交请在 DeskBox 桌面确认'
    }
  })
  tools.setExecutor({
    describe(definitions) { return native.describe(definitions.filter(item => allows(item.name))) },
    execute(input) { return native.execute({ ...input, maxParallelToolCalls: 1 }) },
  })
  ctx.on('session/event', (_session, event) => {
    if (event.type === 'turn/start') reset()
    if (event.type === 'tool/call') lastCall = event.data
    if (event.type !== 'tool/result' || !lastCall || event.data?.message?.toolCallId !== lastCall.callId) return
    const message = event.data.message
    if (!message.isError && !event.data.error) {
      consecutiveFailures = 0
      lastFailure = undefined
      return
    }
    const tool = /^[\w.-]{1,100}$/u.test(lastCall.name) ? lastCall.name : '工具'
    const details = message.content?.map(block => block.type === 'text' ? block.text : '').join(' ') ?? ''
    const code = /permission|unauthori[sz]ed|denied|没有授权|请在 DeskBox 桌面确认/iu.test(details) ? 'permission'
      : /deadline|timed?\s*out|timeout|超时/iu.test(details) ? 'timeout'
        : /unknown tool|not found|not registered|不可用|未注册/iu.test(details) ? 'unavailable' : 'tool_error'
    consecutiveFailures = lastFailure && (lastFailure.tool === tool || lastFailure.code === code && code !== 'tool_error')
      ? consecutiveFailures + 1 : 1
    lastFailure = { tool, code }
  })
  ctx.on('agent/pre-step', (_event, next) => {
    if (reporting) {
      onStop(stop('repeated_tool_error', lastFailure.code))
      return { kind: 'reject' }
    }
    if (consecutiveFailures >= 2) {
      reportOnly = reporting = true
      onStop(stop('repeated_tool_error', lastFailure.code))
    }
    steps++
    return next()
  })
  ctx.on('agent/request-error', ({ failure }, _next) => {
    const code = /^[\w.-]{1,64}$/u.test(failure?.code ?? '') ? failure.code : undefined
    onStop(stop(/QUOTA/.test(code ?? '') ? 'quota' : 'provider_error', code))
  })
}
