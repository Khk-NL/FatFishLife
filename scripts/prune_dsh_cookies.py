"""清理 DSH 桌面端累积的本地认证 Cookie。

DSH 每次启动会用一个随机端口起本地服务，并写一条 `dsh-auth-<随机>` 的 Cookie，host_key 恒为
`127.0.0.1`。Cookie 按主机发送、不区分端口，所以历史记录会一起塞进请求头；攒到 70 条左右就超过
请求头大小上限，桌面端报笼统的 “Web authentication failed”。

这个脚本把本地 host 下同名的历史 Cookie 删掉，只保留最新一条（没有就全清，App 下次启动会重发）。
必须在 App 关闭时运行——运行中 Chromium 会把内存里的 Cookie 写回磁盘，删了也会复活。

用法：
    python scripts/prune_dsh_cookies.py            # 真要清理（App 未运行才动手）
    python scripts/prune_dsh_cookies.py --check    # 只统计，不改
    python scripts/prune_dsh_cookies.py --keep 1   # 保留最新 N 条，默认 1
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
COOKIE_NAME_PREFIX = "dsh-auth-"
ACCESS_DENIED = (5, 32)  # Windows: 拒绝访问 / 文件被占用


def cookie_files(appdata: str | None = None) -> list[Path]:
    root = Path(appdata or os.environ.get("APPDATA", "")) / "@deepseek-ai" / "dsh-desktop"
    found: list[Path] = []
    for path in root.glob("Network/Cookies"):
        found.append(path)
    for path in root.glob("Partitions/*/Network/Cookies"):
        found.append(path)
    return [path for path in found if path.is_file()]


def host_running() -> bool:
    """有 DeepSeek Harness 进程在跑就别改库。"""
    try:
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq DeepSeek Harness.exe", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        return "DeepSeek Harness.exe" in out
    except Exception:
        return True  # 判断不了就当作在跑，宁可不改


def count_rows(path: Path) -> tuple[int, int]:
    """(本地 Cookie 总数, 其中 dsh-auth 的条数)。用只读+immutable 读，避免干扰运行中的 App。"""
    uri = "file:///" + quote(str(path).replace("\\", "/"), safe="/:") + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        print(f"  读不了（可能被占用）：{path} — {exc}")
        return (0, 0)
    try:
        placeholders = ",".join("?" for _ in LOCAL_HOSTS)
        total = con.execute(
            f"select count(*) from cookies where host_key in ({placeholders})", LOCAL_HOSTS
        ).fetchone()[0]
        auth = con.execute(
            f"select count(*) from cookies where host_key in ({placeholders}) and name like ?",
            (*LOCAL_HOSTS, COOKIE_NAME_PREFIX + "%"),
        ).fetchone()[0]
        return (int(total), int(auth))
    except sqlite3.Error as exc:
        print(f"  查询失败：{path} — {exc}")
        return (0, 0)
    finally:
        con.close()


def prune(path: Path, keep: int) -> int:
    """删掉历史记录，保留最新 keep 条；返回删除条数。"""
    placeholders = ",".join("?" for _ in LOCAL_HOSTS)
    con = sqlite3.connect(str(path), timeout=15)
    try:
        rows = con.execute(
            f"select rowid from cookies where host_key in ({placeholders}) and name like ? "
            "order by last_access_utc desc, creation_utc desc",
            (*LOCAL_HOSTS, COOKIE_NAME_PREFIX + "%"),
        ).fetchall()
        doomed = [row[0] for row in rows[keep:]]
        if not doomed:
            return 0
        marks = ",".join("?" for _ in doomed)
        con.execute(f"delete from cookies where rowid in ({marks})", doomed)
        con.commit()
        con.execute("vacuum")
        return len(doomed)
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只统计，不清理")
    parser.add_argument("--keep", type=int, default=1, help="保留最新几条（默认 1）")
    parser.add_argument("--force", action="store_true", help="App 在运行时也强行清理（不推荐）")
    args = parser.parse_args()

    files = cookie_files()
    if not files:
        print("没找到 DSH 桌面端的 Cookie 库，跳过。")
        return 0

    running = host_running()
    print(f"DSH 宿主正在运行：{'是' if running else '否'}")

    changed = 0
    for path in files:
        total, auth = count_rows(path)
        print(f"{path}\n  本地 Cookie {total} 条，其中 dsh-auth {auth} 条")
        if args.check:
            continue
        if running and not args.force:
            print("  宿主在运行，跳过（退出应用后再清，否则会被内存写回）。")
            continue
        if auth <= args.keep:
            print("  不需要清理。")
            continue
        try:
            removed = prune(path, args.keep)
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", None)
            print(f"  清理失败（{exc}），可能被占用；主机退出后再试。")
            continue
        print(f"  已删除 {removed} 条历史认证 Cookie。")
        changed += removed

    if not args.check:
        print(f"完成，共删除 {changed} 条。")
    print(f"PRUNE_RESULT files={len(files)} removed={changed} running={1 if running else 0} check={1 if args.check else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
