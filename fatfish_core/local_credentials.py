"""Read a specifically named local credential without shell expansion or logging."""
from pathlib import Path
import re


def read_value(path: str | Path, names: tuple[str, ...], *, allow_bare=False) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        return ''
    entries, bare = {}, []
    for raw in file.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)', line)
        if match:
            value = match[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            entries[match[1].upper()] = value
        else:
            bare.append(line)
    for name in names:
        if entries.get(name.upper()):
            return entries[name.upper()]
    return bare[0].strip('\"\'') if allow_bare and len(bare) == 1 and not entries else ''
