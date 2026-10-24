"""Export sender-free, conversation-isolated local Markdown chat memory."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish_core.chat_records import export_chat_records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/chat-memory")
    args = parser.parse_args()
    print(json.dumps(export_chat_records(args.db, args.output_dir)))
