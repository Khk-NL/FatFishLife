"""Prepare the installed MIT Codex addon with a credential-free quota service."""

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile


VERSION = "3.2.27"
ENTRY_SHA = "e3f5dd076056fe28595ff8fdf7a2270ab27dc1e27affac6cd583e0f243cc7eb8"
ROOT = Path(__file__).resolve().parents[1]
SERVICE = '''\tlet fatfishQuotaGeneration = 0;
\tctx.provide("fatfishCodexQuota", {
\t\tgeneration: () => fatfishQuotaGeneration,
\t\tasync read(signal) {
\t\t\tconst report = await usageReader.read({ signal });
\t\t\tconst windows = report.rateLimits.find(item => item.id === "codex")?.windows;
\t\t\tconst window = windows?.find(item => item.windowSeconds === 18000);
\t\t\tconst weekly = windows?.find(item => item.windowSeconds === 604800);
\t\t\treturn {
\t\t\t\tmodelAvailable: !report.rateLimitReachedType && !report.spendControlReached && provider.getModels()
\t\t\t\t\t.some(model => model.id === "gpt-6.2-sol" && model.thinkingLevelMap?.medium != null),
\t\t\t\tfetchedAt: report.fetchedAt,
\t\t\t\tremaining: window?.remainingPercent,
\t\t\t\tresetsAt: window?.resetsAt,
\t\t\t\tweeklyRemaining: weekly?.remainingPercent,
\t\t\t\tweeklyResetsAt: weekly?.resetsAt,
\t\t\t};
\t\t},
\t});
'''


def replace_once(source: str, anchor: str, updated: str) -> str:
    if source.count(anchor) != 1:
        raise ValueError(f"Unsupported upstream source at {anchor!r}")
    return source.replace(anchor, updated, 1)


def pack(installed: Path, destination: Path) -> Path:
    metadata = json.loads((installed / "package.json").read_text(encoding="utf-8"))
    if (metadata["name"], metadata["version"], metadata["license"]) != ("dsh-codex-subscription", VERSION, "MIT"):
        raise ValueError("Unexpected plugin package")
    raw = (installed / "lib/index.js").read_bytes()
    if sha256(raw).hexdigest() != ENTRY_SHA:
        raise ValueError("Unreviewed Codex plugin entry")
    source = raw.decode()
    anchor = '\tconst subscriptionHandler = createSubscriptionRpcHandler({'
    source = replace_once(source, anchor, SERVICE + anchor)
    anchor = '\t\tonAccountChanged: () => {\n\t\t\tremoteBridge.clearUploads();'
    source = replace_once(source, anchor, anchor.replace('\n', '\n\t\t\tfatfishQuotaGeneration++;\n', 1))
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f"codex-routing-{VERSION}.tgz"
    with tarfile.open(temporary, "w:gz") as archive:
        for entry in sorted(installed.iterdir()):
            if entry.name not in {"docs", "lib", "locale", "native", "compatibility.json", "cordis.patch.yml",
                                  "icon-subscription.webp", "package.json", "LICENSE", "THIRD_PARTY_NOTICES.md",
                                  "SECURITY.md", "DIRECTORY.md"} and not entry.name.startswith("README"):
                continue
            archive.add(entry, "package/" + entry.name,
                        filter=lambda member: None if member.name == "package/lib/index.js" else member)
        payload = source.encode()
        member = tarfile.TarInfo("package/lib/index.js")
        member.mode = 0o644
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    digest = sha256(temporary.read_bytes()).hexdigest()
    path = temporary.with_stem(temporary.stem + "-" + digest[:12])
    temporary.replace(path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, default=Path("D:/DSHData/profiles/desktop/node_modules/dsh-codex-subscription"))
    parser.add_argument("--destination", type=Path, default=ROOT / ".tools/dsh-vendor/adapted")
    args = parser.parse_args()
    print(pack(args.installed, args.destination))
