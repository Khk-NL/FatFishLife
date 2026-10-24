"""Compatibility entry point for source-grounded activity summaries."""
from pathlib import Path
import argparse
import json
from build_activity_knowledge import run
CFG = Path("D:/Code/Apps/AstrBot/data/cmd_config.json")

def api_key() -> str:
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    for source in cfg.get("provider_sources", []):
        if source.get("id") == "deepseek":
            key = source.get("key")
            return key[0] if isinstance(key, list) else str(key)
    raise RuntimeError("没有找到 DeepSeek Key")



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--astrbot",type=Path,default=CFG.parents[1])
    run(parser.parse_args())

if __name__ == "__main__":
    main()
