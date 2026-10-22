"""Loopback Web editor. Local files are uploaded only for explicit exports."""

from __future__ import annotations

import base64
import binascii
import json
import math
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlsplit
import uuid

from .project import ProjectError
from .renderer import RenderError, find_tools, render_project
from .face_crop import crop_face

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).parent / "web"
MAX_BODY = 72 * 1024 * 1024


def _number(data, key, default, minimum, maximum):
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} 应在 {minimum}～{maximum} 之间")
    return value


def _write_upload(value, destination, *, image=False):
    if not isinstance(value, dict) or not isinstance(value.get("data"), str):
        raise ValueError("缺少上传文件内容")
    content = value["data"]
    if content.startswith("data:"):
        header, content = content.split(",", 1)
        if ";base64" not in header:
            raise ValueError("上传需要 base64 编码")
    try:
        decoded = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("上传文件编码无效") from exc
    if not decoded or len(decoded) > 50 * 1024 * 1024:
        raise ValueError("文件不能为空，且不能超过 50 MB")
    if image and not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("合成图片需要 PNG 格式")
    destination.write_bytes(decoded)


def _music(data, job):
    value = data.get("music")
    if not value:
        return None
    audio = job / "music-input.bin"
    _write_upload(value, audio)
    return {"path": str(audio), "speed": _number(data, "speed", 1, 0.5, 2),
            "pitch": "preserve" if data.get("preserve_pitch", False) else "follow_speed",
            "volume": _number(data, "volume", 0.65, 0, 1.5)}


def process_export(data, kind, root=ROOT):
    """Shared HTTP/CLI-test operation. Return only generated-file URLs."""
    if not isinstance(data, dict):
        raise ValueError("请求必须是 JSON 对象")
    executable, _ = find_tools()
    identifier = uuid.uuid4().hex
    job = root / ".web-data" / identifier
    job.mkdir(parents=True)
    output = root / "outputs/web"
    output.mkdir(parents=True, exist_ok=True)
    music = _music(data, job)
    if kind == "audio":
        if music is None:
            raise ValueError("请先导入音乐")
        destination = output / f"music-{identifier}.wav"
        filters = ["aresample=48000"]
        if music["pitch"] == "preserve":
            filters.append(f"atempo={music['speed']}")
        else:
            filters += [f"asetrate={48000 * music['speed']}", "aresample=48000"]
        filters.append(f"volume={music['volume']}")
        process = subprocess.run([str(executable), "-hide_banner", "-loglevel", "error", "-y", "-i", music["path"],
                                  "-vn", "-af", ",".join(filters), "-ar", "48000", "-ac", "2", str(destination)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
        if process.returncode:
            raise RenderError("音乐导出失败：" + "\n".join(process.stderr.splitlines()[-8:]))
        return {"url": "/media/" + destination.name, "filename": destination.name}
    image = job / "character.png"
    _write_upload(data.get("image"), image, image=True)
    caption = data.get("caption", "")
    if not isinstance(caption, str) or len(caption) > 160:
        raise ValueError("字幕最多 160 字，请拆成短句测试")
    scene = {"duration": _number(data, "duration", 8, 2, 30), "roles": [{"asset": "edited", "box": [0.15, 0.025, 0.70, 0.90]}], "zoom": 0.01}
    if caption.strip():
        scene["caption"] = caption
    background = data.get("background", "#5AA6CF")
    if not isinstance(background, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise ValueError("背景颜色应为 #RRGGBB")
    project = {"schema_version": 1, "title": "Web 拼贴测试", "template": "single", "canvas": {"background": background},
               "assets": {"edited": str(image)}, "scenes": [scene], "music": music,
               "output": str(output / f"video-{identifier}.mp4")}
    source = job / "project.json"
    source.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    result = render_project(source)
    return {"url": "/media/" + result.video.name, "filename": result.video.name, "cover": "/media/" + result.cover.name,
            "duration": result.duration}


def process_face(data, root=ROOT):
    if not isinstance(data, dict):
        raise ValueError("请求必须是 JSON 对象")
    identifier = uuid.uuid4().hex
    folder = root / ".web-data" / identifier
    folder.mkdir(parents=True)
    source = folder / "face-source.bin"
    _write_upload(data.get("image"), source)
    destination = root / "outputs/web" / f"face-{identifier}.png"
    result = crop_face(source, destination)
    return {**result, "url": "/media/" + destination.name}


class EditorHandler(BaseHTTPRequestHandler):
    def _json(self, value, status=200):
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _file(self, path, base):
        path, base = path.resolve(), base.resolve()
        if not path.is_relative_to(base) or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        request_range = self.headers.get("Range")
        if request_range:
            try:
                bounds = request_range.removeprefix("bytes=").split("-", 1)
                start = int(bounds[0]) if bounds[0] else max(0, size - int(bounds[1]))
                end = min(size - 1, int(bounds[1])) if bounds[0] and bounds[1] else size - 1
                if not 0 <= start <= end < size:
                    raise ValueError
            except (ValueError, IndexError):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if request_range else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        if request_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            left = end - start + 1
            while left:
                chunk = source.read(min(left, 65536))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        if route == "/api/characters":
            catalog = ROOT / "assets/characters/catalog.json"
            if not catalog.is_file():
                self._json({"error": "角色库未准备好，请执行 python scripts/sync_characters.py"}, 503)
            else:
                self._json(json.loads(catalog.read_text(encoding="utf-8")))
        elif route.startswith("/assets/"):
            self._file(ROOT / route.lstrip("/"), ROOT / "assets")
        elif route.startswith("/media/"):
            self._file(ROOT / "outputs/web" / route.removeprefix("/media/"), ROOT / "outputs/web")
        elif route in ("/", "/index.html", "/app.js", "/styles.css"):
            self._file(WEB / ("index.html" if route == "/" else route.lstrip("/")), WEB)
        else:
            self.send_error(404)

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ("/api/export-audio", "/api/render", "/api/crop-face"):
            self.send_error(404)
            return
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self._json({"error": "仅接受本机编辑页面的请求"}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                self._json({"error": "请求为空或文件过大（最多 50 MB 文件）"}, 413)
                return
            data = json.loads(self.rfile.read(size))
            result = process_face(data) if route == "/api/crop-face" else process_export(data, "audio" if route.endswith("audio") else "video")
            self._json(result)
        except (ValueError, ProjectError, RenderError, OSError) as exc:
            self._json({"error": str(exc)}, 400)

    def log_message(self, format, *args):
        # No uploaded content or full request bodies in operational logs.
        super().log_message(format, *args)


def serve(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), EditorHandler)
    print(f"FatFishLife Web: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
