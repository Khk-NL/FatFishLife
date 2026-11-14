"""Install the pinned WeChat channel into the stopped DSH desktop profile."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOME = Path('D:/DSHData')
PROFILE = HOME / 'profiles/desktop'
PATCH = PROFILE / 'cordis.patch.yml'
MANIFEST = PROFILE / 'package.json'
CLI = Path('D:/dsh/resources/runtime/cli/bin/dsh.cmd')
PACKAGE = 'dsh-wechat'
VERSION = '0.3.7'
ARCHIVE = ROOT / 'outputs/clawbot-20261114' / f'{PACKAGE}-{VERSION}.tgz'
SHA256 = '30c51947b071923dcd12673e600d399896b69068d673e8cb07a81d3a2e6dfaf7'
TEMPLATE = ROOT / 'dsh/templates/wechat-clawbot.patch.yml'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def require_desktop_closed():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        "@(Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True, check=True, timeout=15)
    if result.stdout.strip() != '0':
        raise RuntimeError('请从 Windows 托盘完全退出 DSH 后再安装。')


def replace_patch(before, after):
    temp = PATCH.with_name(f'{PATCH.name}.wechat-{os.getpid()}.tmp')
    with temp.open('xb') as stream:
        stream.write(after)
    try:
        if PATCH.read_bytes() != before:
            raise RuntimeError('发现并发桌面配置修改，已保留该修改。')
        temp.replace(PATCH)
    finally:
        temp.unlink(missing_ok=True)


def config_rows(content):
    document = yaml.compose(content.decode('utf-8-sig'))
    if not isinstance(document, yaml.SequenceNode):
        raise ValueError('桌面配置需要是 YAML 列表。')
    return [
        row for row in document.value if isinstance(row, yaml.MappingNode)
        and any(key.value == 'id' and getattr(value, 'value', None) == PACKAGE
                for key, value in row.value)
    ]


def proposed_patch(before, template):
    if config_rows(before):
        raise ValueError('桌面已有微信配置，保留原配置。')
    old = before.decode('utf-8-sig')
    if not yaml.compose(old).value:
        old = ''.join(line for line in old.splitlines(keepends=True) if line.strip() != '[]')
    newline = '\r\n' if '\r\n' in old else '\n'
    addition = newline.join(template.splitlines())
    after = (old.rstrip('\r\n') + newline + newline + addition + newline).encode(
        'utf-8-sig' if before.startswith(b'\xef\xbb\xbf') else 'utf-8')
    if len(config_rows(after)) != 1:
        raise ValueError('微信配置校验失败。')
    return after


def install():
    require_desktop_closed()
    if not ARCHIVE.is_file() or hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != SHA256:
        raise ValueError('微信包缺失或 SHA256 不符。')
    before = PATCH.read_bytes()
    before_manifest = read_json(MANIFEST)
    if PACKAGE in before_manifest['dependencies']:
        raise ValueError('桌面已经安装微信插件，请检查当前设置。')
    after = proposed_patch(before, TEMPLATE.read_text(encoding='utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = ARCHIVE.parent / f'desktop-backup-{stamp}'
    backup.mkdir()
    for name in ('package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'cordis.patch.yml'):
        path = PROFILE / name
        if path.is_file():
            (backup / name).write_bytes(path.read_bytes())
    print(f'备份：{backup}', flush=True)

    require_desktop_closed()
    if PATCH.read_bytes() != before or read_json(MANIFEST) != before_manifest:
        raise RuntimeError('检测到并发配置改动。')
    # Apply the restrictive patch before installing the bundle, whose own autoLogin defaults to true.
    replace_patch(before, after)
    try:
        install_env = {**os.environ, 'DSH_HOME': str(HOME), 'DSH_PROFILE': 'desktop'}
        with (backup / 'install.private.log').open('wb') as log:
            subprocess.run([str(CLI), 'plugin', '--profile', 'desktop', 'add',
                            'file:' + ARCHIVE.as_posix(), '--ignore-scripts',
                            '--store-dir', str(ARCHIVE.parent / 'pnpm-store')],
                           cwd=PROFILE, env=install_env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
    except (OSError, subprocess.SubprocessError):
        if read_json(MANIFEST) == before_manifest and PATCH.read_bytes() == after:
            replace_patch(after, before)
        raise

    installed = read_json(PROFILE / 'node_modules' / PACKAGE / 'package.json')
    current = read_json(MANIFEST)
    spec = current['dependencies'].get(PACKAGE, '')
    expected = before_manifest
    expected['dependencies'][PACKAGE] = spec
    expected.setdefault('dsh', {}).setdefault('profile', {}).setdefault('bundles', []).append(PACKAGE)
    if (installed['version'] != VERSION or not spec.startswith('file:')
            or not spec.endswith(ARCHIVE.name) or current != expected or PATCH.read_bytes() != after):
        raise RuntimeError('安装后的配置读回与预期不符，请检查备份。')
    (HOME / 'private/fatfish-wechat/workspace').mkdir(parents=True, exist_ok=True)
    print('微信插件已安装。重新打开 DSH 后，在设置里手动绑定。')


if __name__ == '__main__':
    try:
        install()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except yaml.YAMLError:
        print('桌面 YAML 解析失败，请检查本机配置。', file=sys.stderr)
        raise SystemExit(1)
