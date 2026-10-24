"""Compatibility entry point; always use meme_manager native schema and entry IDs."""
import sys
from pathlib import Path
from generate_meme_semantics import main
if __name__ == "__main__":
    sys.argv[1:1] = ["--astrbot-root", "D:/Code/Apps/AstrBot", "--output-dir", str(Path(__file__).resolve().parents[1]/"outputs/meme-semantics")]
    raise SystemExit(main())
