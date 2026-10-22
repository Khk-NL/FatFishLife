"""Cache public StarRailRes portraits for the offline character picker."""

import concurrent.futures
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/"


def fetch(relative, destination):
    request = urllib.request.Request(BASE + relative, headers={"User-Agent": "FatFishLife-local-test"})
    with urllib.request.urlopen(request, timeout=40) as response:
        destination.write_bytes(response.read())


def main():
    folder = ROOT / "assets/characters"
    folder.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(BASE + "index_new/cn/characters.json", timeout=40) as response:
        source = json.load(response)
    records, jobs = [], []
    previous = folder / "catalog.json"
    fronts = {c["id"]: c["front"] for c in json.loads(previous.read_text(encoding="utf-8"))["characters"] if "front" in c} if previous.exists() else {}
    for key, character in source.items():
        if "{" in character["name"]:
            continue  # 主角昵称占位项没有固定角色名。
        record = {"id": key, "name": character["name"], "tag": character["tag"], "rarity": character["rarity"]}
        if key in fronts:
            record["front"] = fronts[key]
        for kind, remote in (("icon", character["icon"]), ("preview", character["preview"])):
            filename = f"{key}-{kind}.png"
            record[kind] = "/assets/characters/" + filename
            target = folder / filename
            if not target.exists():
                jobs.append((remote, target))
        records.append(record)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch, relative, target) for relative, target in jobs]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    manifest = {"source": "https://github.com/Mar-7th/StarRailRes", "characters": records}
    (folder / "catalog.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Cached {len(records)} characters, downloaded {len(jobs)} images.")


if __name__ == "__main__":
    main()
