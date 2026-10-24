"""Updream creation briefs, exported-video verification and explicit owner approval."""

from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Video
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from fatfish_bili.publisher import PublishError
from fatfish_story.client import _loads_json_object
from fatfish_story.updream import BRIEF_PROMPT, save_brief, import_export
from fatfish_core.usage import record_usage
from fatfish_story.review import ReviewError, ReviewQueue

PLUGIN_NAME = "astrbot_plugin_fatfish_story"


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.directory = StarTools.get_data_dir(PLUGIN_NAME)
        self.queue = ReviewQueue(self.directory / "reviews")
        self._lock = asyncio.Lock()
        logger.info("fatfish story ready: owner preview and explicit approval")

    def _instance(self, name):
        item = self.context.get_registered_star(name)
        return getattr(item, "star_cls", None) if item and getattr(item, "activated", True) else None

    def _memory(self):
        memory = self._instance("astrbot_plugin_fatfish_memory")
        return memory.store if memory else None

    def _owner_private(self, event):
        if not event.is_private_chat():
            return False
        platform = str(event.get_platform_name() or "").lower()
        if not platform.startswith(("aiocqhttp", "qq_official")):
            return False
        owner = str(self.config.get("owner_qq") or "").strip()
        if not owner:
            bili = self._instance("astrbot_plugin_fatfish_bili")
            owner = str(bili.config.get("owner_qq") or "").strip() if bili else ""
        # Administrator status and model-generated text never grant publish approval.
        return bool(owner) and str(event.get_sender_id()) == owner

    def _identity(self, event):
        return {"owner": str(event.get_sender_id()), "session": str(event.unified_msg_origin)}

    def _growth(self, stage, status, error_code=""):
        store = self._memory()
        if store is None:
            return
        try:
            from fatfish_core.growth import record_capability
            record_capability(store, "video_review", status, stage=stage, error_code=error_code)
        except Exception as exc:
            logger.warning(f"视频成长记录未写入：{type(exc).__name__}")

    def _metadata(self, *, topic, title):
        raw_tags = str(self.config.get("tags") or "").replace("，", ",")
        return {
            "title": title[:80], "description": f"话题：{topic}"[:2000],
            "tags": [tag.strip() for tag in raw_tags.split(",") if tag.strip()],
            "zone": int(self.config.get("zone") or 0), "tid": int(self.config.get("tid") or 0),
            "ai_declare": True,
        }

    def _bili_settings(self):
        bili = self._instance("astrbot_plugin_fatfish_bili")
        if bili:
            return {"bili_exe": bili.exe, "bili_home": bili.home}
        home = str(self.config.get("bili_home") or "").strip()
        return {"bili_exe": str(self.config.get("bili_exe") or "bili"), "bili_home": Path(home) if home else None}

    async def _prepare_updream(self, topic, event):
        provider = await self.context.get_using_provider_async(umo=event.unified_msg_origin)
        if provider is None:
            raise ValueError("请先配置创作模型")
        prompt = f"公开选题：{topic}\n目标时长：{max(15, min(180, int(self.config.get('duration') or 30)))}秒。"
        lore = self._instance("astrbot_plugin_fatfish_lore")
        if lore:
            prompt += "\n公开设定参考：\n" + lore.graph.context(topic, max_chars=2500)
        response = await asyncio.wait_for(provider.text_chat(prompt=prompt, system_prompt=BRIEF_PROMPT + "\n角色语气：" + str(self.config.get("persona") or "苹果乐，以能天使为基础"),
                                           contexts=[], response_format={"type":"json_object"}), timeout=135)
        await record_usage(self.context, provider, response, umo=event.unified_msg_origin, agent_type="fatfish_updream_plan")
        job = await asyncio.to_thread(save_brief, self.directory / "updream", topic,
                                      _loads_json_object(response.completion_text), **self._identity(event))
        self._growth("plan", "success")
        return job

    async def _import_updream(self, path, event):
        media = await asyncio.to_thread(import_export, Path(path.strip().strip('"')).expanduser(), self.directory / "updream_exports")
        row = await asyncio.to_thread(self.queue.create, media["video"],
                                      self._metadata(topic="Updream制作成片", title=Path(path).stem[:80]),
                                      report=media["report"], topic="Updream制作成片", **self._identity(event))
        self._growth("generate", "success")
        return row

    def _preview_text(self, row):
        meta = row["metadata"]
        lines = [f"老板，成片 {row['id']} 先给你看。", f"标题：{meta['title']}",
                 f"简介：{meta['description']}", "标签：" + "、".join(meta["tags"]),
                 f"分区：zone={meta['zone']}，tid={meta['tid']}；声明 AI 生成。"]
        if row.get("metadata_error"):
            lines.append("投稿信息待配置：" + row["metadata_error"] + "。在控制台配置后，用 /视频 预览 " + row["id"] + " 取得新的审阅编号。")
        else:
            lines.append(f"看片并检查这些投稿信息后，发 /视频 确认 {row['id']} 才提交审核。")
        lines.append(f"先不发就用 /视频 取消 {row['id']}。")
        return "\n".join(lines)

    async def _preview(self, row, event):
        # All sends must return without error before an approval becomes actionable.
        await event.send(event.chain_result([Image.fromFileSystem(row["cover"])]))
        await event.send(event.chain_result([Video.fromFileSystem(row["video"])]))
        await event.send(event.plain_result(self._preview_text(row)))
        await asyncio.to_thread(self.queue.mark_preview, row["id"], **self._identity(event))
        self._growth("review", "success")

    @filter.command("视频")
    async def video(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr("")):
        if not self._owner_private(event):
            yield event.plain_result("视频制作和投稿只在老板的 QQ 私聊里处理。")
            return
        action, body = str(action).strip(), str(text).strip()
        if action in ("", "帮助", "help"):
            yield event.plain_result(
                "/视频 选题：从最近公开候选中选话题\n/视频 制作 <话题>：准备Updream叙事方案\n/视频 导入 <本机成片路径>：核验Updream导出并私聊看片\n"
                "/视频 预览 <编号>：重发成片，更新投稿配置时需重新审阅\n"
                "/视频 确认 <编号>：只投稿该次预览\n/视频 取消 <编号>\n/视频 状态 <编号>"
            )
            return
        if action == "选题":
            store = self._memory()
            rows = store.recent(scopes=("public",), kinds=("video",), limit=5) if store else []
            yield event.plain_result("最近公开选题候选：\n" + "\n".join(str(row["content"]) for row in rows) if rows else
                                     "还没有公开选题候选。可以先用 /bili 发现，或直接 /视频 制作 <话题>。")
            return
        if action not in ("制作", "导入", "预览", "确认", "取消", "状态") or not body:
            yield event.plain_result("发送 /视频 帮助 查看用法。")
            return
        if self._lock.locked():
            yield event.plain_result("上一条视频操作还在处理，完成后再来。")
            return
        async with self._lock:
            stage = "generate" if action in ("制作", "导入") else "publish" if action == "确认" else "review"
            try:
                if action == "制作":
                    if len(body) > 1000:
                        raise ReviewError("话题请控制在 1000 字内")
                    job = await self._prepare_updream(body, event)
                    yield event.plain_result(f"Updream创作方案 {job['id']} 已准备：{job['brief']['title']}\n{job['path']}\n"
                                             "视频统一在Updream制作；平台生成和导出完成后，用 /视频 导入 <本机成片路径> 发给老板看片。")
                elif action == "导入":
                    row = await self._import_updream(body, event)
                    stage = "review"
                    await self._preview(row, event)
                elif action == "预览":
                    row = self.queue.get(body, **self._identity(event))
                    row = self.queue.revise(body, self._metadata(topic=row["topic"], title=row["metadata"]["title"]), **self._identity(event))
                    await self._preview(row, event)
                elif action == "确认":
                    row = await asyncio.to_thread(self.queue.submit, body, **self._identity(event), **self._bili_settings())
                    self._growth("publish", "success")
                    yield event.plain_result("已提交审核：" + row["result"]["url"] + "\n审核通过后才会公开。")
                elif action == "取消":
                    self.queue.cancel(body, **self._identity(event))
                    yield event.plain_result("这条先留在本地，已取消投稿审批。")
                else:
                    row = self.queue.get(body, **self._identity(event))
                    yield event.plain_result(f"视频 {row['id']}：{row['status']}" + ("\n" + row["result"]["url"] if row.get("result") else ""))
            except Exception as exc:
                status = "failed"
                if action == "确认":
                    try:
                        status = "uncertain" if self.queue.get(body, **self._identity(event))["status"] in ("uncertain", "submitting") else "blocked"
                    except ReviewError:
                        status = "blocked"
                code = "unconfirmed" if status == "uncertain" else "not_configured" if isinstance(exc, PublishError) else "awaiting_review" if status == "blocked" else "service_error"
                self._growth(stage, status, code)
                # Provider and renderer diagnostics may contain request data; full details stay local.
                if isinstance(exc, (ReviewError, PublishError)):
                    message = str(exc)
                else:
                    message = "本次Updream方案或导出处理未完成，请在本机检查创作模型、成片路径和媒体工具。"
                logger.warning(f"视频 {stage} 失败：{type(exc).__name__}")
                yield event.plain_result(message)
