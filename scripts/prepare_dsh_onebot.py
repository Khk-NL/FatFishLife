"""Prepare an integrity-locked QQ bridge copy; never edit the desktop runtime."""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(source: str, old: str, new: str, count: int = 1) -> str:
    found = source.count(old)
    if found != count:
        raise RuntimeError(f"Upstream patch mismatch: expected {count}, found {found}: {old[:70]}")
    return source.replace(old, new)


def inbound(source: str) -> str:
    """NapCat 存图恒用 .jpg 后缀，但字节可能是 png/gif/webp；read_image 按魔数校验会拒绝。
    按魔数把文件改成正确后缀，保证 [图片:path] 指向一个真能读的文件。"""
    source = replace(
        source,
        "import { writeFile } from 'node:fs/promises';",
        "import { open, rename, writeFile } from 'node:fs/promises';",
    )
    helper = r"""/**
 * NapCat 把入站图片一律存成 .jpg，可实际字节可能是 png/gif/webp；read_image 会按魔数
 * 校验并拒绝扩展名与内容不符的文件。这里只读前 16 字节判断真实格式，必要时改名。
 */
async function normalizeImageExtension(filePath) {
    let head;
    try {
        const handle = await open(filePath, 'r');
        try {
            const buffer = Buffer.alloc(16);
            const { bytesRead } = await handle.read(buffer, 0, 16, 0);
            head = buffer.subarray(0, bytesRead);
        }
        finally {
            await handle.close();
        }
    }
    catch {
        return filePath;
    }
    let wanted = '';
    if (head.length >= 3 && head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff)
        wanted = '.jpg';
    else if (head.length >= 8 && head[0] === 0x89 && head[1] === 0x50 && head[2] === 0x4e && head[3] === 0x47)
        wanted = '.png';
    else if (head.length >= 4 && head.subarray(0, 4).toString('ascii') === 'GIF8')
        wanted = '.gif';
    else if (head.length >= 12 && head.subarray(0, 4).toString('ascii') === 'RIFF' && head.subarray(8, 12).toString('ascii') === 'WEBP')
        wanted = '.webp';
    if (wanted === '' || filePath.toLowerCase().endsWith(wanted))
        return filePath;
    const dot = filePath.lastIndexOf('.');
    const target = (dot > 0 ? filePath.slice(0, dot) : filePath) + wanted;
    try {
        await rename(filePath, target);
        return target;
    }
    catch {
        return filePath;
    }
}
"""
    source = replace(
        source,
        "export function normalizeOneBot11(event) {",
        helper + "export function normalizeOneBot11(event) {",
    )
    return replace(
        source,
        "                const settings = this.ctx.getSettings(chatId);\n"
        "                settings.lastImagePath = resolved.path;\n"
        "                settings.pendingImageRef = undefined;\n"
        "                return '[图片:' + resolved.path + ']';",
        "                const settings = this.ctx.getSettings(chatId);\n"
        "                const imagePath = await normalizeImageExtension(resolved.path);\n"
        "                settings.lastImagePath = imagePath;\n"
        "                settings.pendingImageRef = undefined;\n"
        "                return '[图片:' + imagePath + ']';",
    )


def prepare() -> Path:
    lock = json.loads((ROOT / "dsh/upstream-lock.json").read_text(encoding="utf-8"))["onebot"]
    cache = ROOT / ".tools/dsh-vendor"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{lock['name']}-{lock['version']}.tgz"
    if not archive.exists():
        with urllib.request.urlopen(lock["tarball"], timeout=60) as response:
            archive.write_bytes(response.read())
    sri = "sha512-" + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    if sri != lock["integrity"]:
        raise RuntimeError("QQ bridge integrity mismatch; refusing to prepare")
    pristine = cache / f"onebot-{lock['version']}"
    with tarfile.open(archive) as bundle:
        bundle.extractall(pristine, filter="data")
    target = cache / "prepared-onebot"
    shutil.copytree(pristine / "package", target, dirs_exist_ok=True)
    if not (target / "LICENSE").read_text(encoding="utf-8").startswith("BSD 3-Clause"):
        raise RuntimeError("Unexpected upstream license")
    package = json.loads((target / "package.json").read_text(encoding="utf-8"))
    # The official schemastery package has its own 3.x version, independent
    # of the DSH 0.x release train. Fix metadata rather than force-install.
    package["peerDependencies"]["@deepseek-ai/schemastery"] = "^3.18.0"
    (target / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for file in ("policy.mjs", "runtime-adapter.mjs"):
        shutil.copy2(ROOT / "dsh" / file, target / "lib" / file)

    def patch(name, transform):
        path = target / "lib" / name
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")

    def entry(source):
        source = "import { loadPolicy } from './runtime-adapter.mjs';\n" + source
        source = replace(source, "export const inject = ['tools',", "export const inject = ['fatfishSettings', 'tools',")
        source = replace(source, "    config = resolveDeprecatedConfig(config);", "    const fatfishPolicy = loadPolicy(ctx.fatfishSettings);\n    config = { ...resolveDeprecatedConfig(config), requireMention: false, interimMessages: false, sendErrorNotice: false, deferredTimeoutMs: 0, newMessagePolicy: 'queue', autoSteerPolicy: 'admin' };")
        source = replace(source, "const mediaDir = config.mediaDir !== '' ? config.mediaDir : defaultMediaDir();", "const mediaDir = join(config.mediaDir !== '' ? config.mediaDir : defaultMediaDir(), fatfishPolicy.sessionId('private:' + fatfishPolicy.config.botId));")
        source = replace(source, "    const policy = resolvePolicy(config);", "    const policy = { ...resolvePolicy(config), adminUsers: [String(fatfishPolicy.config.ownerId)] };")
        source = replace(source, "    const bridge = new ChatBridge({\n        ctx,", "    const bridge = new ChatBridge({\n        fatfishPolicy,\n        ctx,")
        source = replace(source, "        config: {\n            botQQ:", "        config: {\n            fatfishPolicy,\n            botQQ:")
        source = replace(
            source,
            "    logLevel: z.union([z.const('debug'), z.const('info'), z.const('warn'), z.const('error')]).default('info')",
            """    extraMediaRoots: z.array(z.string()).default([])
        .description('额外允许的出站媒体根目录（表情图库、TTS 输出等）'),
    logLevel: z.union([z.const('debug'), z.const('info'), z.const('warn'), z.const('error')]).default('info')""",
        )
        # 桥的 deps.config 是显式白名单，extraMediaRoots 不传进去等于没配
        source = replace(
            source,
            "            mediaDir,",
            "            mediaDir," + chr(10) + "            extraMediaRoots: config.extraMediaRoots,",
        )

        return source

    def bridge(source):
        source = "import { beforeInbound, installSocialScope, assertOutbound, ownerCommand, parseNewTarget, parseModeCommand, applyModeCommand, SOCIAL_CHANNEL_PROMPT } from './runtime-adapter.mjs';\n" + source
        source = replace(source, "    async handleInbound(event, opts = {}) {", "    async handleInbound(event, opts = {}) {\n        try {\n            const gated = await beforeInbound(this, event);\n            if (gated === false) return;\n            event = gated;\n        } catch (error) {\n            this.deps.log('error', 'FatFish ingress/delivery failed: ' + error.name);\n            return;\n        }")
        # 主人可在私聊用 /new group:<群号> 或 /new all 重置指定群会话（群里不出现字样）
        source = replace(
            source,
            "    tryHandleCommand(chatId, text, userId, nickname) {",
            """    tryHandleCommand(chatId, text, userId, nickname) {
        if (!this.deps.fatfishPolicy.owner(userId)) return Promise.resolve(false);
        const targeted = parseNewTarget(text);
        if (targeted) {
            const scopes = targeted.scope === 'all'
                ? [...this.chats.keys()].filter(id => id.startsWith('group:'))
                : [targeted.scope];
            return ownerCommand(this.deps.fatfishPolicy, async () => {
                let done = 0;
                for (const scope of scopes) {
                    try { await this.commandCtx.resetChat(scope); done += 1; } catch {}
                }
                if (String(chatId).startsWith('private:')) {
                    await this.sendToChat(chatId, '已重置 ' + done + ' 个群会话').catch(() => {});
                }
                return true;
            });
        }
        const modeCommand = parseModeCommand(text);
        if (modeCommand) {
            const result = applyModeCommand(this.deps.fatfishPolicy, text);
            if (result && String(chatId).startsWith('private:')) {
                this.sendToChat(chatId, result.reply).catch(() => {});
            }
            return Promise.resolve(true);
        }""",
        )
        source = replace(source, "    installChannelScope(agentCtx) {", "    installChannelScope(agentCtx) {\n        installSocialScope(agentCtx, this);")
        source = replace(source, 'text: buildPlatformPrompt(this.deps.config.restrictedMemberPrefix),', 'text: SOCIAL_CHANNEL_PROMPT,')
        # 上游的 registerTools 原样保留（发语音/发图的实现、限额、审计都是现成的）；
        # 只注册哪几个工具由 tools.js 的白名单决定，见下面的 tools() 补丁。
        source = replace(source,
            "        const candidates = [this.deps.config.mediaDir];",
            "        const candidates = [this.deps.config.mediaDir, ...(this.deps.config.extraMediaRoots ?? [])];")
        source = replace(source, "    guardedConnectionCall(action, params, chatId) {", "    guardedConnectionCall(action, params, chatId) {\n        assertOutbound(this.deps.fatfishPolicy, action);")
        source = replace(source, "this.sendToChat(chatId, QUEUE_NOTICE_TEXT).catch", "Promise.resolve([]).catch")
        source = replace(source, "            this.interim.onTurnEnd(chatId, chat);", "            if (reason.kind !== 'completed') chat.loopPending = null;\n            this.interim.onTurnEnd(chatId, chat);")
        return source

    def registry(source):
        source = "import { scopedSessionId } from './runtime-adapter.mjs';\n" + source
        source = replace(source, "sessionIdForChat(chatId)", "scopedSessionId(this.deps.config.fatfishPolicy, chatId)", 6)
        source = replace(source, "    async joinPreset(agentCtx, preferred) {\n        if (this.deps.agentPresets === undefined)\n            return;",
            "    async joinPreset(agentCtx, preferred) {\n        if (this.deps.agentPresets === undefined)\n            throw new Error('FatFish requires an available social preset service');")
        source = replace(source,
            "            this.deps.log('warn', 'agent preset mount failed (tools fall back to the global layer): ' + describeError(error));",
            "            this.deps.log('error', 'social preset mount failed: ' + describeError(error));\n            throw error;")
        return source

    def interim(source):
        source = replace(source, "        this.ctx.relayHostCards(chatId, message.content);", "        // Host control cards stay in the local management interface.\n        if (message.content.some(block => block.type === 'tool-call')) { chat.loopPending = null; return; }")
        return source

    def connection(source):
        return replace(source, "            // notice / request events are intentionally ignored (v1).", "            if (event.post_type === 'notice' && event.notice_type === 'notify' && event.sub_type === 'poke') this.onMessage(event);\n            // Other notices and requests stay ignored.")

    def tools(source):
        # 恢复上游的媒体发送工具，但只放行「发语音 / 发图」两个。
        # 其余 qq_send_*（视频/文件/转发/任意 segment）与 qq_napcat_api 继续不注册，
        # 避免把它们重新塞回模型的可选工具面（P1 撤掉它们是有原因的）。
        return replace(source,
            "    const register = (tool) => {\n        disposers.push(ctx.tools.register(tool));\n    };",
            "    const MEDIA_ALLOW = new Set(['qq_send_voice', 'qq_send_image']);\n"
            "    const register = (tool) => {\n"
            "        if (!MEDIA_ALLOW.has(tool.name)) return;\n"
            "        disposers.push(ctx.tools.register(tool));\n"
            "    };")

    def transport(source):
        # 控制层（dsh-fatfish-life）要发定时消息与主动开口，走桥自己的发送面：
        # 审计、分段、断线排队都在桥里，另起一个 OneBot 客户端只会分叉。
        anchor = ("    // Lifecycle: start the bridge and transport; unwind everything on unload.\n"
                  "    ctx.effect(() => {")
        injected = (
            "    // FATFISH: outbound text transport for the control layer.\n"
            "    try {\n"
            "        ctx.provide('dshOnebotTransport', {\n"
            "            connected: () => Boolean(connection.connected),\n"
            "            sendText: async (chatId, text) => {\n"
            "                await bridge.sendToChat(chatId, text);\n"
            "                return [];\n"
            "            },\n"
            "        });\n"
            "        log('debug', 'transport provided: dshOnebotTransport');\n"
            "    } catch (error) {\n"
            "        log('warn', 'transport provide failed: ' + describeError(error));\n"
            "    }\n"
            "    // FATFISH: [sticker:名字] 标记 -> dsh-nekowhale-stickers 的图片段。\n"
            "    try {\n"
            "        ctx.inject(['stickers'], (stickerCtx) => {\n"
            "            const kit = stickerCtx.get('stickers');\n"
            "            const forward = bridge.sendToChat.bind(bridge);\n"
            "            bridge.sendToChat = async (chatId, text, options = {}) => {\n"
            "                const raw = String(text ?? '');\n"
            "                const markers = [...raw.matchAll(/[[]sticker:([^\\]\\n]{1,40})[\\]]/g)];\n"
            "                if (!markers.length) return forward(chatId, text, options);\n"
            "                const rest = raw.replace(/[[]sticker:[^\\]\\n]{1,40}[\\]]/g, '').trim();\n"
            "                const ids = [];\n"
            "                if (rest) ids.push(...((await forward(chatId, rest, options)) ?? []));\n"
            "                for (const marker of markers) {\n"
            "                    const name = marker[1].trim();\n"
            "                    try {\n"
            "                        const hit = await kit.pick(name);\n"
            "                        if (!hit) {\n"
            "                            ids.push(...((await forward(chatId, '[表情:' + name + ']', options)) ?? []));\n"
            "                        } else {\n"
            "                            const file = await kit.file(hit);\n"
            "                            await bridge.sendSegments(chatId, [{ type: 'image', data: { file: file.path } }]);\n"
            "                            ids.push('sticker:' + name);\n"
            "                        }\n"
            "                    } catch (error) {\n"
            "                        log('warn', 'sticker send failed: ' + describeError(error));\n"
            "                    }\n"
            "                }\n"
            "                return ids;\n"
            "            };\n"
            "            log('debug', 'sticker markers enabled');\n"
            "        });\n"
            "    } catch (error) {\n"
            "        log('warn', 'sticker hook failed: ' + describeError(error));\n"
            "    }\n"
        )
        return replace(source, anchor, injected + anchor)

    patch("index.js", lambda source: transport(entry(source)))
    patch("bridge.js", bridge)
    patch("registry.js", registry)
    patch("interim.js", interim)
    patch("connection.js", connection)
    patch("tools.js", tools)
    patch("inbound.js", inbound)
    evidence = {"upstream": lock, "adapted_files": {
        str(path.relative_to(target)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((target / "lib").glob("*")) if path.is_file()
    }}
    (target / "fatfish-build.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return target


def pack(prepared: Path) -> Path:
    destination = prepared.parent / "adapted/fatfish-onebot-0.9.6.tgz"
    destination.parent.mkdir(exist_ok=True)
    with tarfile.open(destination, "w:gz") as bundle:
        for name in ("package.json", "cordis.patch.yml", "LICENSE", "README.md", "README.en.md", "lib"):
            bundle.add(prepared / name, arcname="package/" + name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    addressed = destination.with_stem(destination.stem + '-' + digest[:12])
    destination.replace(addressed)
    (destination.parent / 'onebot-current.json').write_text(json.dumps({'archive': str(addressed), 'sha256': digest}), encoding='utf-8')
    return addressed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", action="store_true", help="build an installable tarball, keeping the pinned upstream archive intact")
    args = parser.parse_args()
    prepared = prepare()
    if args.pack:
        print(pack(prepared))
    else:
        print(prepared)