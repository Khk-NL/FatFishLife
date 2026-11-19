"""Read-only upgrade check for the official Desktop host and its active bundles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bundled_versions(archive: Path) -> dict[str, str]:
    with archive.open("rb") as stream:
        _, header_size, _, payload_size = struct.unpack("<IIII", stream.read(16))
        if not 0 < payload_size <= 32 * 1024 * 1024:
            raise ValueError("Invalid ASAR header size")
        tree = json.loads(stream.read(payload_size))
        for part in ("dsh", "node_modules", "@deepseek-ai"):
            tree = tree["files"][part]
        packages = {}
        for name, node in tree["files"].items():
            meta = node.get("files", {}).get("package.json")
            if not meta or "offset" not in meta:
                continue
            stream.seek(8 + header_size + int(meta["offset"]))
            packages[f"@deepseek-ai/{name}"] = json.loads(stream.read(meta["size"]))["version"]
        return packages


def host_requirements(manifest: dict, version: str) -> dict:
    # DSH's admission checks engines.dsh first; otherwise it compares DSH peers
    # against the host version, with prereleases included.
    engines = manifest.get("engines", {})
    if not isinstance(engines, dict):
        raise ValueError("Invalid plugin engines field")
    if "dsh" in engines:
        return {"engines.dsh": engines["dsh"]}
    requirements = manifest.get("peerDependencies", {})
    if not isinstance(requirements, dict):
        raise ValueError("Invalid plugin peerDependencies field")
    return {
        name: version if requirement in ("workspace:*", "workspace:^", "workspace:~") else requirement
        for name, requirement in requirements.items()
        if name == "@deepseek-ai/dsh" or name.startswith("@deepseek-ai/dsh-")
    }


def inspect(profile: Path, archive: Path, node: str, semver: Path) -> dict:
    manifest = read_manifest(profile / "package.json")
    active = manifest["dsh"]["profile"]["bundles"]
    versions = bundled_versions(archive)
    version = versions["@deepseek-ai/dsh"]
    missing, requirements, shadowed = [], {}, {}
    for bundle in active:
        path = profile / "node_modules" / bundle / "package.json"
        if bundle not in versions and not path.is_file():
            missing.append(bundle)
        elif bundle not in versions:
            requirements[bundle] = host_requirements(read_manifest(path), version)
    for name, expected in versions.items():
        for base in (profile / "node_modules", profile.parent / "node_modules"):
            path = base / name / "package.json"
            if path.is_file():
                actual = read_manifest(path).get("version")
                if actual != expected:
                    shadowed.setdefault(name, []).append({"expected": expected, "found": actual})
    script = """
const { satisfies } = require(process.argv[1]);
const { version, requirements } = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const bad = Object.entries(requirements).flatMap(([bundle, entries]) => {
  const unmet = Object.fromEntries(Object.entries(entries).filter(([, range]) =>
    typeof range !== 'string' || !range.trim() || !satisfies(version, range, { includePrerelease: true })));
  return Object.keys(unmet).length ? [{ bundle, unmet }] : [];
});
console.log(JSON.stringify(bad));
"""
    run = subprocess.run([node, "-e", script, str(semver)], check=True, capture_output=True,
                         input=json.dumps({"version": version, "requirements": requirements}),
                         encoding="utf-8", timeout=10)
    return {"host_version": version, "active_bundles": len(active), "missing": missing,
            "incompatible": json.loads(run.stdout), "sdk_version_conflicts": shadowed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("D:/DSHData/profiles/desktop"))
    parser.add_argument("--archive", type=Path, default=Path("D:/dsh/resources/app.asar"))
    parser.add_argument("--node", default="D:/Nodejs/node.exe")
    parser.add_argument("--semver", type=Path, default=Path("D:/Nodejs/node_modules/npm/node_modules/semver"))
    options = parser.parse_args()
    try:
        result = inspect(options.profile, options.archive, options.node, options.semver)
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": "DSH compatibility could not be verified",
                          "error_type": type(exc).__name__}))
        return 2
    conflicts = result.pop("sdk_version_conflicts")
    result["sdk_version_conflict_count"] = len(conflicts)
    result["sdk_version_conflict_examples"] = dict(list(sorted(conflicts.items()))[:8])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["missing"] or result["incompatible"] or conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
