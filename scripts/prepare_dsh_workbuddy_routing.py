"""Add a balance-only routing service to the pinned MIT WorkBuddy connector."""

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

from prepare_dsh_codex_routing import replace_once


VERSION = "5.25.2"
ENTRY_SHA = "4c69ae130abdcd02d7b1d8ae87999492d0222b385a68dcd98854c5661bb5a56c"
ROOT = Path(__file__).resolve().parents[1]
SERVICE = '''
		let fatfishGeneration = 0;
		let fatfishSelection;
		const bounds = () => {
			const config = current();
			const account = effectiveAccountFor("cn", config);
			if (!regionEnabled(config, "cn") || poolPreferencesOf(config, "cn").enabled) return false;
			return account || null;
		};
		const generation = () => {
			const currentSelection = bounds();
			if (fatfishSelection !== currentSelection) {
				fatfishSelection = currentSelection;
				fatfishGeneration++;
			}
			return fatfishGeneration;
		};
		const knownGifts = new Set(["CodeBuddy个人版拉新权益包", "CodeBuddy个人版国内运营裂变包", "CodeBuddy个人体验版"]);
		ctx.provide("fatfishWorkBuddyQuota", {
			generation,
			async read(signal) {
				const startedAt = Date.now();
				const selection = bounds();
				const { store, catalog } = stacks.cn;
				const model = catalog.current().find(row => row.id === "deepseek-v4.1-flash");
				if (!selection || !catalog.hasLiveRoster() || model?.supportsToolCall !== true
					|| model.contextWindow < 1_000_000 || model.maxTokens < 128_000
					|| !Number.isFinite(model.creditMultiplier) || model.creditMultiplier <= 0) return undefined;
				const credential = await store.credentialFor(selection);
				if (signal.aborted || !credential || credential.enterpriseId) return undefined;
				const balance = await client.fetchCredits(credential);
				if (signal.aborted || bounds() !== selection) return undefined;
				const packages = balance.packages.filter(row => row.remain > 0);
				if (!packages.length || packages.some(row => !knownGifts.has(row.packageName))) return undefined;
				return {
					modelAvailable: true,
					fetchedAt: startedAt,
					giftCredits: balance.total,
					expiresAt: balance.nearestExpiryMs,
				};
			},
		});
'''


def pack(installed: Path, destination: Path) -> Path:
    metadata = json.loads((installed / "package.json").read_bytes())
    if (metadata["name"], metadata["version"], metadata["license"]) != ("dsh-connect-workbuddy", VERSION, "MIT"):
        raise ValueError("Unexpected WorkBuddy plugin package")
    raw = (installed / "lib/index.js").read_bytes()
    if sha256(raw).hexdigest() != ENTRY_SHA:
        raise ValueError("Unreviewed WorkBuddy plugin entry")
    anchor = "\t\t\tsyncRegionRegistration(current());"
    source = replace_once(raw.decode(), anchor, anchor + SERVICE)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f"workbuddy-routing-{VERSION}.tgz"
    with tarfile.open(temporary, "w:gz") as archive:
        for entry in sorted(installed.iterdir()):
            if entry.name.startswith(".") or entry.name == "node_modules":
                continue
            archive.add(entry, "package/" + entry.name,
                        filter=lambda member: None if member.name == "package/lib/index.js" else member)
        payload = source.encode()
        member = tarfile.TarInfo("package/lib/index.js")
        member.mode = 0o644
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    path = temporary.with_stem(temporary.stem + "-" + sha256(temporary.read_bytes()).hexdigest()[:12])
    temporary.replace(path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, default=Path("D:/DSHData/profiles/desktop/node_modules/dsh-connect-workbuddy"))
    parser.add_argument("--destination", type=Path, default=ROOT / ".tools/dsh-vendor/adapted")
    args = parser.parse_args()
    print(pack(args.installed, args.destination))
