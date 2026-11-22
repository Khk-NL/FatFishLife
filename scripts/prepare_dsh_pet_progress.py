"""Adapt reviewed dsh-pet 0.4.3 task bubbles to show native todo counts."""

import argparse
from hashlib import file_digest, sha256
import io
import json
from pathlib import Path
import tarfile

from prepare_dsh_codex_routing import replace_once


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.3"
SOURCES = {
    "lib/index.js": "dda0afa88753a1818a623b96ea3082936181d84c015f5de37f44ca00278cc30b",
    "src/host/work-status.ts": "59517a24676d7688f92506ab1c12ee9ddf1d84b2362d703241c9e42158a1ddb6",
}


def add_progress(source: str, indent: str) -> str:
    before = indent + "const points = Array.from(content);\n"
    after = "\n".join(indent + line for line in (
        "// Counts are meaningful only for a complete list of recognized native statuses.",
        "const valid = todos.every(item => item?.status === 'pending'",
        "  || item?.status === 'in_progress' || item?.status === 'completed');",
        "const completed = todos.filter(item => item?.status === 'completed').length;",
        "const prefix = valid ? `${completed}/${todos.length} ` : '';",
        "const label = prefix + content;",
        "const points = Array.from(label);",
    )) + "\n"
    start = source.index("function currentTaskFromTodo(")
    end = source.index("\n}\n", start) + 2
    task = replace_once(source[start:end], before, after)
    task = replace_once(task, "points.slice(0, TASK_TEXT_MAX)", "points.slice(0, TASK_TEXT_MAX - 1)")
    task = replace_once(task, " : content;", " : label;")
    return source[:start] + task + source[end:]


def pack(source: Path, destination: Path) -> Path:
    package = json.loads((source / "package.json").read_bytes())
    if (package["name"], package["version"], package["license"]) != ("dsh-pet", VERSION, "MIT"):
        raise ValueError("Expected the reviewed dsh-pet release")
    overlays = {}
    for name, expected in SOURCES.items():
        raw = (source / name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError(f"Unreviewed dsh-pet source: {name}")
        indent = "  " if name.endswith(".ts") else "\t"
        overlays[name] = add_progress(raw.decode(), indent).encode()
    overlays["FATFISH-ADAPTATION.json"] = json.dumps({
        "source": "https://github.com/PC2005-cloud/dsh-pet",
        "version": VERSION,
        "codeLicense": "MIT",
        "designReference": "https://github.com/QCYTSN/dsh-dafeiyu/blob/v0.1.23/src/companion-reducer.js",
    }, indent=2).encode()
    destination.mkdir(parents=True, exist_ok=True)
    pending = destination / f"dsh-pet-progress-{VERSION}.tgz"
    with tarfile.open(pending, "w:gz", compresslevel=4) as archive:
        for path in sorted(source.iterdir()):
            if path.name in ("node_modules", "FATFISH-ADAPTATION.json") or path.name.startswith("."):
                continue
            archive.add(path, "package/" + path.name, filter=lambda member:
                        None if member.name.removeprefix("package/") in overlays else member)
        for name, data in overlays.items():
            entry = tarfile.TarInfo("package/" + name)
            entry.mode = 0o644
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    with pending.open("rb") as file:
        digest = file_digest(file, "sha256").hexdigest()[:12]
    target = pending.with_stem(f"{pending.stem}-{digest}")
    pending.replace(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, default=Path("D:/DSHData/profiles/desktop/node_modules/dsh-pet"))
    parser.add_argument("--destination", type=Path, default=ROOT / ".tools/dsh-vendor/adapted")
    arguments = parser.parse_args()
    print(pack(arguments.installed, arguments.destination))
