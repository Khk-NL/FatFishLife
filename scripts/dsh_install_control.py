"""Install visible FatFish controls into the Desktop-owned profile while DSH is quit."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_dsh_control import pack

CLI = Path('D:/dsh/resources/runtime/cli/bin/dsh.cmd')


def initial_config():
    identity = json.loads((ROOT/'dsh/policy.json').read_text(encoding='utf-8'))
    behavior = json.loads((ROOT/'data/dsh/behavior.json').read_text(encoding='utf-8'))
    voice, meme, life, bili = (behavior[key] for key in ('voice','meme','life','bili'))
    channel = lambda value: {'enabled': value['enabled'], 'basePercent': value['base']*100,
                             'stepPercent': value['step']*100, 'maxPercent': value['max']*100}
    return {'dataDirectory': (ROOT/'data/dsh').as_posix(),
        'identity': {key: identity[key] for key in ('adapterId','botId','ownerId')},
        'reply': {'silent': identity.get('silent', True), 'normalKeywords': identity.get('normalKeywords', []),
                  'groupCooldownSeconds': identity.get('groupCooldownMs',10000)/1000,
                  'userCooldownSeconds': identity.get('userCooldownMs',60000)/1000},
        'voice': {**channel(voice), 'textAlongsideVoice': voice['text_alongside_voice'],
                  'cooldownSeconds': voice['cooldown_seconds'], 'maxTextLength': voice['max_text_length'] or 0,
                  'manualTrigger': voice['manual_trigger'], 'provider': 'siliconflow'},
        'meme': {**channel(meme), 'manualTrigger': meme['manual_trigger'], 'maxPerMessage': meme['max_per_message']},
        'workflows': {'recommend': {'enabled': bool(bili.get('auto_scroll_enabled')), 'times': str(bili.get('auto_scroll_times') or '12:30,20:30').split(','),
                                     'commentEnabled': bool(bili.get('auto_scroll_comment_enabled'))},
                      'study': {'enabled': bool(bili.get('study_enabled')), 'time': bili.get('study_time') or '21:00'},
                      'comments': {'enabled': bool(bili.get('auto_reply')), 'ownerOnly': bool(bili.get('auto_reply_owner_only'))},
                      'daily': {'enabled': life['enabled'], 'publishEnabled': life['publish_enabled'], 'time': life['reflection_time'],
                                'basePercent': life['base']*100, 'stepPercent': life['step']*100, 'maxPercent': life['max']*100}}}


def add_patch(text: str, config: dict) -> str:
    # Preserve native !!js expressions, user comments, credentials and other rows.
    # Existing managed settings are kept so an upgrade never resets UI choices.
    if '# >>> fatfish-control' in text:
        return text
    significant = '\n'.join(line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')).strip()
    if significant in ('', '[]'):
        text = '# Desktop profile overrides\n'
    elif not significant.startswith('-'):
        raise RuntimeError('Unsupported profile patch layout; preserve it for manual review')
    if (re.search(r'(?m)^\s*-\s*id:\s*[\'\"]?fatfish-control[\'\"]?\s*$', text) or
        re.search(r'(?m)^\s*-\s*\{\s*"id"\s*:\s*"fatfish-control"', text)):
        raise RuntimeError('An existing FatFish control row needs review; not adding a duplicate')
    row = json.dumps({'id':'fatfish-control','config':config}, ensure_ascii=False)
    return text.rstrip() + '\n\n# >>> fatfish-control\n- ' + row + '\n# <<< fatfish-control\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    profile = Path.home()/'.dsh/profiles/desktop'
    patch = profile/'cordis.patch.yml'
    content = patch.read_text(encoding='utf-8-sig') if patch.exists() else '[]'
    composed = add_patch(content, initial_config())
    if args.dry_run:
        print(json.dumps({'profile':str(profile), 'plugin':'dsh-fatfish-life', 'changes_patch':composed!=content,
                          'connects_qq':False, 'changes_legacy_connection':False}))
        return 0
    running = subprocess.run(['powershell','-NoProfile','-Command',
        "@(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue).Count"], capture_output=True,text=True,timeout=15)
    if running.returncode or int(running.stdout.strip() or '0'):
        raise RuntimeError('请完全退出DeepSeek Harness后安装；不终止正在使用的应用')
    backup = ROOT/'outputs/dsh-migration'/('control-install-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    for name in ('package.json','pnpm-lock.yaml','pnpm-workspace.yaml','cordis.patch.yml','cordis.yml'):
        source = profile/name
        if source.exists(): shutil.copy2(source,backup/name)
    archive = pack()
    result = subprocess.run([str(CLI),'plugin','--profile','desktop','add','file:'+archive.as_posix(),'--ignore-scripts'],capture_output=True,timeout=120)
    (backup/'install.private.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('插件安装失败；见本机私有安装日志，配置未替换')
    current = patch.read_text(encoding='utf-8-sig') if patch.exists() else '[]'
    if current != content:
        raise RuntimeError('安装期间profile被修改，保留用户修改，不覆盖配置')
    patch.write_text(composed,encoding='utf-8')
    if patch.read_text(encoding='utf-8') != composed:
        raise RuntimeError('配置读回不一致')
    print(json.dumps({'installed':True,'profile':str(profile),'backup':str(backup),'connects_qq':False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
