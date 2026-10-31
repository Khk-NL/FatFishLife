"""Package the host-only control bundle for the official DSH plugin manager."""
from pathlib import Path
import tarfile
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def pack() -> Path:
    source = ROOT / 'dsh/control'
    target = ROOT / '.tools/dsh-vendor/adapted/dsh-fatfish-life-0.1.0.tgz'
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, 'w:gz') as archive:
        for name in ('package.json', 'cordis.patch.yml', 'index.mjs', 'schedule.mjs', 'ops.mjs', 'settings.mjs',
                     'business.mjs', 'proactive.mjs', 'compose.mjs', 'llm.mjs', 'hub.mjs', 'bili.mjs', 'transport.mjs',
                     'moodsync.mjs',
                     'petmood.mjs',
                     'wallet.mjs',
                     'client.js', 'locale'):
            archive.add(source / name, arcname='package/' + name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    addressed = target.with_stem(target.stem + '-' + digest[:12])
    target.replace(addressed)
    (target.parent / 'control-current.json').write_text(json.dumps({'archive': str(addressed), 'sha256': digest}), encoding='utf-8')
    return addressed


if __name__ == '__main__':
    print(pack())
