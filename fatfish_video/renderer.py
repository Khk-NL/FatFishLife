"""FFmpeg compositor. No web services, model keys or global mutable state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .project import Project, ProjectError, Scene, TEMPLATES, load_project


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderResult:
    video: Path
    cover: Path
    subtitles: Path
    report: Path
    duration: float
    frames: int
    width: int
    height: int
    fps: int
    has_music: bool

    def as_dict(self) -> dict:
        return {key: str(value) if isinstance(value, Path) else value for key, value in vars(self).items()}


def _resolve_tool(name: str, explicit: str | Path | None = None) -> Path:
    configured = explicit or os.environ.get(f"FATFISH_{name.upper()}")
    if configured:
        resolved = Path(configured) if Path(configured).is_file() else Path(shutil.which(str(configured)) or "")
        if resolved.is_file():
            return resolved.resolve()
        raise RenderError(f"指定的 {name} 不存在：{configured}")
    candidates = [shutil.which(name)]
    suffix = ".exe" if os.name == "nt" else ""
    for root in (Path.cwd(), Path(__file__).resolve().parent.parent):
        candidates.append(root / ".tools" / "ffmpeg" / "bin" / f"{name}{suffix}")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
        if candidate and shutil.which(str(candidate)):
            return Path(shutil.which(str(candidate))).resolve()
    raise RenderError(f"找不到 {name}。将 FFmpeg 的 bin 加入 PATH，或设置 FATFISH_{name.upper()}；详见 README。")


def find_tools(ffmpeg: str | Path | None = None, ffprobe: str | Path | None = None) -> tuple[Path, Path]:
    executable = _resolve_tool("ffmpeg", ffmpeg)
    sibling = executable.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    probe = _resolve_tool("ffprobe", ffprobe or os.environ.get("FATFISH_FFPROBE") or (sibling if sibling.is_file() else None))
    return executable, probe


def find_font(project: Project | None = None) -> tuple[Path, str]:
    if project and project.font:
        if not project.font_name:
            raise ProjectError("自定义 subtitles.font 时也需要指定真实的 subtitles.font_name 字体家族名")
        return project.font, project.font_name
    candidates = [
        ("C:/Windows/Fonts/msyhbd.ttc", "Microsoft YaHei"),
        ("C:/Windows/Fonts/msyh.ttc", "Microsoft YaHei"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
    ]
    for path, name in candidates:
        if Path(path).is_file():
            return Path(path), project.font_name if project and project.font_name else name
    raise RenderError("找不到中文字体。安装 Noto Sans CJK，或在 subtitles 中指定 font 和 font_name。")


def _run(args: list[str | Path], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run([str(arg) for arg in args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RenderError(f"无法启动媒体工具：{exc}") from exc
    if result.returncode:
        tail = "\n".join(result.stderr.splitlines()[-18:])
        raise RenderError(f"{Path(args[0]).name} 执行失败（{result.returncode}）：\n{tail}")
    return result.stdout


def probe_media(path: str | Path, ffprobe: str | Path | None = None) -> dict:
    executable = _resolve_tool("ffprobe", ffprobe)
    try:
        return json.loads(_run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", Path(path).resolve()]))
    except json.JSONDecodeError as exc:
        raise RenderError("ffprobe 没有返回有效的 JSON") from exc


def _units(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def wrap_caption(text: str, max_units: int) -> str:
    """Explicit Unicode-aware line breaks; libass does not guess line length."""
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current = ""
        for char in paragraph:
            if current and _units(current + char) > max_units:
                lines.append(current.rstrip())
                current = ""
            current += char
        lines.append(current.rstrip())
    return "\n".join(lines)


def _timestamp(seconds: float, ass: bool = False) -> str:
    factor = 100 if ass else 1000
    ticks = round(seconds * factor)
    whole, remainder = divmod(ticks, factor)
    hours, rest = divmod(whole, 3600)
    minutes, seconds = divmod(rest, 60)
    if ass:
        return f"{hours}:{minutes:02}:{seconds:02}.{remainder:02}"
    return f"{hours:02}:{minutes:02}:{seconds:02},{remainder:03}"


def _ass_text(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N")


def _write_ass(project: Project, scene: Scene, path: Path, font_name: str) -> None:
    margin_x = round(project.width * 0.055)
    margin_y = round(project.height * 0.065)
    outline = max(1, round(project.height * 4 / 1080))
    max_units = max(4, int((project.width - 2 * margin_x) / project.font_size * 1.8))
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {project.width}\nPlayResY: {project.height}\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{project.font_size},&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,{margin_x},{margin_x},{margin_y},1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for caption in scene.captions:
        wrapped = wrap_caption(caption.text, max_units)
        if len(wrapped.splitlines()) > 3:
            raise ProjectError("一条字幕换行后超过 3 行；请拆成多个 captions 时间段或缩短文字。")
        events.append(f"Dialogue: 0,{_timestamp(caption.start, True)},{_timestamp(caption.end, True)},Default,,0,0,0,,{_ass_text(wrapped)}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def _write_srt(project: Project, path: Path) -> None:
    blocks = []
    offset = 0.0
    for scene in project.scenes:
        for caption in scene.captions:
            blocks.append(f"{len(blocks) + 1}\n{_timestamp(offset + caption.start)} --> {_timestamp(offset + caption.end)}\n{caption.text}\n")
        offset += scene.frames / project.fps
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


def _scene_command(project: Project, scene: Scene, index: int, ffmpeg: Path, work: Path, font_name: str) -> list:
    duration = scene.frames / project.fps
    stem = f"scene_{index:03}"
    _write_ass(project, scene, work / f"{stem}.ass", font_name)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1",
               "-f", "lavfi", "-i", f"color=c=0x{project.background[1:]}:s={project.width}x{project.height}:r={project.fps}:d={duration:.9f}"]
    layers = []
    if scene.panel:
        layers.append((scene.panel, TEMPLATES[scene.template]["panel"], False))
    for role, default_box in zip(scene.roles, TEMPLATES[scene.template]["roles"]):
        layers.append((role, default_box, True))
    filters = []
    previous = "0:v"
    for number, (placement, default_box, bottom_align) in enumerate(layers, 1):
        asset = project.assets[placement.asset]
        command += ["-loop", "1", "-framerate", str(project.fps), "-i", asset.path]
        x, y, width, height = placement.box or default_box
        x, y = round(x * project.width), round(y * project.height)
        width = max(2, int(width * project.width) // 2 * 2)
        height = max(2, int(height * project.height) // 2 * 2)
        chain = f"[{number}:v]"
        if asset.crop:
            cx, cy, cw, ch = asset.crop
            chain += f"crop={cw}:{ch}:{cx}:{cy},"
        pad_y = "oh-ih" if bottom_align else "(oh-ih)/2"
        chain += (f"format=rgba,scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                  f"pad={width}:{height}:(ow-iw)/2:{pad_y}:color=0x00000000,setsar=1[layer{number}]")
        filters.append(chain)
        filters.append(f"[{previous}][layer{number}]overlay={x}:{y}:eof_action=repeat:shortest=1[base{number}]")
        previous = f"base{number}"
    tail = f"[{previous}]format=yuv420p,"
    if scene.zoom:
        denominator = max(1, scene.frames - 1)
        tail += (f"zoompan=z='1+{scene.zoom}*on/{denominator}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                 f"d=1:s={project.width}x{project.height}:fps={project.fps},")
    tail += f"subtitles={stem}.ass:fontsdir=fonts,setsar=1,setpts=PTS-STARTPTS[outv]"
    filters.append(tail)
    command += ["-filter_complex", ";".join(filters), "-map", "[outv]", "-an", "-frames:v", str(scene.frames),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4", "-pix_fmt", "yuv420p",
                "-fps_mode", "cfr", work / f"{stem}.mp4"]
    return command


def _mux_command(project: Project, ffmpeg: Path, work: Path) -> list:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "scenes.txt"]
    music = project.music
    if music:
        if music.loop:
            command += ["-stream_loop", "-1"]
        command += ["-ss", str(music.start), "-i", music.path]
        filters = ["aresample=48000"]
        if music.pitch == "follow_speed":
            filters += [f"asetrate={48000 * music.speed:.8f}", "aresample=48000"]
        else:
            filters.append(f"atempo={music.speed}")
        filters += [f"volume={music.volume}", f"apad=whole_dur={project.duration:.9f}", f"atrim=duration={project.duration:.9f}", "asetpts=PTS-STARTPTS"]
        fade_in = min(music.fade_in, project.duration / 2)
        fade_out = min(music.fade_out, project.duration / 2)
        if fade_in:
            filters.append(f"afade=t=in:st=0:d={fade_in:.9f}")
        if fade_out:
            filters.append(f"afade=t=out:st={project.duration - fade_out:.9f}:d={fade_out:.9f}")
        command += ["-af", ",".join(filters)]
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    command += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", f"{project.duration:.9f}", "-movflags", "+faststart", "render.mp4"]
    return command


def _verify(project: Project, metadata: dict) -> None:
    videos = [stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"]
    audios = [stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "audio"]
    if not videos or not audios:
        raise RenderError("成片缺少视频轨或音轨")
    video = videos[0]
    if (video.get("width"), video.get("height")) != (project.width, project.height):
        raise RenderError("成片分辨率与配置不符")
    numerator, denominator = map(int, video["avg_frame_rate"].split("/"))
    if not denominator or abs(numerator / denominator - project.fps) > 0.001:
        raise RenderError("成片帧率与配置不符")
    if int(video.get("nb_frames", -1)) != project.frames:
        raise RenderError("成片帧数与配置不符")
    if abs(float(metadata["format"]["duration"]) - project.duration) > max(0.05, 1 / project.fps):
        raise RenderError("成片时长与字幕时间轴不符")


def render_project(
    project: Project | str | Path,
    output: str | Path | None = None,
    *,
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> RenderResult:
    """Render, inspect, then return artifacts. Failures never return a success result."""
    project = project if isinstance(project, Project) else load_project(project)
    executable, probe = find_tools(ffmpeg, ffprobe)
    font_path, font_name = find_font(project)
    target = Path(output).resolve() if output is not None else project.output
    if target.suffix.lower() != ".mp4":
        raise ProjectError("输出必须是 .mp4 文件")
    cover = target.with_suffix(".cover.jpg")
    subtitles = target.with_suffix(".srt")
    report = target.with_suffix(".result.json")
    destinations = (target, cover, subtitles, report)
    inputs = {project.source, font_path, *(asset.path for asset in project.assets.values())}
    if project.music:
        inputs.add(project.music.path)
        audio_metadata = probe_media(project.music.path, probe)
        if not any(stream.get("codec_type") == "audio" for stream in audio_metadata.get("streams", [])):
            raise ProjectError("music.path 没有可用音轨")
        source_duration = float(audio_metadata.get("format", {}).get("duration", 0))
        if source_duration <= project.music.start:
            raise ProjectError("music.start 已超过音乐时长")
    if any(path in inputs for path in destinations):
        raise ProjectError("输出会覆盖输入素材或配置，请更换输出路径")
    existing = [str(path) for path in destinations if path.exists()]
    if existing and not overwrite:
        raise RenderError("输出已存在；如需替换请传 --overwrite：" + ", ".join(existing))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Work is contained in the explicitly selected output directory. Only this
    # newly created temporary directory is cleaned up by TemporaryDirectory.
    with tempfile.TemporaryDirectory(prefix=".fatfish-render-", dir=target.parent) as directory:
        work = Path(directory).resolve()
        if work.parent != target.parent.resolve():
            raise RenderError("临时目录不在输出目录内")
        (work / "fonts").mkdir()
        shutil.copy2(font_path, work / "fonts" / font_path.name)
        for index, scene in enumerate(project.scenes):
            if progress:
                progress(f"合成场景 {index + 1}/{len(project.scenes)}（{scene.template}，{scene.frames / project.fps:.2f} 秒）")
            _run(_scene_command(project, scene, index, executable, work, font_name), work)
        (work / "scenes.txt").write_text("".join(f"file 'scene_{index:03}.mp4'\n" for index in range(len(project.scenes))), encoding="utf-8")
        if progress:
            progress("拼接场景、处理 BGM 并检查成片")
        _run(_mux_command(project, executable, work), work)
        metadata = probe_media(work / "render.mp4", probe)
        _verify(project, metadata)
        _run([executable, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(min(0.25, project.duration / 2)),
              "-i", work / "render.mp4", "-frames:v", "1", "-q:v", "2", "-update", "1", work / "cover.jpg"], work)
        _write_srt(project, work / "subtitles.srt")
        result = RenderResult(target, cover, subtitles, report, project.duration, project.frames, project.width, project.height, project.fps, project.music is not None)
        manifest = {"status": "completed", "schema_version": 1, "project": str(project.source), "title": project.title,
                    **result.as_dict(), "probe": metadata}
        (work / "result.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # All media operations succeeded before any final artifact is published.
        for name, destination in (("cover.jpg", cover), ("subtitles.srt", subtitles), ("render.mp4", target), ("result.json", report)):
            os.replace(work / name, destination)
    return result


def doctor(ffmpeg: str | Path | None = None, ffprobe: str | Path | None = None) -> dict:
    executable, probe = find_tools(ffmpeg, ffprobe)
    font, family = find_font()
    filters = _run([executable, "-hide_banner", "-filters"])
    encoders = _run([executable, "-hide_banner", "-encoders"])
    missing = [name for name in ("subtitles", "overlay", "zoompan", "asetrate", "atempo", "afade") if name not in filters]
    if "libx264" not in encoders:
        missing.append("libx264")
    if missing:
        raise RenderError("FFmpeg 缺少必要能力：" + ", ".join(missing))
    return {"ffmpeg": str(executable), "ffprobe": str(probe), "version": _run([executable, "-version"]).splitlines()[0],
            "font": str(font), "font_name": family, "ready": True}

