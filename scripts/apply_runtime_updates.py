"""Install the completed group-style, voice and owner-only proactive settings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil


def apply(astrbot: Path, profiles: Path, owner: str, bot: str, *, activate_voices=False):
    data = astrbot / "data"
    backup = data / "private-config-backups" / datetime.now().strftime("%Y%m%d-phase-%H%M%S")
    changed = []

    def save(relative, transform):
        path = data / relative
        cfg = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        before = json.dumps(cfg, sort_keys=True)
        transform(cfg)
        if before == json.dumps(cfg, sort_keys=True):
            return
        if path.exists():
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".phase.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        assert json.loads(path.read_text(encoding="utf-8")) == cfg
        changed.append(relative)

    voices = json.loads(profiles.read_text(encoding="utf-8"))
    # Registration results are local private voice URIs, never copied into Git.
    def native(cfg):
        for provider in cfg.get("provider", []):
            if provider.get("type") == "fatfish_siliconflow_tts":
                provider.update(voice=voices["neutral"], emotion_voices=voices, speed=1.1)

    def router(cfg):
        cfg["tts_engine"]["siliconflow"].update(default_voice=voices["neutral"], speed=1.1)
        route = cfg["emotion_route"]
        route["enable"] = True
        mapping = route.setdefault("voice_map", {})
        for emotion in set(mapping) | {"neutral", "happy", "soft"}:
            profile = "happy" if emotion in {"happy", "excited", "relieved"} else "soft" if emotion in {"soft", "sad", "weary", "gentle"} else "neutral"
            mapping[emotion] = voices[profile]

    def proactive(cfg):
        friend = cfg["friend_settings"]
        friend.update(enable=True, session_list=[f"napcat:FriendMessage:{owner}"])
        friend["auto_trigger_settings"].update(enable_auto_trigger=True, auto_trigger_after_minutes=30)
        friend["schedule_settings"].update(min_interval_minutes=180, max_interval_minutes=600,
                                           quiet_hours="23-8", max_unanswered_times=2)
        friend["proactive_prompt"] = (
            "现在是 {{current_time}}，你是苹果乐，以能天使为基础，称呼老板，爽朗有点嘴硬，偶尔装傻。"
            "根据真实聊天挑一个有趣的小事自然接话，最多两句。可以好奇、接梗、说自己的看法。"
            "不要编造上班、送货、见面、吃东西等现实经历，不强行暧昧，不催回复。"
            "之前未回复 {{unanswered_count}} 次，保持轻松，别让老板有压力。")
        cfg["group_settings"]["enable"] = False

    if activate_voices:
        save("cmd_config.json", native)
        save("config/astrbot_plugin_tts_emotion_router_config.json", router)
    save("config/astrbot_plugin_fatfish_style_config.json", lambda cfg: cfg.update(enabled=True, bot_id=bot, min_messages=10))
    save("config/astrbot_plugin_proactive_chat_config.json", proactive)
    return {"changed_files": changed, "backup_created": backup.exists()}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--astrbot", type=Path, required=True)
    p.add_argument("--voice-profiles", type=Path, required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--bot", required=True)
    p.add_argument("--activate-voices", action="store_true", help="Use only after the new voice profiles pass synthesis and listening checks")
    args = p.parse_args()
    print(json.dumps(apply(args.astrbot, args.voice_profiles, args.owner, args.bot, activate_voices=args.activate_voices)))
