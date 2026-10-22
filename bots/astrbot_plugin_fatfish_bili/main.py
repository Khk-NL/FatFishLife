"""AstrBot plugin: drive a Bilibili account through bili-cli, share memory with QQ."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

PLUGIN_NAME = "astrbot_plugin_fatfish_bili"
MEMORY_PLUGIN = "astrbot_plugin_fatfish_memory"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.exe = str(self.config.get("bili_exe") or "bili")
        home = str(self.config.get("bili_home") or "").strip()
        self.home = Path(home) if home else StarTools.get_data_dir(PLUGIN_NAME)
        self.home.mkdir(parents=True, exist_ok=True)
        memory = str(self.config.get("memory_db") or "").strip()
        self.memory_db = Path(memory) if memory else StarTools.get_data_dir(MEMORY_PLUGIN) / "memory.db"
        self._poll_task: asyncio.Task | None = None
        if bool(self.config.get("enable_inbox_poll", False)):
            self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"fatfish bili ready: exe={self.exe} home={self.home} memory={self.memory_db}")

    # ---------- bili-cli ----------

    async def _run(self, *args: str, timeout: float = 180.0, dry_run: bool = False) -> dict:
        command = [self.exe]
        if dry_run:
            command.append("--dry-run")
        command.extend(args)
        env = os.environ.copy()
        env["BILI_CLI_HOME"] = str(self.home)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            return {"ok": False, "error": {"code": "internal_error", "message": f"无法启动 bili-cli：{exc}", "hint": "检查 bili_exe 配置"}}
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return {"ok": False, "error": {"code": "network_error", "message": f"bili-cli 超过 {timeout:.0f} 秒未返回", "hint": "稍后重试"}}
        text = stdout.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(text)
        except ValueError:
            tail = (stderr.decode("utf-8", errors="replace") or text)[-400:].strip()
            return {"ok": False, "error": {"code": "internal_error", "message": tail or "bili-cli 没有返回 JSON", "hint": "运行 bili <命令> --help 检查参数"}}

    @staticmethod
    def _error(payload: dict) -> str:
        error = payload.get("error") or {}
        code = error.get("code", "unknown")
        message = error.get("message", "未知错误")
        hint = error.get("hint") or ""
        return f"B 站操作失败（{code}）：{message}" + (f"\n提示：{hint}" if hint else "")

    @staticmethod
    def _format(payload: dict, limit: int = 3500) -> str:
        if not payload.get("ok"):
            return ""
        text = json.dumps(payload.get("data"), ensure_ascii=False, indent=2)
        return text if len(text) <= limit else text[:limit] + "\n…（已截断）"

    # ---------- shared memory ----------

    def _remember(self, content: str, *, scope: str = "public", kind: str = "bili") -> bool:
        if not self.memory_db.is_file():
            logger.warning(f"共享记忆库不存在：{self.memory_db}")
            return False
        try:
            conn = sqlite3.connect(self.memory_db, timeout=10)
            try:
                conn.execute(
                    "INSERT INTO events(platform, scope, kind, session, actor, content, created_at, meta) VALUES (?,?,?,?,?,?,?,?)",
                    ("bilibili", scope, kind, "bili-cli", "", " ".join(content.split())[:500], _now(), "{}"),
                )
                conn.commit()
            finally:
                conn.close()
            return True
        except sqlite3.Error as exc:
            logger.warning(f"写入共享记忆失败：{exc}")
            return False

    async def _notify(self, text: str) -> None:
        umo = str(self.config.get("notify_umo") or "").strip()
        if not umo:
            return
        try:
            await StarTools.send_message(umo, [Plain(text)])
        except (ValueError, RuntimeError, OSError) as exc:
            logger.warning(f"推送失败：{exc}")

    async def _poll_loop(self) -> None:
        interval = max(60, int(self.config.get("poll_interval_seconds", 180)))
        while True:
            try:
                payload = await self._run("feed", "inbox", "--limit", "5", timeout=60)
                if payload.get("ok"):
                    data = payload.get("data") or {}
                    summary = json.dumps(data, ensure_ascii=False)
                    if summary not in ("{}", "[]", "null"):
                        self._remember("B 站收件箱更新：" + summary, scope="public", kind="inbox")
                        await self._notify("B 站有新消息：\n" + summary[:1200])
                elif payload.get("error", {}).get("code") in ("not_logged_in", "auth_expired", "risk_control", "captcha_required"):
                    await self._notify(self._error(payload) + "\n轮询已暂停。")
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the loop alive; one bad poll must not kill it
                logger.warning(f"收件箱轮询异常：{exc}")
            await asyncio.sleep(interval)

    # ---------- commands ----------

    @filter.command("bili")
    async def bili(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr("")):
        command = (action or "").strip()
        body = str(text or "").strip()
        if command in ("", "帮助", "help"):
            yield event.plain_result(
                "B 站用法：\n"
                "/bili 状态\n"
                "/bili 登录      生成二维码\n"
                "/bili 确认      检查扫码结果\n"
                "/bili 收件箱\n"
                "/bili 看 <BV号>\n"
                "/bili 搜 <关键词>\n"
                "/bili 回复 <BV号> <评论ID> <内容>\n"
                "/bili 私信 <UID> <内容>\n"
                "/bili 记忆 <关键词>\n"
                "写操作默认只预览；关闭 dry_run_writes 才会真正发送。"
            )
            return
        if command == "状态":
            auth = await self._run("auth", "status", timeout=60)
            me = await self._run("me", "show", timeout=60) if auth.get("ok") else {}
            lines = [f"bili-cli: {self.exe}"]
            lines.append("登录：" + ("是" if auth.get("data", {}).get("logged_in") else self._error(auth) if not auth.get("ok") else "否"))
            if me.get("ok"):
                data = me.get("data") or {}
                lines.append("账号：" + json.dumps({k: data.get(k) for k in ("uid", "name", "level", "coins") if k in data}, ensure_ascii=False))
            lines.append("凭据目录：" + str(self.home))
            lines.append("共享记忆：" + str(self.memory_db) + ("（存在）" if self.memory_db.is_file() else "（缺失）"))
            lines.append("写操作：" + ("仅预览" if self.config.get("dry_run_writes", True) else "真实发送"))
            lines.append("收件箱轮询：" + ("开启" if self._poll_task and not self._poll_task.done() else "关闭"))
            yield event.plain_result("\n".join(lines))
            return
        if command == "登录":
            qr = self.home / "qr.png"
            payload = await self._run("auth", "login", "--qr-out", str(qr), timeout=90)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            data = payload.get("data") or {}
            image_path = Path(str(data.get("qr_image") or qr))
            if not image_path.is_file():
                yield event.plain_result("二维码已生成但找不到图片：" + str(data.get("qr_url") or image_path))
                return
            yield event.chain_result([
                Image.fromFileSystem(str(image_path)),
                Plain(f"请用 B 站 App 扫码（{data.get('expires_in', 180)} 秒内有效），扫完发送 /bili 确认。"),
            ])
            return
        if command == "确认":
            payload = await self._run("auth", "status", "--wait", "120", timeout=150)
            if payload.get("ok") and payload.get("data", {}).get("logged_in"):
                me = await self._run("me", "show", timeout=60)
                uid = (me.get("data") or {}).get("uid") if me.get("ok") else None
                if uid and str(self.config.get("owner_uid") or "") == str(uid):
                    await self._run("owner", "set", str(uid), timeout=60)
                yield event.plain_result("B 站登录成功。" + (f"\nUID：{uid}" if uid else ""))
            else:
                yield event.plain_result("还没有完成登录。\n" + (self._error(payload) if not payload.get("ok") else "请确认手机端已同意扫码。"))
            return
        if command == "收件箱":
            payload = await self._run("feed", "inbox", "--limit", "5", timeout=90)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            data = payload.get("data") or {}
            self._remember("B 站收件箱：" + json.dumps(data, ensure_ascii=False), scope="public", kind="inbox")
            yield event.plain_result("B 站收件箱：\n" + self._format(payload, 4000))
            return
        if command == "看":
            if not body:
                yield event.plain_result("请给出 BV 号或链接，例如 /bili 看 BV1xx411c7mD")
                return
            payload = await self._run("video", "watch", body.split()[0], "--comments", "5", "--max-chars", "3000", timeout=300)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            data = payload.get("data") or {}
            title = data.get("title") or body
            summary = data.get("summary") or data.get("ai_summary") or ""
            self._remember(f"看了 B 站视频《{title}》：{summary}", scope="public", kind="video")
            yield event.plain_result(f"《{title}》\n" + self._format(payload, 4000))
            return
        if command == "搜":
            if not body:
                yield event.plain_result("请给出关键词，例如 /bili 搜 崩铁")
                return
            payload = await self._run("search", "video", body, "--size", "10", timeout=90)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            yield event.plain_result("搜索结果：\n" + self._format(payload, 4000))
            return
        if command == "回复":
            if not event.is_admin():
                yield event.plain_result("只有管理员可以回复评论。")
                return
            parts = body.split(maxsplit=2)
            if len(parts) < 3:
                yield event.plain_result("格式：/bili 回复 <BV号> <评论ID> <内容>")
                return
            target, rpid, content = parts
            dry = bool(self.config.get("dry_run_writes", True))
            payload = await self._run("comment", "reply", target, rpid, content, timeout=90, dry_run=dry)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            if not dry:
                self._remember(f"回复了 {target} 的评论 {rpid}：{content}", scope="public", kind="reply")
            yield event.plain_result(("已发送。" if not dry else "预览（未发送）：") + "\n" + self._format(payload))
            return
        if command == "私信":
            if not event.is_admin():
                yield event.plain_result("只有管理员可以发私信。")
                return
            parts = body.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("格式：/bili 私信 <UID|owner> <内容>")
                return
            target, content = parts
            dry = bool(self.config.get("dry_run_writes", True))
            payload = await self._run("dm", "send", target, content, timeout=90, dry_run=dry)
            if not payload.get("ok"):
                yield event.plain_result(self._error(payload))
                return
            if not dry:
                self._remember(f"给 {target} 发了私信：{content}", scope="private", kind="dm")
            yield event.plain_result(("已发送。" if not dry else "预览（未发送）：") + "\n" + self._format(payload))
            return
        if command == "记忆":
            if not body:
                yield event.plain_result("请给出关键词，例如 /bili 记忆 视频")
                return
            if not self.memory_db.is_file():
                yield event.plain_result("共享记忆库还没有创建，先启用 astrbot_plugin_fatfish_memory。")
                return
            try:
                conn = sqlite3.connect(self.memory_db, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute(
                        "SELECT created_at, scope, content FROM events WHERE platform='bilibili' AND content LIKE ? ORDER BY id DESC LIMIT 10",
                        (f"%{body}%",),
                    ).fetchall()
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                yield event.plain_result(f"读取记忆失败：{exc}")
                return
            if not rows:
                yield event.plain_result("没有找到 B 站相关记忆。")
                return
            yield event.plain_result("B 站记忆：\n" + "\n".join(f"[{row['created_at'][:16]}] {row['scope']} {row['content'][:120]}" for row in rows))
            return
        yield event.plain_result("未知操作，发送 /bili 帮助 查看用法。")

    # ---------- LLM tools ----------

    @filter.llm_tool(name="bili_watch")
    async def bili_watch(self, event: AstrMessageEvent, video_id: str):
        """看懂一个 B 站视频：标题、AI 总结、字幕全文、热评与画面总览。

        Args:
            video_id(string): BV 号、av 号或视频链接
        """
        payload = await self._run("video", "watch", video_id, "--comments", "5", "--max-chars", "3000", timeout=300)
        if not payload.get("ok"):
            yield event.plain_result(self._error(payload))
            return
        data = payload.get("data") or {}
        title = data.get("title") or video_id
        self._remember(f"看了 B 站视频《{title}》：" + str(data.get("summary") or ""), scope="public", kind="video")
        yield event.plain_result(f"《{title}》\n" + self._format(payload, 4000))

    @filter.llm_tool(name="bili_search")
    async def bili_search(self, event: AstrMessageEvent, keyword: str, limit: int = 10):
        """搜索 B 站视频，返回标题、UP 主、播放量与链接。

        Args:
            keyword(string): 搜索关键词
            limit(number): 返回条数，默认 10
        """
        payload = await self._run("search", "video", keyword, "--size", str(max(1, min(20, int(limit)))), timeout=90)
        if not payload.get("ok"):
            yield event.plain_result(self._error(payload))
            return
        yield event.plain_result("B 站搜索结果：\n" + self._format(payload, 4000))

    @filter.llm_tool(name="bili_inbox")
    async def bili_inbox(self, event: AstrMessageEvent):
        """查看 B 站收件箱：新回复、@、赞、系统通知和未读私信。"""
        payload = await self._run("feed", "inbox", "--limit", "5", timeout=90)
        if not payload.get("ok"):
            yield event.plain_result(self._error(payload))
            return
        data = payload.get("data") or {}
        self._remember("B 站收件箱：" + json.dumps(data, ensure_ascii=False), scope="public", kind="inbox")
        yield event.plain_result("B 站收件箱：\n" + self._format(payload, 4000))

    async def terminate(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        logger.info("fatfish bili stopped")
