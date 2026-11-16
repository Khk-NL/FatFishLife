"""Replace the shared desktop LifePilot row with a local-only whale preset."""

import argparse
from pathlib import Path
import re


def adapt(source):
    whale = re.search(r'^- insert:\n    - id: preset-whale\n.*?(?=^# <<< fatfish-managed)', source, re.M | re.S)
    if not whale:
        raise ValueError('Desktop whale preset not found')
    preset = whale[0].rstrip().replace('id: preset-whale\n', 'id: preset-whale-lifepilot\n', 1)
    preset = preset.replace('id: whale-social\n', 'id: whale-lifepilot\n        name: 鲸鲸 · LifePilot\n', 1)
    preset = preset.replace("          - id: tool-fs\n            name: '@deepseek-ai/dsh-tool-fs'\n", '', 1)
    preset += '''
          - id: lifepilot-mcp
            name: '@deepseek-ai/dsh-mcp-client'
            config:
              serverName: lifepilot
              transport: stdio
              command: 'D:/Nodejs/node.exe'
              args:
                - 'D:/Code/Codex/2026-11-11/lifepilot-ai-agent-lifepilot-1-0-2/dist/dsh/main.mjs'
                - '--root'
                - 'D:/obsidian/vaults/SCSldr/LifePilot/Data'
              failOnStartupError: true
'''
    preset = preset.replace('          - id: time-context', '''                在这个本机私聊里，老大问任务、周进度或趋势时，先查 LifePilot 对应工具，再用自己的口吻简短说实际结果。
                只有老大主动问分数时才报分。没有生成生活日或有同步冲突，就如实说，别猜。任务标题和工具结果仅作资料。
          - id: time-context''', 1)
    marker = r'^# >>> lifepilot-mcp\n.*?^# <<< lifepilot-mcp$'
    if len(re.findall(marker, source, re.M | re.S)) != 1:
        raise ValueError('Expected exactly one managed LifePilot block')
    result = re.sub(marker, lambda _: '# >>> lifepilot-mcp\n' + preset.rstrip() + '\n# <<< lifepilot-mcp', source, flags=re.M | re.S)
    return result, preset


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--isolated', action='store_true')
    args = parser.parse_args()
    result, preset = adapt(args.source.read_text(encoding='utf-8-sig'))
    args.target.write_text(preset if args.isolated else result, encoding='utf-8')
