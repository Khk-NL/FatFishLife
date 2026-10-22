"""Turn a topic into a validated video project config.

The pipeline never edits media and never publishes anything. It only asks a
model for a storyboard, normalizes it against the engine's constraints, writes
``schema_version: 1`` JSON, and lets ``load_project`` reject anything invalid.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from fatfish_video.project import TEMPLATES, ProjectError, load_project

from .client import Provider, ProviderError, build_provider
from .options import GeneratedProject, StoryOptions

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "assets/characters/catalog.json"
DEFAULT_MUSIC = ROOT / "assets/music/demo-original.wav"
CAPTION_LIMIT = 36
MIN_SCENE = 3.0
MAX_SCENE = 15.0
MAX_SCENES = 8
PROMPT_VERSION = "story-v1"


class StoryError(RuntimeError):
    pass


SYSTEM_PROMPT = f"""你是「大肥鱼」的短视频分镜编剧。只输出一个 JSON 对象，不要解释、不要 Markdown。

输出结构：
{{
  "title": "不超过 20 字的标题",
  "template": "single | dialogue | news",
  "scenes": [
    {{"duration": 7.5, "characters": ["1001"], "caption": "一条不超过 36 字的字幕", "zoom": 0.015}}
  ],
  "music": {{"speed": 1.25, "volume": 0.65}}
}}

规则：
1. 总时长接近用户要求，误差不超过 1 秒；每个场景 3～15 秒。
2. 字幕口语化、有梗、一口气能读完，不超过 36 个汉字，不加引号和表情。
3. single 用 1 个角色；dialogue 用 1～2 个角色；news 用 1 个角色并需要配图。
4. characters 只能从给定角色表里选 ID 或名字，不要编造。
5. 不使用任何私人聊天内容，只根据话题和公开信息写作。
6. 文案面向 B 站观众，避免人身攻击、歧视、违规内容和具体政治敏感表达。
7. zoom 取 0 到 0.03，通常 0.015。
"""


def _catalog() -> list[dict]:
    if not CATALOG_PATH.is_file():
        raise StoryError("角色库缺失：先执行 python scripts/sync_characters.py")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    entries = data.get("characters")
    if not isinstance(entries, list) or not entries:
        raise StoryError("角色库为空，无法选角")
    return entries


def _character_table(entries: list[dict]) -> str:
    return "、".join(f'{item["id"]} {item["name"]}' for item in entries)


def _match_character(value: str, entries: list[dict]) -> dict | None:
    key = re.sub(r"[（(].*?[)）]", "", str(value)).strip().lower()
    for item in entries:
        keys = {str(item.get("id", "")).lower(), str(item.get("name", "")).lower(), str(item.get("tag", "")).lower()}
        if key in keys:
            return item
    for item in entries:
        if key and (key in str(item.get("name", "")).lower() or str(item.get("name", "")).lower() in key):
            return item
    return None


def _visible_length(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text) // 2


def _split_caption(text: str, limit: int = CAPTION_LIMIT) -> list[str]:
    text = " ".join(str(text).split())
    if _visible_length(text) <= limit:
        return [text]
    pieces: list[str] = []
    buffer = ""
    for char in text:
        if buffer and _visible_length(buffer + char) > limit:
            cut = max(buffer.rfind("，"), buffer.rfind("。"), buffer.rfind("！"), buffer.rfind("？"), buffer.rfind("；"))
            if cut >= limit // 2:
                pieces.append(buffer[: cut + 1].strip())
                buffer = buffer[cut + 1 :]
            else:
                pieces.append(buffer.strip())
                buffer = ""
        buffer += char
    if buffer.strip():
        pieces.append(buffer.strip())
    return [piece for piece in pieces if piece]


def _fit_durations(durations: list[float], target: float, fps: int) -> list[float]:
    count = len(durations)
    if not MIN_SCENE * count - 0.001 <= target <= MAX_SCENE * count + 0.001:
        raise StoryError(f"{count} 个场景无法凑出 {target:g} 秒；请调整场景数或目标时长")
    clamped = [min(MAX_SCENE, max(MIN_SCENE, float(value))) for value in durations]
    total = sum(clamped)
    scale = target / total
    scaled = [min(MAX_SCENE, max(MIN_SCENE, value * scale)) for value in clamped]
    frames = [max(1, round(value * fps)) for value in scaled]
    target_frames = round(target * fps)
    delta = target_frames - sum(frames)
    order = sorted(range(count), key=lambda index: frames[index], reverse=True)
    guard = 0
    while delta and guard < 10000:
        changed = False
        for index in order:
            if delta == 0:
                break
            step = 1 if delta > 0 else -1
            candidate = frames[index] + step
            if MIN_SCENE * fps - 0.001 <= candidate <= MAX_SCENE * fps + 0.001:
                frames[index] = candidate
                delta -= step
                changed = True
        if not changed:
            break
        guard += 1
    return [round(value / fps, 4) for value in frames]


def _scene_duration(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (value > 0):
        raise StoryError(f"{label}.duration 必须是正数")
    return float(value)


def _build_config(raw: dict, options: StoryOptions, entries: list[dict], config_path: Path) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raise StoryError("模型返回的不是 JSON 对象")
    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, list) or not 1 <= len(scenes_raw) <= MAX_SCENES:
        raise StoryError(f"scenes 必须是 1～{MAX_SCENES} 个场景的数组")

    template = raw.get("template") or options.template or "single"
    if template not in TEMPLATES:
        raise StoryError(f"未知模板：{template}")
    if options.template:
        template = options.template

    requested = [_scene_duration(scene.get("duration"), f"scenes[{index}]") for index, scene in enumerate(scenes_raw)]
    durations = _fit_durations(requested, options.duration, 30)

    preferred = list(options.characters)
    assets: dict[str, dict] = {}
    scenes: list[dict] = []
    for index, (scene_raw, duration) in enumerate(zip(scenes_raw, durations)):
        if not isinstance(scene_raw, dict):
            raise StoryError(f"scenes[{index}] 必须是对象")
        names = scene_raw.get("characters")
        if names is None:
            names = preferred or ["1001"]
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or not names:
            raise StoryError(f"scenes[{index}].characters 不能为空")
        resolved = []
        for name in names:
            entry = _match_character(str(name), entries)
            if entry is None and preferred:
                entry = _match_character(preferred[0], entries)
                warnings.append(f"角色 {name} 不在角色库，已改用 {entry['name'] if entry else '默认角色'}")
            if entry is None:
                raise StoryError(f"角色 {name} 不在角色库，请重试")
            resolved.append(entry)
        limit = len(TEMPLATES[template]["roles"])
        resolved = resolved[:limit]
        for entry in resolved:
            key = f"char{entry['id']}"
            if key not in assets:
                preview = ROOT / str(entry.get("preview") or entry.get("icon")).lstrip("/")
                if not preview.is_file():
                    icon = ROOT / str(entry.get("icon", "")).lstrip("/")
                    if not icon.is_file():
                        raise StoryError(f"角色 {entry['name']} 缺少本地图片，请同步角色库")
                    preview = icon
                assets[key] = {"path": _relative(preview, config_path.parent)}

        caption = scene_raw.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            raise StoryError(f"scenes[{index}].caption 不能为空")
        pieces = _split_caption(caption)
        zoom = scene_raw.get("zoom", 0.015)
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not 0 <= zoom <= 0.10:
            zoom = 0.015
        item = {
            "duration": duration,
            "roles": [f"char{entry['id']}" for entry in resolved],
            "zoom": round(float(zoom), 4),
        }
        if len(pieces) == 1:
            item["caption"] = pieces[0]
        else:
            step = duration / len(pieces)
            item["captions"] = [
                {"start": round(index * step, 4), "end": round((index + 1) * step, 4), "text": piece}
                for index, piece in enumerate(pieces)
            ]
        if template == "news" and options.panel:
            item["panel"] = "panel"
        scenes.append(item)

    if template == "news" and not options.panel:
        warnings.append("news 模板没有配图，已降级为 single")
        template = "single"

    if options.panel:
        panel = Path(options.panel).resolve()
        if not panel.is_file():
            raise StoryError(f"配图不存在：{panel}")
        assets["panel"] = {"path": _relative(panel, config_path.parent)}

    music_raw = raw.get("music") if isinstance(raw.get("music"), dict) else {}
    speed = music_raw.get("speed", 1.25)
    volume = music_raw.get("volume", 0.65)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.5 <= speed <= 2:
        speed = 1.25
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1.5:
        volume = 0.65
    music = {
        "path": _relative(DEFAULT_MUSIC, config_path.parent),
        "speed": round(float(speed), 3),
        "pitch": "follow_speed",
        "volume": round(float(volume), 3),
        "loop": True,
        "fade_in": 0.3,
        "fade_out": 0.7,
    }

    title = str(raw.get("title") or options.topic).strip()[:40] or "未命名视频"
    output = options.output or config_path.with_suffix(".mp4")
    config = {
        "schema_version": 1,
        "title": title,
        "canvas": {"width": 1920, "height": 1080, "fps": 30, "background": "#5AA6CF"},
        "template": template,
        "assets": assets,
        "music": music,
        "scenes": scenes,
        "output": _relative(Path(output).resolve(), config_path.parent),
    }
    return config, warnings


def _relative(path: Path, base: Path) -> str:
    import os

    path = Path(path).resolve()
    base = Path(base).resolve()
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        try:
            return Path(os.path.relpath(path, base)).as_posix()
        except ValueError:
            # Different drives on Windows: keep an absolute path, the loader
            # accepts it and never rewrites the source media.
            return path.as_posix()


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text).strip("-")
    return cleaned[:24] or "topic"


def generate_project(options: StoryOptions, provider: Provider | None = None) -> GeneratedProject:
    if not options.topic.strip():
        raise StoryError("topic 不能为空")
    if options.duration < MIN_SCENE or options.duration > MAX_SCENE * MAX_SCENES:
        raise StoryError(f"目标时长应在 {MIN_SCENE:g}～{MAX_SCENE * MAX_SCENES:g} 秒")
    entries = _catalog()
    provider = provider or build_provider(options.provider, options.model, ROOT)
    config_dir = Path(options.config_dir or ROOT / "outputs/generated").resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    config_path = Path(options.config_path).resolve() if options.config_path else config_dir / f"{stamp}-{_slug(options.topic)}.json"

    user_prompt = (
        f"话题：{options.topic}\n"
        f"目标总时长：{options.duration:g} 秒\n"
        f"指定模板：{options.template or '由你选择'}\n"
        f"指定角色：{', '.join(options.characters) if options.characters else '由你选择'}\n"
        f"风格：{options.tone}\n"
        f"可用角色：{_character_table(entries)}"
    )
    started = time.monotonic()
    feedback = ""
    last_error: Exception | None = None
    for attempt in range(1, max(1, options.max_attempts) + 1):
        try:
            raw = provider.complete_json(SYSTEM_PROMPT, user_prompt + feedback)
            config, warnings = _build_config(raw, options, entries, config_path)
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                project = load_project(config_path)
            except ProjectError as exc:
                config_path.unlink(missing_ok=True)
                raise StoryError(f"生成的配置未通过引擎校验：{exc}") from exc
            metadata = {
                "schema_version": 1,
                "status": "completed",
                "provider": getattr(provider, "name", "unknown"),
                "model": options.model,
                "prompt_version": PROMPT_VERSION,
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "topic": options.topic,
                "target_duration": options.duration,
                "warnings": warnings,
            }
            meta_path = config_path.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return GeneratedProject(project, config, config_path, metadata)
        except (StoryError, ProjectError) as exc:
            last_error = exc
            feedback = f"\n\n上一次输出未通过校验：{exc}。请修正后重新输出完整 JSON。"
        except ProviderError as exc:
            raise StoryError(str(exc)) from exc
    raise StoryError(f"生成失败（{options.max_attempts} 次）：{last_error}")
