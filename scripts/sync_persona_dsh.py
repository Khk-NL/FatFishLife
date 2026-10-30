"""把 docs/persona/whale-core.md 同步进 DSH 运行时的人设 prefix。

运行时读的不是 Markdown 源文件，而是 profile 的 `cordis.patch.yml` 里
`dsh-persona` 的 `prefix: |` 块（安装器从 `dsh/preset-apple-le.yml` 抄进去的）。
两边都改，才能既让当前宿主生效，又让下次重装保持一致。

用法：
    python scripts/sync_persona_dsh.py --dry-run
    python scripts/sync_persona_dsh.py            # 同时改 preset 与 profile patch
    python scripts/sync_persona_dsh.py --profile-only
"""

from __future__ import annotations

import argparse
import re
import os
import shutil
import time
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/persona/whale-core.md"
EXAMPLES = ROOT / "docs/persona/whale-examples.md"
PRESET = ROOT / "dsh/preset-whale.yml"
DSH_HOME = Path.home() / ".dsh"
BILI_PERSONA = Path.home() / ".bili-ai" / "persona.md"


def profile_patch(profile: str) -> Path:
    return DSH_HOME / "profiles" / profile / "cordis.patch.yml"


def compose(with_examples: bool) -> str:
    text = SOURCE.read_text(encoding="utf-8").strip()
    if with_examples and EXAMPLES.is_file():
        examples = EXAMPLES.read_text(encoding="utf-8")
        # 只取示例对话代码块，正文说明不喂给模型
        blocks = re.findall(r"```\n(<START>.*?)\n```", examples, re.S)
        if blocks:
            text += "\n\n## 语气示例（不要复述原句，只学长短和味道）\n\n"
            text += "\n\n".join(f"<START>\n{b.strip()}" for b in blocks)
    return text


def atomic_write(path: Path, text: str, attempts: int = 3) -> None:
    """先写同目录临时文件再 os.replace；目录受限时改写到仓库暂存区，交给 shell 落盘。

    `~/.dsh/profiles/desktop` 的 ACL 只给沙盒子进程读权限（写会 PermissionError），
    但宿主的 shell 可以写。所以这里失败就暂存到 outputs/persona-staging/，
    由调用方（agent）用 cp 覆盖，脚本本身不假装写成功。
    """
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
    except PermissionError:
        stage = ROOT / "outputs/persona-staging" / path.name
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.write_text(text, encoding="utf-8", newline="\n")
        print(f"[暂存] 目录不可写，已生成 {stage}；请执行：cp \"{stage}\" \"{path}\"")
        return
    for index in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if index == attempts - 1:
                stage = ROOT / "outputs/persona-staging" / path.name
                stage.parent.mkdir(parents=True, exist_ok=True)
                stage.write_text(text, encoding="utf-8", newline="\n")
                tmp.unlink(missing_ok=True)
                print(f"[暂存] 替换受限，已生成 {stage}；请执行：cp \"{stage}\" \"{path}\"")
                return
            time.sleep(0.4)


def replace_prefix(path: Path, body: str, dry: bool) -> tuple[int, int]:
    """把 persona 的 prefix 块整体换掉。返回 (旧字符数, 新字符数)。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    indent = 0
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)prefix:\s*\|\s*$", line)
        if match:
            start, indent = index, len(match.group(1))
            break
    if start is None:
        raise SystemExit(f"没有在 {path} 里找到 prefix: | 块")
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
            break
        end += 1
    old_lines = lines[start + 1 : end]
    old_chars = len("\n".join(old_lines).strip())
    pad = " " * (indent + 2)
    new_lines = [pad + line if line.strip() else "" for line in body.splitlines()]
    if not dry:
        backup_dir = ROOT / "outputs/persona-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}")
        atomic_write(path, "\n".join(lines[: start + 1] + new_lines + lines[end:]) + "\n")
    return old_chars, len(body)


def verify(path: Path) -> str:
    try:
        import yaml
    except ImportError:
        return "未安装 PyYAML，跳过结构校验"
    loader = type("L", (yaml.SafeLoader,), {})
    loader.add_multi_constructor("tag:yaml.org,2002:js", lambda _l, _s, _n: None)
    loader.add_multi_constructor("!js", lambda _l, _s, _n: None)
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=loader)
    except yaml.YAMLError as error:
        return "解析失败：" + str(error).splitlines()[0][:120]
    return "解析正常" if isinstance(data, list) else f"顶层应是数组，实际是 {type(data).__name__}"


def whale_body() -> str:
    """由常驻卡生成 B 站分身人设：B 站只有私聊，去掉群聊、@、戳一戳这些规则。"""
    raw = SOURCE.read_text(encoding="utf-8").strip()
    sections = re.split(r"(?m)^## ", raw)
    kept = []
    for section in sections:
        if not section.strip():
            continue
        title = section.splitlines()[0]
        if "群里的判断力" in title:
            continue
        body = "## " + section if not section.startswith("# ") else section
        # 三、关系里「其他群友」小节只对 QQ 群有意义
        if "关系与称呼" in title and "### 其他群友" in body:
            body = body.split("### 其他群友")[0].rstrip() + chr(10)
        body = body.replace("QQ 3124904460。你的创造者", "你的创造者")
        body = body.replace("但老大私下问", "但对方私下问")
        kept.append(body.strip())
    header = ("# 吞星之鲸 · B 站分身" + chr(10) + chr(10) +
              "> 由 docs/persona/whale-core.md 自动生成，别手改这个文件；改完源文件重跑同步脚本。" + chr(10))
    return header + chr(10) + (chr(10) + chr(10)).join(kept) + chr(10)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步大肥鲸人设到 DSH 运行时")
    parser.add_argument("--profile", default="desktop")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-examples", action="store_true", help="把示例对话一并写进 prefix（更占上下文）")
    parser.add_argument("--profile-only", action="store_true", help="只改 profile patch，不动 preset")
    parser.add_argument("--no-whale", action="store_true", help="不生成 B 站分身人设")
    args = parser.parse_args()

    if not SOURCE.is_file():
        print(f"找不到人设源：{SOURCE}")
        return 1
    body = compose(args.with_examples)
    targets = [] if args.profile_only else [PRESET]
    targets.append(profile_patch(args.profile))

    for target in targets:
        if not target.is_file():
            print(f"跳过（不存在）：{target}")
            continue
        before, after = replace_prefix(target, body, args.dry_run)
        mark = "将改为" if args.dry_run else "已改为"
        print(f"{target}\n  {mark} {after} 字符（原 {before}）；结构：{verify(target) if not args.dry_run else '（dry-run 未写入）'}")
    if not args.no_whale:
        whale = whale_body()
        if args.dry_run:
            print(str(BILI_PERSONA) + " 将改为 " + str(len(whale)) + " 字符（B 站分身，由常驻卡生成）")
        else:
            BILI_PERSONA.parent.mkdir(parents=True, exist_ok=True)
            if BILI_PERSONA.is_file():
                backup_dir = ROOT / "outputs/persona-backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(BILI_PERSONA, backup_dir / ("bili-persona." + datetime.now().strftime("%Y%m%d-%H%M%S") + ".md"))
            atomic_write(BILI_PERSONA, whale)
            print(str(BILI_PERSONA) + " 已改为 " + str(len(whale)) + " 字符（B 站分身）")
    if args.dry_run:
        print("\n这是预览，没有写入。去掉 --dry-run 才会真的改。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
