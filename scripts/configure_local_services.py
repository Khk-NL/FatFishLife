"""Apply local service credentials without printing or copying them into the repo."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        name, sep, value = line.partition("=")
        if not sep:
            raise ValueError("Invalid environment assignment")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def configure(env_file: Path, astrbot: Path, *, apply: bool = False) -> dict:
    env = read_env(env_file)
    data = astrbot / "data"
    pending = []
    for key in ("FATFISH_DEEPSEEK_KEY", "FATFISH_SILICONFLOW_KEY", "FATFISH_ANYSEARCH_KEY",
                "FATFISH_BILI_OWNER_UID", "FATFISH_STUDY_TAGS"):
        if not env.get(key):
            raise ValueError("Missing setting: " + key)
    configs: dict[Path, dict] = {}

    def load(name: str) -> dict:
        path = data / name
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        configs[path] = cfg
        return cfg

    main = load("cmd_config.json")
    matched = set()
    for source in main.get("provider_sources", []):
        if source.get("provider") == "deepseek":
            source["key"] = [env["FATFISH_DEEPSEEK_KEY"]]
            matched.add("deepseek")
        elif source.get("provider") == "siliconflow":
            source["key"] = [env["FATFISH_SILICONFLOW_KEY"]]
            if source.get("provider_type") == "embedding":
                source["embedding_api_key"] = env["FATFISH_SILICONFLOW_KEY"]
            matched.add("siliconflow")
    if matched != {"deepseek", "siliconflow"}:
        raise ValueError("Existing DeepSeek and SiliconFlow provider sources are required")
    for provider in main.get("provider", []):
        if provider.get("id") == "siliconflow_stt" or provider.get("type") == "fatfish_siliconflow_tts":
            provider["api_key"] = env["FATFISH_SILICONFLOW_KEY"]
    anysearch = load("config/astrbot_plugin_anysearch_config.json")
    anysearch["api_key"] = env["FATFISH_ANYSEARCH_KEY"]
    bili = load("config/astrbot_plugin_fatfish_bili_config.json")
    bili["owner_uid"] = env["FATFISH_BILI_OWNER_UID"]
    if env.get("FATFISH_QQ_OWNER"):
        bili["owner_qq"] = env["FATFISH_QQ_OWNER"]
    bili["study_tags"] = env["FATFISH_STUDY_TAGS"]
    bili["study_time"] = env.get("FATFISH_STUDY_TIME") or bili.get("study_time", "21:00")
    datetime.strptime(bili["study_time"], "%H:%M")
    bili["study_top_n"] = int(env.get("FATFISH_STUDY_TOP_N") or bili.get("study_top_n", 3))
    if not 1 <= bili["study_top_n"] <= 20:
        raise ValueError("study_top_n must be between 1 and 20")
    bili["study_enabled"] = True
    router = load("config/astrbot_plugin_tts_emotion_router_config.json")
    silicon = router["tts_engine"]["siliconflow"]
    silicon["key"] = env["FATFISH_SILICONFLOW_KEY"]
    # Preserve a subsequently installed custom voice on repeat configuration.
    if silicon.get("model") in (None, "", "gpt-tts-pro"):
        silicon["model"] = "FunAudioLLM/CosyVoice2-0.5B"
    if not silicon.get("default_voice"):
        silicon["default_voice"] = "FunAudioLLM/CosyVoice2-0.5B:diana"
    silicon["format"] = "mp3"
    vault = env.get("FATFISH_OBSIDIAN_VAULT", "")
    if vault and Path(vault).is_dir():
        obsidian = load("config/astrbot_plugin_obsidian_sync_config.json")
        obsidian.update(obsidian_dir=str(Path(vault).resolve()), kb_name="FatFish-Obsidian-Private",
                        kb_file_id="fatfish_obsidian_private", restrict_commands=True)
        if env.get("FATFISH_QQ_OWNER"):
            obsidian["admin_user_ids"] = [env["FATFISH_QQ_OWNER"]]
        # The installed legacy importer must be validated before it runs.
        obsidian["sync_on_startup"] = False
        obsidian["sync_now_request"] = False
    else:
        pending.append("obsidian_vault")
    changed = [path for path, cfg in configs.items()
               if json.loads(path.read_text(encoding="utf-8-sig")) != cfg]
    backup = None
    if apply and changed:
        backup = data / "private-config-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        for path in changed:
            saved = backup / path.relative_to(data)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(configs[path], stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(tmp, path)
            finally:
                Path(tmp).unlink(missing_ok=True)
        # Verify every committed setting from disk, without returning secret values.
        if any(json.loads(path.read_text(encoding="utf-8")) != configs[path] for path in changed):
            raise RuntimeError("Configuration readback mismatch")
    return {"applied": apply, "changed_files": [str(p.relative_to(data)) for p in changed],
            "pixiv": "preserved", "backup_created": backup is not None, "pending": pending}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--astrbot", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(configure(args.env_file, args.astrbot, apply=args.apply), ensure_ascii=True))


if __name__ == "__main__":
    main()
