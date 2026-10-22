"""Render the existing calibrated character layers with the fixed face source."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

from fatfish_video.renderer import RenderError, find_tools


ROOT = Path(__file__).resolve().parent.parent
FACE_SOURCE = ROOT / "assets/originals/kobe-original.png"
FACE_CROP = ROOT / "assets/web/kobe-face.json"


class CollageError(RuntimeError):
    pass


def prepare_character(entry: dict, config_path: Path) -> Path:
    """Reuse the Web editor's calibrated layers; the face remains the top layer."""
    preset = entry.get("front")
    if not isinstance(preset, dict):
        raise CollageError(f"角色 {entry['name']} 尚无校准的正面模型，不能自动贴脸；请改选银狼、卡芙卡、刃或仙舟三月七")
    base = ROOT / str(preset["base"]).lstrip("/")
    hair = ROOT / str(preset["hair"]).lstrip("/")
    for path in (base, hair, FACE_SOURCE, FACE_CROP):
        if not path.is_file():
            raise CollageError(f"自动拼贴素材缺失：{path}")
    crop = json.loads(FACE_CROP.read_text(encoding="utf-8"))
    left, top, crop_width, crop_height = crop["crop"]
    width, height = preset["size"]
    x, y, face_width, face_height = preset["face"]
    # Match the Web editor: cover the calibrated face hole and preserve face ratio.
    ratio = crop_width / crop_height
    face_height = max(face_height * height * 1.04, face_width * width * 1.04 / ratio)
    face_width = face_height * ratio
    out_width, out_height = max(2, round(face_width)), max(2, round(face_height))
    face_x, face_y = round(x * width - out_width / 2), round(y * height - out_height / 2)
    folder = config_path.with_suffix(".assets")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{entry['id']}-{uuid4().hex[:12]}.png"
    alpha = "255*clip((1-hypot((X-W/2)/(W/2),(Y-H/2)/(H/2)))/0.05,0,1)"
    filters = (
        "[0:v][1:v]overlay=0:0:format=auto[role];"
        f"[2:v]crop={crop_width}:{crop_height}:{left}:{top},scale={out_width}:{out_height},"
        f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'[face];"
        f"[role][face]overlay={face_x}:{face_y}:format=auto,format=rgba[out]"
    )
    try:
        ffmpeg, _ = find_tools()
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(base), "-i", str(hair), "-i", str(FACE_SOURCE), "-filter_complex", filters, "-map", "[out]", "-frames:v", "1", "-update", "1", str(destination)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (OSError, RenderError) as exc:
        raise CollageError(f"无法合成角色贴图：{exc}") from exc
    if result.returncode:
        destination.unlink(missing_ok=True)
        raise CollageError("角色贴图合成失败：" + "\n".join(result.stderr.splitlines()[-8:]))
    return destination
