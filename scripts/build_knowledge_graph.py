"""Build local, source-backed lore/Obsidian graphs with configured providers."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    os.environ["ASTRBOT_ROOT"] = str(args.astrbot.resolve())
    sys.path.insert(0, str(args.astrbot.resolve()))
    from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    from fatfish_core import resolve_shared_db
    from fatfish_core.knowledge_graph import KnowledgeGraph
    from fatfish_core.graph_build import build_graph, file_documents
    cfg = json.loads((args.astrbot / "data/cmd_config.json").read_text(encoding="utf-8-sig"))
    model = next(p for p in cfg["provider"] if p["id"] == "deepseek/deepseek-flash")
    source = next(p for p in cfg["provider_sources"] if p["id"] == model["provider_source_id"])
    provider = ProviderOpenAIOfficial({**source, **model, "custom_extra_body": {"thinking": {"type": "disabled"}}}, cfg.get("provider_settings", {}))
    graph = KnowledgeGraph(resolve_shared_db(args.astrbot / "data"))
    docs = list(file_documents(ROOT / "docs/knowledge", "lore"))
    if args.private_vault:
        docs += list(file_documents(args.private_vault, "private_obsidian"))
    async def generate(system, text):
        r = await asyncio.wait_for(provider.text_chat(system_prompt=system, prompt=text,
                                   response_format={"type": "json_object"}, max_tokens=6500), timeout=90)
        return r.completion_text
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def progress(result):
        args.output.write_text(json.dumps(result), encoding="utf-8")
    try:
        result = await build_graph(graph, docs, generate, progress=progress,
                                   complete_collections=["lore", *(["private_obsidian"] if args.private_vault else [])])
        result.update(lore=graph.stats(), private_obsidian=graph.stats(collection="private_obsidian"))
        progress(result)
        print(json.dumps(result))
    finally:
        await provider.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--astrbot", type=Path, required=True)
    p.add_argument("--private-vault", type=Path)
    p.add_argument("--output", type=Path, default=ROOT / "outputs/knowledge-graph-result.json")
    asyncio.run(run(p.parse_args()))
