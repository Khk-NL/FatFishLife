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
        source = replace(source, "    config = resolveDeprecatedConfig(config);", "    const fatfishPolicy = loadPolicy();\n    config = { ...resolveDeprecatedConfig(config), requireMention: false, interimMessages: false, sendErrorNotice: false, deferredTimeoutMs: 0, newMessagePolicy: 'queue', autoSteerPolicy: 'admin' };")
        source = replace(source, "const mediaDir = config.mediaDir !== '' ? config.mediaDir : defaultMediaDir();", "const mediaDir = join(config.mediaDir !== '' ? config.mediaDir : defaultMediaDir(), fatfishPolicy.sessionId('private:' + fatfishPolicy.config.botId));")
        source = replace(source, "    const policy = resolvePolicy(config);", "    const policy = { ...resolvePolicy(config), adminUsers: [String(fatfishPolicy.config.ownerId)] };")
        source = replace(source, "    const bridge = new ChatBridge({\n        ctx,", "    const bridge = new ChatBridge({\n        fatfishPolicy,\n        ctx,")
        source = replace(source, "        config: {\n            botQQ:", "        config: {\n            fatfishPolicy,\n            botQQ:")
        return source

    def bridge(source):
        source = "import { beforeInbound, installSocialScope, assertOutbound, ownerCommand } from './runtime-adapter.mjs';\n" + source
        source = replace(source, "    async handleInbound(event, opts = {}) {", "    async handleInbound(event, opts = {}) {\n        try {\n            const gated = await beforeInbound(this, event);\n            if (gated === false) return;\n            event = gated;\n        } catch (error) {\n            this.deps.log('error', 'FatFish ingress/delivery failed: ' + error.name);\n            return;\n        }")
        source = replace(source, "        return routeCommand(this.commandCtx, chatId, text, userId, nickname);", "        if (!this.deps.fatfishPolicy.owner(userId)) return Promise.resolve(false);\n        return ownerCommand(this.deps.fatfishPolicy, () => routeCommand(this.commandCtx, chatId, text, userId, nickname));")
        source = replace(source, "    installChannelScope(agentCtx) {", "    installChannelScope(agentCtx) {\n        installSocialScope(agentCtx, this);")
        source = replace(source, "    guardedConnectionCall(action, params, chatId) {", "    guardedConnectionCall(action, params, chatId) {\n        assertOutbound(this.deps.fatfishPolicy, action);")
        source = replace(source, "this.sendToChat(chatId, QUEUE_NOTICE_TEXT).catch", "Promise.resolve([]).catch")
        source = replace(source, "            this.interim.onTurnEnd(chatId, chat);", "            if (reason.kind !== 'completed') chat.loopPending = null;\n            this.interim.onTurnEnd(chatId, chat);")
        return source

    def registry(source):
        source = "import { scopedSessionId } from './runtime-adapter.mjs';\n" + source
        return replace(source, "sessionIdForChat(chatId)", "scopedSessionId(this.deps.config.fatfishPolicy, chatId)", 6)

    def interim(source):
        source = replace(source, "        this.ctx.relayHostCards(chatId, message.content);", "        // Host control cards stay in the local management interface.\n        if (message.content.some(block => block.type === 'tool-call')) { chat.loopPending = null; return; }")
        return source

    def connection(source):
        return replace(source, "            // notice / request events are intentionally ignored (v1).", "            if (event.post_type === 'notice' && event.notice_type === 'notify' && event.sub_type === 'poke') this.onMessage(event);\n            // Other notices and requests stay ignored.")

    patch("index.js", entry)
    patch("bridge.js", bridge)
    patch("registry.js", registry)
    patch("interim.js", interim)
    patch("connection.js", connection)
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
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", action="store_true", help="build an installable tarball, keeping the pinned upstream archive intact")
    args = parser.parse_args()
    prepared = prepare()
    if args.pack:
        print(pack(prepared))
    else:
        print(prepared)
