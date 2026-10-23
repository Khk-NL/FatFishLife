"""对「资料不足」的活动换页面名重试（原名 / 加年份 / 去复刻后缀）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_activity_summaries import api_key  # noqa: E402
from rewrite_activity_summaries import prts_text, rewrite, TARGET  # noqa: E402


def variants(title: str) -> list[str]:
    base = re.sub(r"(·复刻|复刻)$", "", title).strip()
    out = [base]
    for year in ("2026", "2025", "2024", "2023"):
        out.append(f"{base}{year}")
    out.append(f"{base}·复刻")
    return list(dict.fromkeys(out))


def main() -> None:
    key = api_key()
    text = TARGET.read_text(encoding="utf-8")
    blocks = re.findall(r"## (.+?)\n\n- 登场：(.+?)\n- 梗概：(.+?)\n", text)
    targets = [b for b in blocks if "资料不足" in b[2]]
    print("待补", len(targets))
    for index, (title, chars, summary) in enumerate(targets, 1):
        source = ""
        used = ""
        for candidate in variants(title):
            source = prts_text(candidate)
            if len(source) > 400:
                used = candidate
                break
        if not source or len(source) <= 400:
            print(f"[{index}/{len(targets)}] {title} 仍无页面")
            continue
        try:
            result = rewrite(key, title, source)
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {title}: {exc}")
            continue
        new_chars = "、".join(result.get("characters") or []) or "资料不足"
        new_summary = str(result.get("summary") or "资料不足，别编").strip()
        old_block = f"## {title}\n\n- 登场：{chars}\n- 梗概：{summary}\n"
        new_block = f"## {title}\n\n- 登场：{new_chars}\n- 梗概：{new_summary}\n"
        text = text.replace(old_block, new_block, 1)
        TARGET.write_text(text, encoding="utf-8")
        print(f"[{index}/{len(targets)}] {title} <- {used}")


if __name__ == "__main__":
    main()
