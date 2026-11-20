"""Prepare a profile change while preserving the rest of the desktop YAML."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import yaml

from sync_persona_dsh import ROOT, structured_prefix_line

WORKSPACE = Path("D:/DSHData/whale-work")
PROFILE = Path("D:/DSHData/profiles/desktop/cordis.patch.yml")
VOICE_HEADER = "## 吞饭之鲸的说话规则"
BEGIN = "## FatFishLife local workbench"
END = "## End FatFishLife local workbench"


def mappings(node):
    if isinstance(node, yaml.MappingNode):
        return {key.value: value for key, value in node.value}
    return {}


def find_rows(document, name):
    rows = []
    if isinstance(document, yaml.SequenceNode):
        for node in document.value:
            nested = mappings(node).get("insert")
            candidates = nested.value if isinstance(nested, yaml.SequenceNode) else [node]
            rows.extend(mappings(item) for item in candidates
                        if getattr(mappings(item).get("id"), "value", None) == name)
    return rows


def voice_rules():
    output = subprocess.check_output(["node", "--input-type=module", "-e",
        "import { WHALE_VOICE } from './dsh/control/whale-voice.mjs'; console.log(WHALE_VOICE)"], cwd=ROOT)
    return output.decode("utf-8").strip()


def render(original: str, mcp: Path | None) -> tuple[str, str]:
    root = yaml.compose(original)
    lines = original.splitlines()
    at = structured_prefix_line(original)
    indent = len(lines[at]) - len(lines[at].lstrip())
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    persona = "\n".join(line[indent + 2:] if line.strip() else "" for line in lines[at + 1:end]).rstrip()
    if VOICE_HEADER in persona:
        persona = persona.split(VOICE_HEADER, 1)[0].rstrip()
    voice = voice_rules()
    full = persona + "\n\n" + VOICE_HEADER + "\n" + voice
    lines[at + 1:end] = [(" " * (indent + 2) + line) if line else "" for line in full.splitlines()]
    if not find_rows(root, "fatfish-control"):
        raise ValueError("control plugin missing from the target")
    result = "\n".join(lines) + "\n"
    # These are overrides in the profile's merge layer, never a replacement of a bundle.
    changes = [
        {"id": "fatfish-control", "config": {"peakEnabled": False, "workspaceDirectory": WORKSPACE.as_posix()}},
        {"id": "obsidian", "config": {"vaultPath": (WORKSPACE / "Notes").as_posix(), "vaultWorkspaceOnly": True}},
    ]
    if mcp:
        windows_bridge = {"id": "whale-workbench-windows", "name": "@deepseek-ai/dsh-mcp-client", "config": {
            "serverName": "windows", "transport": "stdio", "command": mcp.resolve(strict=True).as_posix(),
            "args": ["serve", "--exclude-tools", "App,PowerShell,FileSystem,Registry"], "toolCallTimeoutMs": 120000,
            "env": {"ANONYMIZED_TELEMETRY": "false", "WINDOWS_MCP_SCREENSHOT_SCALE": "0.75"},
            "failOnStartupError": False}}
        changes.append({"insert": [{"id": "whale-workbench-preset", "name": "@deepseek-ai/dsh-agent-preset",
            "config": {"id": "whale-workbench", "name": "鲸鲸工作台", "plugins": [
                {"id": "whale-persona", "name": (ROOT / "dsh/persona/runtime.mjs").as_uri(),
                    "config": {"cardFile": (ROOT / "dsh/persona/whale.json").as_posix(), "channel": "desktop"}},
                windows_bridge,
            ]}}]})
    if BEGIN + "\n" in result:
        before, managed = result.split(BEGIN + "\n", 1)
        if END + "\n" not in managed:
            raise ValueError("invalid FatFishLife settings block")
        result = before + managed.split(END + "\n", 1)[1]
    result = result.rstrip() + "\n\n" + BEGIN + "\n" + yaml.safe_dump(changes, allow_unicode=True, sort_keys=False) + END + "\n"
    yaml.compose(result)
    return result, full


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--source", type=Path, default=PROFILE)
    parser.add_argument("--windows-mcp", type=Path)
    args = parser.parse_args()
    original = args.source.read_bytes()
    result, persona = render(original.decode("utf-8-sig"), args.windows_mcp)
    args.target.mkdir(parents=True, exist_ok=False)
    (args.target / "cordis.patch.yml").write_text(result, encoding="utf-8")
    (args.target / "bilibili-persona.md").write_text(persona + "\n", encoding="utf-8")
    (args.target / "receipt.json").write_text(json.dumps({"sourceSha256": sha256(original).hexdigest(),
        "workspace": WORKSPACE.as_posix(), "peakEnabled": False, "windowsScoped": bool(args.windows_mcp)}), encoding="utf-8")
    print(args.target.resolve())


if __name__ == "__main__":
    main()
