"""Package reviewed upstream plugins, retaining their MIT licenses and pinned sources.

No install/build scripts run. Use the official profile manager on the returned archives.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile
import tempfile
import io

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'bilibili': ('moxingovo/dsh-bilibili', '42cd1c9e7d975fc46cf62bd86024a134c37501d7'),
    'find-plugin': ('awesome-dsh-plugin/dsh-find-plugin', 'afce1cd43f98b8a8b02e4a35cd6a65d6444de412'),
}


def prepare(kind):
    repository, revision = SOURCES[kind]
    source = ROOT / '.tools/dsh-vendor' / ('review-' + kind)
    if not source.exists():
        subprocess.run(['git', 'clone', '--no-checkout', 'https://github.com/' + repository + '.git', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'checkout', '--detach', revision], check=True)
    current = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
    if current != revision or dirty:
        raise RuntimeError('Upstream checkout must match the reviewed revision without local changes')
    manifest = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    if manifest['license'] != 'MIT':
        raise RuntimeError('License differs from reviewed source')
    # Build artifacts are committed upstream. Runtime uses Desktop's matching peers.
    manifest.pop('devDependencies', None)
    manifest.pop('scripts', None)
    if kind == 'bilibili':
        manifest['description'] = 'B站文本工具（FatFish适配）：搜索、视频资料、已有字幕；不注册抽帧、媒体直链或自动转写。'
    for peer in manifest.get('peerDependencies', {}):
        if peer.startswith('@deepseek-ai/dsh-'):
            manifest['peerDependencies'][peer] = '0.2.1-rc.3'
    members = ['lib', 'cordis.patch.yml', 'LICENSE', 'README.md']
    if kind == 'find-plugin':
        members.append('data')
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / 'package.tgz'
        with tarfile.open(target, 'w:gz') as archive:
            for member in members:
                for file in sorted((source / member).rglob('*')) if (source / member).is_dir() else [source / member]:
                    if not file.is_file() or file.suffix == '.map':
                        continue
                    data = file.read_bytes()
                    if kind == 'bilibili' and file.relative_to(source).as_posix() == 'lib/index.js':
                        content = data.decode('utf-8')
                        for call in ('applyBilibiliPlayUrlTool(ctx, provider, resolved.timeoutMs);',
                                     'applyBilibiliFramesTool(ctx, provider, resolved.timeoutMs);'):
                            if content.count(call) != 1:
                                raise RuntimeError('Upstream registration changed')
                            content = content.replace(call, '// FatFish: text-only policy; tool not registered.')
                        start = content.index('const GUIDANCE = ')
                        end = content.index('\n', start)
                        content = content[:start] + 'const GUIDANCE = ' + json.dumps(
                            'Use bilibili_search, bilibili_video and bilibili_subtitles for public text only. '
                            'Cite the source video URL. Missing subtitles are not permission to download or transcribe media.') + ';' + content[end:]
                        data = content.encode('utf-8')
                    if kind == 'find-plugin' and file.suffix == '.js':
                        data = data.replace(b'--profile web add', b'--profile desktop add')
                        # Registry-supplied commands also need the current Desktop target.
                        if file.name == 'index.js':
                            data = data.replace(b'${m.install}', b'${m.install.replace(/--profile web\\b/g, "--profile desktop")}')
                            marker = b'install: String(plugin.install ?? `dsh plugin --profile desktop add github:${plugin.owner}/${plugin.name}`),'
                            if data.count(marker) != 1:
                                raise RuntimeError('Upstream discovery output changed')
                            data = data.replace(marker, marker[:-1] + b'.replace(/--profile web\\b/g, "--profile desktop"),')
                    info = tarfile.TarInfo('package/' + file.relative_to(source).as_posix())
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            for name, data in {
                'package.json': json.dumps(manifest, ensure_ascii=False, indent=2).encode(),
                'FATFISH-ADAPTATION.json': json.dumps({'source': 'https://github.com/' + repository,
                    'revision': revision, 'license': 'MIT', 'policy': 'text-only; Desktop-compatible peers and install hints'}, indent=2).encode(),
            }.items():
                info = tarfile.TarInfo('package/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    output = ROOT / '.tools/dsh-vendor/adapted' / f'{manifest["name"]}-{manifest["version"]}-{digest[:12]}.tgz'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return {'archive': str(output), 'sha256': digest, 'name': manifest['name'], 'version': manifest['version'], 'revision': revision}


if __name__ == '__main__':
    results = [prepare(kind) for kind in SOURCES]
    (ROOT / '.tools/dsh-vendor/adapted/community-current.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results))
