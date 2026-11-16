"""Build the FatFishLife adaptation from the pinned upstream dsh-wechat archive."""

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
    return replace_once(source, '  /** Mark one bot', '''  #isBoundOwner(conversationKey) {
    const sender = userIdOf(conversationKey)
    const credential = this.store.credentialsFor(this.#botOf(conversationKey))
    return Boolean(sender && credential?.ownerUserId === sender)
  }

  /** Mark one bot''')


def main():
    if hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError('Unexpected upstream archive SHA256')
    output = io.BytesIO()
    with tarfile.open(UPSTREAM, 'r:gz') as source, tarfile.open(fileobj=output, mode='w:gz') as result:
        for member in source:
            data = source.extractfile(member).read() if member.isfile() else None
            if member.name == BRIDGE:
                data = adapt_bridge(data.decode()).encode()
                member.size = len(data)
            result.addfile(member, io.BytesIO(data) if data is not None else None)
        for filename, target in [('wechat-shared-context.mjs', CONTEXT),
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
