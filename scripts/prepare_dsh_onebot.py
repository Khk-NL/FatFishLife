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
        return source

    def bridge(source):
        source = "import { beforeInbound, installSocialScope, assertOutbound, ownerCommand, parseNewTarget, SOCIAL_CHANNEL_PROMPT } from './runtime-adapter.mjs';\n" + source
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

    patch("index.js", entry)
    patch("bridge.js", bridge)
    patch("registry.js", registry)
    patch("interim.js", interim)
    patch("connection.js", connection)
    patch("tools.js", tools)
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