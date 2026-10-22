"""Generate editable example projects and an original synthetic test soundtrack."""

from __future__ import annotations

import array
import json
import math
import sys
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def write_demo_music(path: Path) -> None:
    rate = 32000
    duration = 16
    beat = 60 / 128
    notes = (440.0, 523.25, 587.33, 659.25, 783.99, 659.25, 587.33, 523.25)
    samples = array.array("h")
    for index in range(rate * duration):
        time = index / rate
        step = int(time / (beat / 2))
        position = time % (beat / 2)
        envelope = min(1, position / 0.01) * max(0, 1 - position / (beat / 2))
        frequency = notes[step % len(notes)]
        lead = (math.sin(2 * math.pi * frequency * time) + 0.15 * math.sin(4 * math.pi * frequency * time)) * envelope
        kick_time = time % beat
        kick = math.sin(2 * math.pi * 65 * kick_time) * math.exp(-kick_time * 32)
        bass = math.sin(2 * math.pi * 110 * time) * 0.12
        sample = int(32767 * (lead * 0.28 + kick * 0.18 + bass))
        samples.append(max(-32768, min(32767, sample)))
    if sys.byteorder != "little":
        samples.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(samples.tobytes())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    music = ROOT / "assets/music/demo-original.wav"
    write_demo_music(music)
    assets = {
        "silver": "../assets/originals/role-silver.jpg",
        "blue": "../assets/originals/role-blue.jpg",
        "red": "../assets/originals/role-red.jpg",
        "red_expression": "../assets/originals/role-red-expression.jpg",
        "notice": {"path": "../assets/originals/reference-layout.png", "crop": [300, 0, 970, 440]},
    }
    projects = {
        "single": [
            {"duration": 4, "roles": ["red"], "caption": "孩子们，先别急，主包的流水线开工了。"},
            {"duration": 4, "roles": ["red_expression"], "caption": "同一套衣服，换个表情，节目效果就来了。"},
            {"duration": 4, "roles": ["silver"], "caption": "这条不用抽卡，角色、字幕和小曲直接合成。"},
        ],
        "dialogue": [
            {"duration": 4, "roles": ["red", "blue"], "caption": "红衣：孩子们，这次谁负责整活？"},
            {"duration": 4, "roles": ["red_expression", "blue"], "caption": "蓝衣：你负责文案，我负责把小曲加速。", "zoom": 0.02},
            {"duration": 4, "roles": ["blue", "silver"], "caption": "孩子们，分工明确，今天又是稳定产出的一天。"},
        ],
        "news": [
            {"duration": 4, "roles": ["blue"], "panel": "notice", "caption": "孩子们，资讯截图也能直接放进模板。"},
            {"duration": 4, "roles": ["red"], "panel": "notice", "captions": [
                {"start": 0, "end": 2, "text": "图归图，角色归角色。"},
                {"start": 2, "end": 4, "text": "分层摆放，换一期也不费劲。"},
            ]},
            {"duration": 4, "roles": ["silver"], "panel": "notice", "caption": "换上你的新话题，下一条就能继续开工。", "zoom": 0},
        ],
    }
    for template, scenes in projects.items():
        project = {
            "schema_version": 1,
            "title": f"大肥鱼模板样片 · {template}",
            "canvas": {"width": 1920, "height": 1080, "fps": 30, "background": "#5AA6CF"},
            "template": template,
            "assets": assets,
            "music": {"path": "../assets/music/demo-original.wav", "speed": 1.25, "pitch": "follow_speed", "volume": 0.65, "fade_in": 0.3, "fade_out": 0.7},
            "scenes": scenes,
            "output": f"../outputs/{template}.mp4",
        }
        destination = ROOT / "examples" / f"{template}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(destination.relative_to(ROOT))
    print("测试 BGM 为本地合成旋律，不是崩铁音乐；可替换 music.path。")


if __name__ == "__main__":
    main()

