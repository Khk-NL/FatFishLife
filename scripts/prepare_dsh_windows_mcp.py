"""Configure the installed MIT dsh-windows-mcp carrier with a local stdio executable."""

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

from prepare_dsh_codex_routing import replace_once


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.11"
STARTUP_TIMEOUT_MS = 25_000
EXPECTED = {
    "cordis.patch.yml": "c457362a31403877d668da683199a15fb7f6bad3f9ce35de5cd4d549dd3f2216",
    "lib/dependency.js": "73d9640e54981a1ed4a2a4d7b44a68d12ff62555b6f162ab225a1f146148e673",
}


def pack(installed: Path, executable: Path, destination: Path) -> Path:
    metadata = json.loads((installed / "package.json").read_bytes())
    if (metadata["name"], metadata["version"], metadata["license"]) != ("dsh-windows-mcp", VERSION, "MIT"):
        raise ValueError("Unexpected Windows MCP carrier")
    executable = executable.resolve(strict=True)
    version_dir = executable.parent.parent / "Lib/site-packages/windows_mcp-0.8.8.dist-info"
    if not executable.is_file() or not version_dir.is_dir():
        raise ValueError("Expected a local Windows-MCP 0.8.8 executable")
    sources = {}
    for name, checksum in EXPECTED.items():
        raw = (installed / name).read_bytes()
        if sha256(raw).hexdigest() != checksum:
            raise ValueError(f"Unreviewed Windows MCP source: {name}")
        sources[name] = raw.decode()

    command = json.dumps(executable.as_posix())
    patch = sources["cordis.patch.yml"]
    patch = replace_once(patch, "\n      disabled: true\n", "\n      disabled: false\n")
    patch = replace_once(patch, "        command: uvx\n", f"        command: {command}\n")
    patch = replace_once(patch, "          - windows-mcp@0.8.8\n", "")
    patch = replace_once(patch, "          - App,PowerShell,FileSystem\n",
                         "          - App,PowerShell,FileSystem,Registry\n")

    patch = replace_once(patch, "        toolCallTimeoutMs: 120000\n",
                         f"        startupTimeoutMs: {STARTUP_TIMEOUT_MS}\n        toolCallTimeoutMs: 120000\n")

    dependency = sources["lib/dependency.js"]
    dependency = replace_once(dependency, '    "    transport: stdio",\n',
                              '    "    transport: stdio",\n'
                              f'    "    startupTimeoutMs: {STARTUP_TIMEOUT_MS}",\n')
    dependency = replace_once(dependency, "import { isAbsolute, basename, join, relative }",
                              "import { isAbsolute, basename, dirname, join, relative }")
    dependency = replace_once(dependency, '  const directory = windowsMcpToolDirectory();',
                              f'  const local = {command};\n'
                              '  if (process.platform === "win32" && existsSync(local)) return local;\n'
                              '  const directory = windowsMcpToolDirectory();')
    dependency = replace_once(dependency, "  return toolVersionIn(windowsMcpToolDirectory());",
                              "  return toolVersionIn(dirname(dirname(executable)));")

    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"windows-mcp-local-{VERSION}.tgz"
    overlays = {"cordis.patch.yml": patch.encode(), "lib/dependency.js": dependency.encode()}
    with tarfile.open(target, "w:gz") as archive:
        for path in sorted(installed.iterdir()):
            if path.name.startswith(".") or path.name == "node_modules":
                continue
            archive.add(path, "package/" + path.name, filter=lambda member:
                        None if member.name.removeprefix("package/") in overlays else member)
        for name, payload in overlays.items():
            member = tarfile.TarInfo("package/" + name)
            member.mode = 0o644
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    output = target.with_stem(target.stem + "-" + sha256(target.read_bytes()).hexdigest()[:12])
    target.replace(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, default=Path("D:/DSHData/profiles/desktop/node_modules/dsh-windows-mcp"))
    parser.add_argument("--executable", type=Path, default=ROOT / ".tools/windows-mcp-py314/Scripts/windows-mcp.exe")
    parser.add_argument("--destination", type=Path, default=ROOT / ".tools/dsh-vendor/adapted")
    args = parser.parse_args()
    print(pack(args.installed, args.executable, args.destination))
