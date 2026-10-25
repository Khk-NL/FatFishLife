"""Reapply a small probability adapter to installed meme_manager 5.2.5 (MIT)."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARKER = "# FatFish progressive meme policy (upstream MIT integration)."
IMPORT = MARKER + "\nfrom fatfish_core.meme_probability import (meme_probability_hit, progressive_response, progressive_decorate, progressive_after_sent, progressive_image_send, progressive_compat_send)\n"


def patch_source(source):
    if MARKER in source:
        if not all(source.count("@" + name) == 1 for name in ("progressive_response", "progressive_decorate", "progressive_after_sent", "progressive_image_send", "progressive_compat_send")):
            raise ValueError("Incomplete progressive meme adapter")
        compile(source, "meme_manager/event_handlers.py", "exec")
        return source
    anchor = "from ..utils import probability_hit\n"
    if source.count(anchor) != 1:
        raise ValueError("Installed meme_manager imports differ from inspected 5.2.5")
    source = source.replace(anchor, anchor + "\n" + IMPORT, 1)
    start = source.find("    def _meme_probability_hit(self, event) -> bool:\n")
    end = source.find("    async def _mark_llm_request_origin_impl", start)
    if start < 0 or end < start:
        raise ValueError("The existing progressive meme patch was not found")
    source = source[:start] + "    def _meme_probability_hit(self, event) -> bool:\n        return meme_probability_hit(self, event)\n\n" + source[end:]
    for name, decorator in (("_resp_impl", "progressive_response"), ("_on_decorating_result_impl", "progressive_decorate"),
                            ("_after_message_sent_impl", "progressive_after_sent"), ("_send_meme_image", "progressive_image_send"),
                            ("compat_send_prepared_message", "progressive_compat_send")):
        anchor = "    async def " + name + "("
        if source.count(anchor) != 1:
            raise ValueError("Installed meme_manager method differs: " + name)
        source = source.replace(anchor, "    @" + decorator + "\n" + anchor, 1)
    old = "        random_value = random.randint(1, 100)\n        if random_value > self.emotions_probability:\n            return [], []\n"
    if source.count(old) != 1:
        raise ValueError("Compatibility probability implementation differs")
    source = source.replace(old, "        if not self._meme_probability_hit(event):\n            return [], []\n", 1)
    old = '        if semantic_mode == "llm":\n            return await self._resp_semantic_llm_impl(event, response, text)\n'
    if source.count(old) != 1:
        raise ValueError("Semantic response implementation differs")
    source = source.replace(old, '        if semantic_mode == "llm":\n            if not self._meme_probability_hit(event):\n                return await self._resp_semantic_impl(event, response, text)\n            return await self._resp_semantic_llm_impl(event, response, text)\n', 1)
    # The original helper discarded Context.send_message's False failure result.
    old = '        await self.context.send_message(event.unified_msg_origin, MessageChain([image]))\n'
    if source.count(old) != 1:
        raise ValueError("Native image sender implementation differs")
    source = source.replace(old, old.replace("        await ", "        return await "), 1)
    compile(source, "meme_manager/event_handlers.py", "exec")
    return source


def configure(root: Path, *, apply=False):
    plugin = root / "data/plugins/meme_manager"
    metadata = (plugin / "metadata.yaml").read_text(encoding="utf-8-sig")
    if not re.search(r"^version:\s*5\.2\.5\s*$", metadata, re.M):
        raise ValueError("Requires inspected meme_manager 5.2.5; review upgrades first")
    license_text = (plugin / "LICENSE").read_text(encoding="utf-8-sig")
    if "MIT License" not in license_text:
        raise ValueError("Upstream MIT attribution missing")
    source_path = plugin / "mixins/event_handlers.py"
    schema_path = plugin / "_conf_schema.json"
    config_path = root / "data/config/meme_manager_config.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    emotion = schema["generation"]["items"]["emotion"]["items"]
    for key, default, description in (("probability_step", 10, "每次合格但未发出表情增加的百分点（0～100，填2表示增加2个百分点）"),
                                      ("probability_max", 90, "表情概率上限（0～100，填90表示90%）")):
        emotion[key] = {"type":"float", "default":default, "description":description, "hint":"0～100；基础概率+n×每次递增，最高不超过上限"}
    emotion["manual_trigger"] = {"type":"bool", "default":True,
                                 "description":"明确要求发表情时跳过随机概率；仍使用原有会话范围、语义候选校验与发送流程"}
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    values = config.setdefault("generation", {}).setdefault("emotion", {})
    values.setdefault("probability_step", 10)
    values.setdefault("probability_max", 90)
    values.setdefault("manual_trigger", True)
    from fatfish_core.progressive_probability import progressive_probability
    progressive_probability(float(values.get("probability", 35))/100, float(values["probability_step"])/100, 0, ceiling=float(values["probability_max"])/100)
    pending = {source_path:patch_source(source_path.read_text(encoding="utf-8-sig")),
               schema_path:json.dumps(schema, ensure_ascii=False, indent=2)+"\n",
               config_path:json.dumps(config, ensure_ascii=False, indent=2)+"\n"}
    changed = [path for path, value in pending.items() if path.read_text(encoding="utf-8-sig") != value]
    backup = root / "data/private-config-backups" / datetime.now().strftime("%Y%m%d-meme-probability-%H%M%S-%f")
    if apply:
        for path in changed:
            target = backup / path.relative_to(root / "data")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            temporary = path.with_suffix(path.suffix + ".meme-probability.tmp")
            temporary.write_text(pending[path], encoding="utf-8")
            temporary.replace(path)
            assert path.read_text(encoding="utf-8") == pending[path]
    return {"applied":apply, "changed_files":[str(path.relative_to(root)) for path in changed],
            "base_percent":values.get("probability",35), "step_percent":values["probability_step"],
            "max_percent":values["probability_max"], "upstream":"anka-afk/astrbot_plugin_meme_manager@5.2.5 (MIT)"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(configure(args.astrbot, apply=args.apply), ensure_ascii=False))
