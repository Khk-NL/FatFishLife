"""Patch the installed AGPL-3.0 Proactive Chat v1.2.6, preserving its scheduler.

Upstream: https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat
Existing upstream source/license remain in place. No upstream engine is copied
into this project. Stop AstrBot before --apply; default is a read-only preview.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fatfish_core.proactive_probability import DEFAULTS

PLUGIN = "astrbot_plugin_proactive_chat"
MARKER = "# FatFish probability gate; retain upstream AGPL-3.0 license."
IMPORT = MARKER + "\nfrom fatfish_core.proactive_probability import proactive_probability_allowed, proactive_probability_sent\n"


def patch_flow(source):
    if MARKER in source:
        if source.count("if not proactive_probability_allowed(") != 1 or source.count("            proactive_probability_sent(") != 1:
            raise ValueError("Incomplete proactive probability adapter")
        return source
    replacements = {
        "from __future__ import annotations\n": "from __future__ import annotations\n\n" + IMPORT,
        "            request_package = await self._prepare_llm_request(normalized_session_id)":
            "            if not proactive_probability_allowed(self, normalized_session_id, session_config):\n"
            "                await self._schedule_next_chat_and_save(normalized_session_id)\n"
            "                return\n\n"
            "            request_package = await self._prepare_llm_request(normalized_session_id)",
        "            await self._finalize_and_reschedule(":
            "            proactive_probability_sent(self, session_id)\n"
            "            await self._finalize_and_reschedule(",
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError("Proactive Chat flow differs from inspected v1.2.6")
        source = source.replace(before, after, 1)
    compile(source, "proactive_chat/core/chat_flow.py", "exec")
    return source


def patch_override(source):
    if '        "probability_settings",' in source:
        return source
    before = '        "schedule_settings",'
    if source.count(before) != 1:
        raise ValueError("Proactive Chat override shape differs from inspected v1.2.6")
    source = source.replace(before, before + '\n        "probability_settings",', 1)
    compile(source, "proactive_chat/core/session_override_manager.py", "exec")
    return source


def schema():
    return {"type":"object", "description":"FatFish progressive proactive probability", "items":{
        "base":{"type":"float", "default":1.0, "description":"主动聊天基础概率 p0（0～1），仍受原定时、免打扰与未回复上限限制"},
        "step":{"type":"float", "default":0.0, "description":"每次合格定时机会未发出消息后增加的概率（0～1）"},
        "max":{"type":"float", "default":1.0, "description":"概率上限（0～1）；每个完整对话独立计数"},
    }}


def configure(root: Path, *, apply=False):
    directory = root / "data/plugins" / PLUGIN
    metadata = (directory / "metadata.yaml").read_text(encoding="utf-8-sig")
    license_text = (directory / "LICENSE").read_text(encoding="utf-8-sig")
    if 'version: "v1.2.6"' not in metadata or "GNU AFFERO GENERAL PUBLIC LICENSE" not in license_text:
        raise ValueError("Requires inspected Proactive Chat v1.2.6 and its original AGPL license")
    flow = directory / "core/chat_flow.py"
    overrides = directory / "core/session_override_manager.py"
    schema_path = directory / "_conf_schema.json"
    config_path = root / "data/config" / (PLUGIN + "_config.json")
    definitions = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    for section in ("friend_settings", "group_settings"):
        definitions[section]["items"]["probability_settings"] = schema()
        settings = config.setdefault(section, {})
        settings["probability_settings"] = {**DEFAULTS, **settings.get("probability_settings", {})}
    pending = {
        flow:patch_flow(flow.read_text(encoding="utf-8-sig")),
        overrides:patch_override(overrides.read_text(encoding="utf-8-sig")),
        schema_path:json.dumps(definitions,ensure_ascii=False,indent=2)+"\n",
        config_path:json.dumps(config,ensure_ascii=False,indent=2)+"\n",
    }
    changed = [path for path,text in pending.items() if path.read_text(encoding="utf-8-sig") != text]
    backup = root / "data/private-config-backups" / datetime.now().strftime("%Y%m%d-proactive-probability-%H%M%S-%f")
    if apply:
        for path in changed:
            target=backup / path.relative_to(root / "data")
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            temporary=path.with_suffix(path.suffix+".probability.tmp")
            temporary.write_text(pending[path],encoding="utf-8");temporary.replace(path)
            assert path.read_text(encoding="utf-8") == pending[path]
    return {"applied":apply,"changed_files":[str(path.relative_to(root)) for path in changed],
            "upstream":"Pancakes-Labs/astrbot_plugin_proactive_chat v1.2.6 (AGPL-3.0)",
            "existing_scope_and_schedule_preserved":True}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot",type=Path,required=True)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    print(json.dumps(configure(args.astrbot,apply=args.apply),ensure_ascii=False))
