"""QQ / NapCat 版本守卫。

为什么不是"两个都自动更新"：
- NapCat 是靠注入 QQ 进程工作的，它的支持表是**按 QQ 构建号**写死的；
  我们实测过：QQ 9.9.33-52230 + NapCat 4.18.38（表里最高 9.9.31）= 每次启动 QQ 都 0x80000003 崩。
- 所以正确顺序是「先有支持表，再让 QQ 升级」。QQ 自己自动更新会跑到 NapCat 前面，
  必然出现一段"新 QQ + 旧 NapCat"的窗口，也就是你反复看到的崩溃。

这个脚本做两件事：
1. 检查当前 QQ 构建号是否在已装 NapCat 的支持表里；
2. 不在的话，自动拉最新 NapCat（走 7890 代理），换装并保留 config，然后重启 NapCat。

用法：
    python scripts/version_guard.py --check      # 只检查，打印结果
    python scripts/version_guard.py             # 检查 + 需要时自动修
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

QQ_EXE = Path("D:/Q/QQ.exe")
NAPCAT_HOME = Path("D:/Code/Apps/NapCat")
NAPCAT_ENTRY = NAPCAT_HOME / "napcat.mjs"
LOG = Path("D:/Code/Projects/FatFishLife/outputs/agent/version-guard.log")
PROXY = os.environ.get("FATFISH_PROXY", "http://127.0.0.1:7890")
ATOM = "https://github.com/NapNeko/NapCatQQ/releases.atom"
ASSET = "https://github.com/NapNeko/NapCatQQ/releases/download/{tag}/NapCat.Shell.zip"


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    LOG.write_text((LOG.read_text(encoding='utf-8') if LOG.exists() else '') + line + "\n", encoding="utf-8")
    print(line)


def qq_version() -> tuple[str, str]:
    """返回 ('9.9.33', '52230')。"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Item '{QQ_EXE.as_posix()}').VersionInfo.ProductVersion"],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    ).stdout.strip()
    match = re.match(r"(\d+\.\d+\.\d+)\.(\d+)", out)
    if not match:
        raise SystemExit(f"读不到 QQ 版本：{out!r}")
    return match.group(1), match.group(2)


def supported_builds() -> set[tuple[str, str]]:
    text = NAPCAT_ENTRY.read_text(encoding="utf-8", errors="ignore")
    keys = set(re.findall(r'"(\d+\.\d+\.\d+)-(\d+)"', text))
    return keys


def latest_tag() -> str:
    request = urllib.request.Request(ATOM, headers={"User-Agent": "fatfish-version-guard"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    with opener.open(request, timeout=60) as response:
        body = response.read().decode("utf-8", errors="ignore")
    tags = re.findall(r"releases/tag/(v[\d.]+)", body)
    if not tags:
        raise SystemExit("atom 里没有 tag")
    return tags[0]


def download(url: str, target: Path) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    request = urllib.request.Request(url, headers={"User-Agent": "fatfish-version-guard"})
    with opener.open(request, timeout=300) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def upgrade_napcat() -> str:
    tag = latest_tag()
    log(f"发现新版本 NapCat {tag}，开始下载")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "napcat.zip"
        download(ASSET.format(tag=tag), zip_path)
        extract = Path(tmp) / "extract"
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract)
        entry = extract / "napcat.mjs"
        if not entry.exists():
            raise SystemExit("下载包里没有 napcat.mjs")
        text = entry.read_text(encoding="utf-8", errors="ignore")
        builds = set(re.findall(r'"(\d+\.\d+\.\d+)-(\d+)"', text))
        major, build = qq_version()
        if (major, build) not in builds:
            raise SystemExit(f"{tag} 也不支持 {major}-{build}")
        # 换装：保留 config，其它目录整体替换
        backup = NAPCAT_HOME.with_name(f"NapCat.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copytree(NAPCAT_HOME / "config", extract / "config", dirs_exist_ok=True)
        shutil.move(str(NAPCAT_HOME), str(backup))
        shutil.copytree(extract, NAPCAT_HOME)
        log(f"NapCat 已换装 {tag}（旧版备份 {backup.name}），支持 {major}-{build}")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process QQ,NapCatWinBootMain -ErrorAction SilentlyContinue | Stop-Process -Force"],
                   capture_output=True, timeout=60)
    subprocess.run(["cmd", "/c", "schtasks /Run /TN FatFishLife-Start"], capture_output=True, timeout=60)
    return tag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not NAPCAT_ENTRY.exists():
        log(f"找不到 NapCat：{NAPCAT_ENTRY}")
        return 2
    major, build = qq_version()
    builds = supported_builds()
    version = f"{major}-{build}"
    supported = (major, build) in builds
    if args.check:
        print(json.dumps({"qq": version, "supported": supported, "napcat_builds": len(builds)}, ensure_ascii=False))
        return 0 if supported else 1
    if supported:
        log(f"QQ {version} 在 NapCat 支持表里，什么都不做")
        return 0
    log(f"QQ {version} 不在 NapCat 支持表里（共 {len(builds)} 个构建），尝试自动升级 NapCat")
    try:
        tag = upgrade_napcat()
    except Exception as error:  # noqa: BLE001
        log(f"自动升级失败：{type(error).__name__}: {error}")
        return 1
    log(f"已升级到 {tag}，NapCat 正在重启")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
