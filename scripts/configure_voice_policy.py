"""Install small policy hooks into the existing MIT TTS Emotion Router 3.3.3.

Source: https://github.com/muyouzhi6/astrbot_plugin_tts_emotion_router
No provider, synthesis client or second message pipeline is installed. Stop
AstrBot before --apply. Existing secrets and unrelated settings are preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fatfish_core.voice_policy import DEFAULT_POLICY

PLUGIN = "astrbot_plugin_tts_emotion_router"
MARKER = "# FatFish policy adapter (upstream MIT; do not remove upstream attribution)."
IMPORT = MARKER + "\nfrom fatfish_core.voice_policy import guarded_result, guarded_manual\n"


def patch_source(source: str):
    if MARKER in source:
        if source.count("@guarded_result") != 1 or source.count("@guarded_manual") != 1:
            raise ValueError("Incomplete voice policy adapter; inspect the installed plugin")
        return source
    changes = {
        "from __future__ import annotations\n": "from __future__ import annotations\n\n" + IMPORT,
        "    @filter.on_decorating_result(priority=-1000)\n    async def on_decorating_result(":
            "    @filter.on_decorating_result(priority=-1000)\n    @guarded_result\n    async def on_decorating_result(",
        "    async def _build_manual_tts_chain(": "    @guarded_manual\n    async def _build_manual_tts_chain(",
        "enable_probability=self.config.is_probability_output_enabled_for_umo(umo),":
            "enable_probability=self.config.is_probability_output_enabled_for_umo(umo) and not getattr(event, '_fatfish_manual_voice', False),",
    }
    for before, after in changes.items():
        if source.count(before) != 1:
            raise ValueError("Installed router interface differs from verified 3.3.3")
        source = source.replace(before, after, 1)
    compile(source, "tts_emotion_router/main.py", "exec")
    return source


def schema():
    descriptions = {
        "enabled": "Enable the voice policy (kept off until ongoing spending is authorized)",
        "voice_probability": "语音基础概率 p0（0～1，0.10表示10%），独立于群聊参与概率",
        "voice_probability_step": "每次合格但未发语音增加的概率（0～1，0.02表示2个百分点；0为固定概率）",
        "voice_probability_max": "语音概率上限（0～1，0.30表示30%）",
        "cooldown_seconds": "Per-conversation speech cooldown in seconds",
        "max_text_length": "Maximum reply characters eligible for speech",
        "manual_trigger": "Explicit speech requests bypass probability, retain cooldown and economy gates",
        "fallback_to_text": "Preserve the generated text if speech synthesis or sending fails",
        "text_alongside_voice": "Send the existing reply text alongside speech",
        "disable_during_economy_mode": "Skip paid speech while the existing offline/economy signal is active",
    }
    return {"type":"object", "description":"FatFish lightweight voice policy", "items":{
        key:{"type":"bool" if isinstance(value,bool) else "float" if isinstance(value,float) else "int",
             "default":value,"description":descriptions[key]}
        for key,value in DEFAULT_POLICY.items()}}


def configure(root: Path, *, apply=False, enable=False, key_file=None, clone_receipt=None, umos=()):
    directory = root / "data/plugins" / PLUGIN
    metadata = (directory / "metadata.yaml").read_text(encoding="utf-8-sig")
    if "version: 3.3.3" not in metadata or "license: MIT" not in metadata:
        raise ValueError("Requires the inspected MIT router version 3.3.3; review upstream changes first")
    source_path = directory / "main.py"
    source = patch_source(source_path.read_text(encoding="utf-8-sig"))
    schema_path = directory / "_conf_schema.json"
    definitions = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    definitions["fatfish_policy"] = schema()
    config_path = root / "data/config" / (PLUGIN + "_config.json")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    config["fatfish_policy"] = {**DEFAULT_POLICY, **config.get("fatfish_policy", {})}
    # Enabling automatic paid requests is a separate deliberate CLI action.
    config["fatfish_policy"]["enabled"] = bool(enable)
    cfg = config["fatfish_policy"]
    config.setdefault("probability", {})["prob"] = cfg["voice_probability"]
    config["cooldown"] = cfg["cooldown_seconds"]
    config["text_limit"] = cfg["max_text_length"]
    config.setdefault("segmented_tts", {})["enable"] = False
    config.setdefault("emotion_route", {}).setdefault("marker", {})["enable"] = False
    policies = config.setdefault("feature_policies", {})
    policies.setdefault("voice_output", {})["enable"] = cfg["enabled"]
    if umos:
        if any(not re.fullmatch(r"[^:\s]+:(?:GroupMessage|FriendMessage):\d+", value) for value in umos):
            raise ValueError("Voice scope requires complete QQ conversation identifiers")
        output_policy = policies["voice_output"]
        output_policy["mode"] = "whitelist"
        output_policy["enabled_umos"] = sorted(set(output_policy.get("enabled_umos", [])) | set(umos))
    policies.setdefault("text_voice_output", {})["enable"] = cfg["text_alongside_voice"]
    policies.setdefault("segmented_output", {})["enable"] = False
    policies.setdefault("probability_output", {})["enable"] = True
    policies.setdefault("llm_tool", {})["enable"] = False
    config.setdefault("tts_engine", {})["max_retries"] = 0
    extra = {}
    if bool(key_file) != bool(clone_receipt):
        raise ValueError("Provide the local key file and successful clone receipt together")
    if clone_receipt:
        from scripts.prepare_minimax_voice import read_key
        clone = json.loads(Path(clone_receipt).read_text(encoding="utf-8-sig"))
        if clone.get("clone_state") != "accepted" or not clone.get("authorized"):
            raise ValueError("An authorized successful clone receipt is required")
        engine = config["tts_engine"]
        engine.update(provider="minimax", timeout=120, max_retries=0)
        engine.setdefault("minimax", {}).update(url="https://api.minimax.cn/v1/t2a_v2", key=read_key(Path(key_file)),
            voice_id=clone["voice_id"], model="speech-2.8-hd", speed=1.0, vol=1.0, pitch=0,
            audio_format="mp3", sample_rate=32000, channel=1, output_format="hex",
            emotion="neutral", aigc_watermark=True)
        # Existing emotion maps belong to the previous engine. Keep them for
        # rollback, but use the new provider's default voice until reviewed.
        config.setdefault("emotion_route", {})["enable"] = False
        main_path = root / "data/cmd_config.json"
        main = json.loads(main_path.read_text(encoding="utf-8-sig"))
        main.setdefault("provider_tts_settings", {})["enable"] = False
        extra[main_path] = json.dumps(main, ensure_ascii=False, indent=2) + "\n"
        voice_path = root / "data/plugin_data/astrbot_plugin_fatfish_voice/minimax-voice.json"
        extra[voice_path] = json.dumps({"voice_id":clone["voice_id"], "model":"speech-2.8-hd",
            "clone_accepted":True,"reference_sha256":clone["sha256"],"speed":1.0},indent=2) + "\n"
    pending = {source_path:source,
               schema_path:json.dumps(definitions,ensure_ascii=False,indent=2)+"\n",
               config_path:json.dumps(config,ensure_ascii=False,indent=2)+"\n", **extra}
    changed = [path for path, text in pending.items() if not path.exists() or path.read_text(encoding="utf-8-sig") != text]
    backup = root / "data/private-config-backups" / datetime.now().strftime("%Y%m%d-voice-policy-%H%M%S-%f")
    if apply:
        for path in changed:
            if path.exists():
                target = backup / path.relative_to(root / "data")
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target)
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".voice-policy.tmp")
            temporary.write_text(pending[path],encoding="utf-8")
            temporary.replace(path)
            assert path.read_text(encoding="utf-8") == pending[path]
    return {"applied":apply,"enabled":cfg["enabled"],"changed_files":[str(p.relative_to(root)) for p in changed],
            "backup_created":backup.exists(),"upstream":"muyouzhi6/astrbot_plugin_tts_emotion_router@3.3.3 (MIT)"}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot",type=Path,required=True)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--key-file",type=Path)
    parser.add_argument("--clone-receipt",type=Path)
    parser.add_argument("--umo",action="append",default=[],help="Explicit complete QQ session to allow")
    parser.add_argument("--enable",action="store_true",help="Enable ongoing automatic TTS only after its spending policy is authorized")
    args=parser.parse_args()
    print(json.dumps(configure(args.astrbot,apply=args.apply,enable=args.enable,
        key_file=args.key_file,clone_receipt=args.clone_receipt,umos=args.umo),ensure_ascii=False))
