"""Build the reviewed See Now package with manual, session-scoped capture."""

import base64
import gzip
import hashlib
import io
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs/saos-plugins-20261116'
UPSTREAM = OUTPUT / 'dsh-see-now-0.2.2.tgz'
SRI = 'cjJrhH0ifIQxTPeJks72/MfIAyd1R0UrXVj6xKJpE38s4YLE4IvNBvtkXCFa8wojvsQCj5UTxX3DNcj+cpOHcg=='


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Unexpected upstream source near {old}')
    return text.replace(old, new, 1)


def adapt_index(text):
    text = replace_once(text, '  let lastCallerSessionId = null;',
                        '  let lastCallerSessionId = null;\n  let manualCaptureSession = null;')
    text = replace_once(text, '    async execute(args = {}, run = {}) {', '''    async execute(args = {}, run = {}) {
      if (!manualCaptureSession || manualCaptureSession !== callerSessionOf(run)
          || !runner.status().running) {
        return { text: '请在当前 DSH 会话手动输入 /seenow 开始采集。' };
      }
      // Changing source can restart capture and must go through the user's command.
      if (args.source != null || args.src != null || args.device != null || args.listen
          || !['peek', 'status', 'stop', 'help'].includes(String(args.action ?? 'peek').toLowerCase())) {
        return { text: '采集由 /seenow 控制。可以查看当前画面、状态或停止。' };
      }
      args = { ...args, action: args.action ?? 'peek' };''')
    text = replace_once(text, '      startCapture: async () => {', '''      startCapture: async (agent) => {
        const owner = callerSessionOf({ agent });
        const cwd = String(agent?.session?.header?.cwd ?? '').replaceAll('\\\\', '/').toLowerCase();
        if (!owner || !cwd || /\/(?:qq-work|whale-work)(?:\/|$)|\/fatfish-wechat(?:\/|$)/.test(cwd)) {
          return { error: '请在本机 DSH 会话开启桌面采集' };
        }
        if (manualCaptureSession && manualCaptureSession !== owner && runner.status().running) {
          return { error: '请先在当前采集会话停止采集' };
        }''')
    text = replace_once(text, "        return runner.start({ src: built.src ?? { kind: 'screen' } });",
                        """        const started = await runner.start({ src: built.src ?? { kind: 'screen' } });
        if (!started?.error && runner.status().running) manualCaptureSession = owner;
        return started;""")
    return replace_once(text, '      stopCapture: () => { try { runner.stop(); }',
                        '      stopCapture: () => { manualCaptureSession = null; try { runner.stop(); }')


def main():
    raw = UPSTREAM.read_bytes()
    if base64.b64encode(hashlib.sha512(raw).digest()).decode() != SRI:
        raise ValueError('Unexpected upstream npm archive')
    output = io.BytesIO()
    with (tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as src,
          gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed,
          tarfile.open(fileobj=compressed, mode='w') as dst):
        for member in src:
            data = src.extractfile(member).read() if member.isfile() else None
            if member.name == 'package/src/index.js':
                data = adapt_index(data.decode()).encode()
            elif member.name == 'package/src/command.js':
                data = replace_once(data.decode(), 'await deps.startCapture?.()',
                                    'await deps.startCapture?.(onAgent)').encode()
            if data is not None:
                member.size = len(data)
            dst.addfile(member, io.BytesIO(data) if data is not None else None)
    data = output.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    archive = OUTPUT / f'dsh-see-now-0.2.2-fatfish-{digest[:12]}.tgz'
    archive.write_bytes(data)
    print(archive)


if __name__ == '__main__':
    main()
