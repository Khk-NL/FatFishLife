"""把 docs/persona/apple-le-core.md 同步进 DSH 运行时的人设 prefix。

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
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/persona/apple-le-core.md"
EXAMPLES = ROOT / "docs/persona/apple-le-examples.md"
PRESET = ROOT / "dsh/preset-apple-le.yml"
DSH_HOME = Path.home() / ".dsh"


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
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}"))
        path.write_text("\n".join(lines[: start + 1] + new_lines + lines[end:]) + "\n", encoding="utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="同步苹果乐人设到 DSH 运行时")
    parser.add_argument("--profile", default="desktop")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-examples", action="store_true", help="把示例对话一并写进 prefix（更占上下文）")
    parser.add_argument("--profile-only", action="store_true", help="只改 profile patch，不动 preset")
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
    if args.dry_run:
        print("\n这是预览，没有写入。去掉 --dry-run 才会真的改。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
