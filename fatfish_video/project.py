"""Versioned JSON input shared by the CLI and future AstrBot integration."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProjectError(ValueError):
    pass


Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Asset:
    path: Path
    crop: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class Placement:
    asset: str
    box: Box | None = None


@dataclass(frozen=True)
class Caption:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Scene:
    template: str
    frames: int
    roles: tuple[Placement, ...]
    panel: Placement | None
    captions: tuple[Caption, ...]
    zoom: float


@dataclass(frozen=True)
class Music:
    path: Path
    speed: float = 1.0
    pitch: str = "follow_speed"
    volume: float = 0.35
    start: float = 0.0
    loop: bool = True
    fade_in: float = 0.3
    fade_out: float = 0.7


@dataclass(frozen=True)
class Project:
    source: Path
    title: str
    width: int
    height: int
    fps: int
    background: str
    assets: dict[str, Asset]
    scenes: tuple[Scene, ...]
    music: Music | None
    font: Path | None
    font_name: str | None
    font_size: int
    output: Path

    @property
    def frames(self) -> int:
        return sum(scene.frames for scene in self.scenes)

    @property
    def duration(self) -> float:
        return self.frames / self.fps


TEMPLATES = {
    "single": {
        "roles": ((0.28, 0.06, 0.44, 0.83),),
        "panel": (0.04, 0.04, 0.28, 0.30),
    },
    "dialogue": {
        "roles": ((0.035, 0.19, 0.43, 0.70), (0.535, 0.19, 0.43, 0.70)),
        "panel": (0.30, 0.035, 0.40, 0.30),
    },
    "news": {
        "roles": ((0.65, 0.18, 0.32, 0.72),),
        "panel": (0.035, 0.065, 0.59, 0.68),
    },
}


def _object(value: Any, label: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ProjectError(f"{label} 必须是对象")
    unknown = set(value) - allowed
    if unknown:
        raise ProjectError(f"{label} 含未知字段：{', '.join(sorted(unknown))}")
    return value


def _number(value: Any, label: str, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProjectError(f"{label} 必须是有限数字")
    if value < minimum or (maximum is not None and value > maximum):
        raise ProjectError(f"{label} 超出范围：{minimum} ～ {maximum or '不限'}")
    return float(value)


def _integer(value: Any, label: str, minimum: int, maximum: int | None = None) -> int:
    number = _number(value, label, minimum, maximum)
    if not number.is_integer():
        raise ProjectError(f"{label} 必须是整数")
    return int(number)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProjectError(f"{label} 必须是非空文本")
    return value


def _file(value: Any, base: Path, label: str) -> Path:
    path = (base / _text(value, label)).resolve()
    if not path.is_file():
        raise ProjectError(f"{label} 文件不存在：{path}")
    return path


def _placement(value: Any, assets: dict[str, Asset], label: str) -> Placement:
    data = {"asset": value} if isinstance(value, str) else _object(value, label, {"asset", "box"})
    asset = _text(data.get("asset"), f"{label}.asset")
    if asset not in assets:
        raise ProjectError(f"{label} 引用了不存在的素材：{asset}")
    box = data.get("box")
    if box is not None:
        if not isinstance(box, list) or len(box) != 4:
            raise ProjectError(f"{label}.box 应为 [x, y, width, height]，使用 0～1 相对坐标")
        box = tuple(_number(v, f"{label}.box", 0, 1) for v in box)
        x, y, width, height = box
        if width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
            raise ProjectError(f"{label}.box 必须有正面积且位于画布内")
    return Placement(asset, box)


def load_project(path: str | Path) -> Project:
    source = Path(path).resolve()
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"无法读取项目 {source}：{exc}") from exc
    data = _object(data, "项目", {"schema_version", "title", "canvas", "assets", "template", "scenes", "music", "subtitles", "output"})
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ProjectError("schema_version 必须为 1")
    base = source.parent
    canvas = _object(data.get("canvas", {}), "canvas", {"width", "height", "fps", "background"})
    width = _integer(canvas.get("width", 1920), "canvas.width", 320)
    height = _integer(canvas.get("height", 1080), "canvas.height", 180)
    if width % 2 or height % 2:
        raise ProjectError("H.264 输出的宽高必须为偶数")
    fps = _integer(canvas.get("fps", 30), "canvas.fps", 1, 120)
    background = canvas.get("background", "#5AA6CF")
    if not isinstance(background, str) or len(background) != 7 or background[0] != "#":
        raise ProjectError("canvas.background 必须为 #RRGGBB")
    try:
        int(background[1:], 16)
    except ValueError as exc:
        raise ProjectError("canvas.background 必须为 #RRGGBB") from exc

    raw_assets = data.get("assets")
    if not isinstance(raw_assets, dict) or not raw_assets:
        raise ProjectError("assets 必须包含至少一个素材")
    assets = {}
    for key, value in raw_assets.items():
        _text(key, "素材 ID")
        spec = {"path": value} if isinstance(value, str) else _object(value, f"assets.{key}", {"path", "crop"})
        asset_path = _file(spec.get("path"), base, f"assets.{key}.path")
        if asset_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            raise ProjectError(f"素材 {key} 需要 PNG/JPEG/WebP/BMP 静态图片")
        crop = spec.get("crop")
        if crop is not None:
            if not isinstance(crop, list) or len(crop) != 4:
                raise ProjectError(f"assets.{key}.crop 应为像素 [x, y, width, height]")
            crop = tuple(_integer(v, f"assets.{key}.crop", 0 if i < 2 else 1) for i, v in enumerate(crop))
        assets[key] = Asset(asset_path, crop)

    default_template = data.get("template", "single")
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ProjectError("scenes 必须包含至少一个场景")
    scenes = []
    for index, raw in enumerate(raw_scenes):
        label = f"scenes[{index}]"
        scene = _object(raw, label, {"template", "duration", "roles", "panel", "caption", "captions", "zoom"})
        template = scene.get("template", default_template)
        if not isinstance(template, str) or template not in TEMPLATES:
            raise ProjectError(f"{label}.template 应为 single、dialogue 或 news")
        requested_duration = _number(scene.get("duration"), f"{label}.duration", 1 / fps)
        frames = round(requested_duration * fps)
        duration = frames / fps
        roles = scene.get("roles")
        if not isinstance(roles, list) or not 1 <= len(roles) <= len(TEMPLATES[template]["roles"]):
            raise ProjectError(f"{label}.roles 与模板 {template} 的角色数量不匹配")
        placements = tuple(_placement(role, assets, f"{label}.roles") for role in roles)
        panel = _placement(scene["panel"], assets, f"{label}.panel") if scene.get("panel") is not None else None
        if template == "news" and panel is None:
            raise ProjectError(f"{label} 的 news 模板需要 panel 配图")
        if "caption" in scene and "captions" in scene:
            raise ProjectError(f"{label} 的 caption 和 captions 只能选择一个")
        cues = []
        if "caption" in scene:
            cues.append(Caption(_text(scene["caption"], f"{label}.caption"), 0.0, duration))
        elif "captions" in scene:
            if not isinstance(scene["captions"], list):
                raise ProjectError(f"{label}.captions 必须是数组")
            last_end = 0.0
            for cue_raw in scene["captions"]:
                cue = _object(cue_raw, f"{label}.captions", {"text", "start", "end"})
                start = round(_number(cue.get("start"), "字幕 start", 0, requested_duration) * fps) / fps
                end = round(_number(cue.get("end"), "字幕 end", 0, requested_duration) * fps) / fps
                if end <= start or start < last_end:
                    raise ProjectError(f"{label} 字幕应按时间排序、不可重叠，end 必须大于 start")
                cues.append(Caption(_text(cue.get("text"), "字幕 text"), start, end))
                last_end = end
        zoom = _number(scene.get("zoom", 0.015), f"{label}.zoom", 0, 0.10)
        scenes.append(Scene(template, frames, placements, panel, tuple(cues), zoom))

    music = None
    if data.get("music") is not None:
        spec = _object(data["music"], "music", {"path", "speed", "pitch", "volume", "start", "loop", "fade_in", "fade_out"})
        pitch = spec.get("pitch", "follow_speed")
        if pitch not in ("follow_speed", "preserve"):
            raise ProjectError("music.pitch 应为 follow_speed（随加速升调）或 preserve（保调）")
        loop = spec.get("loop", True)
        if type(loop) is not bool:
            raise ProjectError("music.loop 必须是布尔值")
        music = Music(
            _file(spec.get("path"), base, "music.path"),
            _number(spec.get("speed", 1), "music.speed", 0.5, 2), pitch,
            _number(spec.get("volume", 0.35), "music.volume", 0, 2),
            _number(spec.get("start", 0), "music.start", 0), loop,
            _number(spec.get("fade_in", 0.3), "music.fade_in", 0),
            _number(spec.get("fade_out", 0.7), "music.fade_out", 0),
        )
    subtitles = _object(data.get("subtitles", {}), "subtitles", {"font", "font_name", "font_size"})
    font = _file(subtitles["font"], base, "subtitles.font") if "font" in subtitles else None
    font_name = _text(subtitles["font_name"], "subtitles.font_name") if "font_name" in subtitles else None
    if font is not None and font_name is None:
        raise ProjectError("自定义 subtitles.font 时也需要指定 subtitles.font_name 字体家族名")
    if font_name and any(c in font_name for c in ",\r\n"):
        raise ProjectError("subtitles.font_name 不可含逗号或换行")
    output = (base / _text(data.get("output", f"{source.stem}.mp4"), "output")).resolve()
    if output.suffix.lower() != ".mp4":
        raise ProjectError("output 必须是 .mp4 文件")
    return Project(
        source, _text(data.get("title", source.stem), "title"), width, height, fps,
        background, assets, tuple(scenes), music, font, font_name,
        _integer(subtitles.get("font_size", round(height * 64 / 1080)), "subtitles.font_size", 8, height // 4),
        output,
    )
