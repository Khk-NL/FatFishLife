"""Generate resumable meme semantics using the installed meme_manager backend.

Run with AstrBot's Python. Only public meme-pack images are sent to the selected
configured vision provider. No chat history, private notes or credentials are
included in prompts. Existing captions and manual overrides are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
import types


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def merged_provider(config: dict, provider_id: str) -> dict:
    selected = next(p for p in config["provider"] if p["id"] == provider_id)
    source_id = selected.get("provider_source_id")
    source = next((p for p in config.get("provider_sources", []) if p["id"] == source_id), {})
    return {**source, **selected}


class LocalCaptionContext:
    """Supply the narrow Context interface required by native generate_caption."""

    def __init__(self, provider, provider_id: str):
        self.provider = provider
        self.provider_id = provider_id
        self._meme_manager_caption_output_modes = {provider_id: "json"}

    async def llm_generate(self, chat_provider_id: str, **kwargs):
        if chat_provider_id != self.provider_id:
            raise ValueError("unexpected_caption_provider")
        tools = kwargs.pop("tools", None)
        return await self.provider.text_chat(
            **kwargs, func_tool=tools, request_max_retries=1,
        )


async def generate(args: argparse.Namespace) -> dict:
    args.astrbot_root = args.astrbot_root.resolve()
    os.environ["ASTRBOT_ROOT"] = str(args.astrbot_root)
    sys.path.insert(0, str(args.astrbot_root))
    plugin = args.astrbot_root / "data/plugins/meme_manager"
    package = types.ModuleType("_fatfish_native_meme_semantics")
    package.__path__ = [str(plugin)]
    sys.modules[package.__name__] = package
    module = package.__name__ + ".backend.semantic."
    storage = importlib.import_module(module + "storage")
    caption = importlib.import_module(module + "caption")
    models = importlib.import_module(module + "models")
    index = importlib.import_module(module + "index")
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    from astrbot.core.provider.sources.openai_embedding_source import OpenAIEmbeddingProvider

    runtime = args.astrbot_root / "data/plugin_data/meme_manager"
    pack = (runtime / "packs" / args.pack_id).resolve()
    if not pack.is_relative_to((runtime / "packs").resolve()) or not pack.is_dir():
        raise ValueError("invalid_or_missing_pack")
    config = read_json(args.astrbot_root / "data/cmd_config.json")
    vision_config = merged_provider(config, args.vision_provider_id)
    # Short JSON caption requests do not need the model's default thinking mode.
    vision_config["custom_extra_body"] = {
        **vision_config.get("custom_extra_body", {}), "thinking": {"type": "disabled"},
    }
    vision_config["timeout"] = args.timeout
    vision = ProviderOpenAIOfficial(vision_config, config.get("provider_settings", {}))
    context = LocalCaptionContext(vision, args.vision_provider_id)
    metadata = storage.reconcile_metadata(pack)
    storage.save_metadata(pack, metadata)
    categories = storage.load_category_descriptions(pack)
    pending = [
        (key, raw) for key, raw in metadata["images"].items()
        if not models.semantic_caption_is_complete(raw)
        and not raw.get("manual_override")
        and raw.get("provenance") not in {"manual", "mixed"}
    ]
    if args.limit:
        pending = pending[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"pid": os.getpid(), "pack_id": args.pack_id, "status": "captioning",
              "schema_version": models.SCHEMA_VERSION, "total": len(metadata["images"]),
              "selected": len(pending), "processed": 0, "failed": 0,
              "vision_provider_id": args.vision_provider_id, "token_usage_total": 0}

    def save_report():
        report["caption_done"] = sum(
            models.semantic_caption_is_complete(raw) for raw in metadata["images"].values()
        )
        report["needs_review"] = sum(
            raw.get("category_review_status") == "needs_review" for raw in metadata["images"].values()
        )
        storage._write_json_atomic(args.output_dir / "semantic-result.json", report)

    semaphore = asyncio.Semaphore(args.concurrency)
    save_report()

    async def process(key, raw):
        async with semaphore:
            item = models.SemanticImage.from_dict(raw)
            try:
                path = storage.safe_relative_path(pack, item.relative_path)
                if path is None or not path.is_file():
                    raise ValueError("missing_meme_image")
                result = await asyncio.wait_for(caption.generate_caption(
                    context, path, args.vision_provider_id, category=item.category,
                    category_description=item.category_description, available_categories=categories,
                ), timeout=args.timeout + 15)
                item.caption = item.auto_caption = result["caption"]
                item.auto_tags = result["tags"]
                item.tags = models.ensure_category_tag(result["tags"], item.category)
                item.visible_text = item.auto_visible_text = result["visible_text"]
                item.vision_model = result["vision_model"]
                item.prompt_version = result["prompt_version"]
                item.category_fit = item.auto_category_fit = result["category_fit"]
                item.category_review_status = item.auto_category_review_status = (
                    "auto_match" if item.category_fit == "match" else "needs_review"
                )
                item.category_review_reason = item.auto_category_review_reason = result["category_review_reason"]
                item.category_review_context_hash = item.category_context_hash
                item.suggested_category = result["suggested_category"]
                item.caption_status, item.embedding_status = "done", "pending"
                item.provenance, item.error = "ai", None
                item.text_hash = models.text_hash(item.vector_text)
                report["token_usage_total"] += int(result.get("token_usage", {}).get("total", 0) or 0)
            except Exception as exc:
                item.caption_status = "failed"
                item.error = type(exc).__name__
                report["failed"] += 1
            item.updated_at = models.utc_now()
            metadata["images"][key] = item.to_dict()
            metadata["requires_local_index_rebuild"] = True
            # Each completed request is an atomic checkpoint. A rerun skips it.
            storage.save_metadata(pack, metadata)
            report["processed"] += 1
            save_report()

    embedding = None
    try:
        await asyncio.gather(*(process(key, raw) for key, raw in pending))
        verified = storage.load_metadata(pack)
        if verified.get("metadata_read_only"):
            raise RuntimeError("native_metadata_validation_failed")
        complete = storage.semantic_metadata_is_complete(pack, verified)
        report["metadata_complete"] = complete
        if complete and not args.skip_index:
            report["status"] = "indexing"
            save_report()
            embedding_config = merged_provider(config, args.embedding_provider_id)
            embedding = OpenAIEmbeddingProvider(embedding_config, config.get("provider_settings", {}))
            adapter = index.EmbeddingAdapter(embedding, args.embedding_provider_id)
            manifest = await index.build_index(pack, runtime, args.pack_id, adapter)
            report["index_ready"] = index.index_is_ready(runtime, args.pack_id, metadata=storage.load_metadata(pack))
            report["index_items"] = manifest.get("item_count", 0)
        report["status"] = "completed" if not report["failed"] else "completed_with_errors"
        save_report()
        return report
    finally:
        await vision.terminate()
        if embedding is not None:
            await embedding.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pack-id", default="builtin-default")
    parser.add_argument("--vision-provider-id", default="deepseek/deepseek-flash")
    parser.add_argument("--embedding-provider-id", default="siliconflow/bge-m3")
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--limit", type=int, default=0, help="首批验证上限；0为全部待处理图片")
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()
    try:
        report = asyncio.run(generate(args))
    except Exception as exc:
        report = {"status": "failed", "error": type(exc).__name__}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "semantic-failure.json").write_text(json.dumps(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
