"""Updream creative briefs and verified, owner-imported exported media."""
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from fatfish_video.renderer import find_tools, RenderError
from fatfish_video.validation import verify_export

BRIEF_PROMPT = """为Updream策划一部有完整叙事的明日方舟二创短片，不能用模板贴脸、幻灯片或字幕段子代替创作。
选题只使用用户提供的公开话题及有出处的设定参考，不读取或补写私人生活。
角色的目标、阻碍、选择和结果要成立；每个镜头要用表演、行动、构图、声音推进叙事。
沿用人物核心性格，避免强行暧昧、装傻口头禅堆砌。原创情节明确作为虚构二创，不能冒充官方剧情。
保持角色外貌、服装和空间连续性；把对白、镜头运动、音效和配乐分别描述。
仅返回JSON：{"title":"标题","logline":"一句话故事与冲突","characters":["角色及固定外貌"],
"visual_style":"统一画风、光线、比例","sound_plan":"对白、环境声与配乐方案",
"shots":[{"duration":6,"action":"镜头行动与表演","dialogue":"对白，可空",
"visual_prompt":"用于Updream生成的画面、构图与运动提示"}]}。
3至12个镜头，每镜头3至15秒，合计接近要求时长。不编写接口地址，不声称视频已生成。"""


def save_brief(directory: Path, topic: str, data: dict, *, owner: str, session: str) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list) or not 3 <= len(data["shots"]) <= 12:
        raise ValueError("Updream brief needs 3-12 narrative shots")
    for key in ("title", "logline", "visual_style", "sound_plan"):
        if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 1000:
            raise ValueError("Incomplete Updream creative brief")
    if not isinstance(data.get("characters"), list) or not 1 <= len(data["characters"]) <= 8 or any(
            not isinstance(c, str) or not c.strip() or len(c) > 500 for c in data["characters"]):
        raise ValueError("Missing consistent character design")
    for shot in data["shots"]:
        if not isinstance(shot, dict) or type(shot.get("duration")) not in (int, float) or not 3 <= shot["duration"] <= 15:
            raise ValueError("Invalid shot duration")
        for key in ("action", "dialogue", "visual_prompt"):
            if not isinstance(shot.get(key), str) or len(shot[key]) > 1500 or (key != "dialogue" and not shot[key].strip()):
                raise ValueError("Incomplete narrative shot")
    job_id = uuid4().hex[:12]
    folder = directory / job_id
    folder.mkdir(parents=True, exist_ok=False)
    row = {"id": job_id, "engine": "updream", "status": "awaiting_updream", "owner": owner, "session": session,
           "topic": topic, "brief": data, "uploaded": False, "generated": False, "published": False}
    (folder / "job.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# " + data["title"], data["logline"], "", "角色：" + "；".join(data["characters"]),
             "画风：" + data["visual_style"], "声音：" + data["sound_plan"], ""]
    for index, shot in enumerate(data["shots"], 1):
        lines.extend([f"## 镜头{index} · {shot['duration']}秒", shot["action"], "对白：" + shot["dialogue"],
                      "画面提示：" + shot["visual_prompt"], ""])
    (folder / "creative-brief.md").write_text("\n".join(lines), encoding="utf-8")
    return {**row, "path": str(folder / "creative-brief.md")}


def import_export(video: Path, directory: Path) -> dict:
    """Keep a review copy; source is declared by the owner, decoding is verified here."""
    if not video.is_file():
        raise FileNotFoundError("Updream export file does not exist")
    folder = directory / uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=False)
    target = folder / "updream.mp4"
    shutil.copy2(video, target)
    validation = verify_export(target, folder / "media-validation.json")
    cover = folder / "cover.jpg"
    ffmpeg, _ = find_tools()
    process = subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-i", str(target),
                              "-frames:v", "1", str(cover)], capture_output=True, timeout=60)
    if process.returncode or not cover.is_file():
        raise RenderError("Updream export cover could not be extracted")
    report = folder / "updream.result.json"
    payload = {"schema_version": 1, "status": "completed", "source": "owner_imported_updream_export",
               "video": str(target.resolve()), "cover": str(cover.resolve()), "report": str(report.resolve()),
               "validation": validation, "origin_verified_by_platform": False, "published": False}
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
