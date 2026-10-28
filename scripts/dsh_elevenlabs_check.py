"""Read ElevenLabs voice/model metadata only. No synthesis or credit-consuming call."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish_core.local_credentials import read_value


def check(env_file: Path, output: Path) -> dict:
    key = read_value(env_file, ('ELEVENLABS_API_KEY', 'FATFISH_ELEVENLABS_API_KEY', 'XI_API_KEY', 'API_KEY'), allow_bare=True)
    if not key:
        return {'ok': False, 'reason': '指定文件中未识别到ElevenLabs密钥', 'synthesis_requests': 0}
    def get(path):
        request = urllib.request.Request('https://api.elevenlabs.io' + path, headers={'xi-api-key': key})
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)
    try:
        models = get('/v1/models')
        voices = get('/v2/voices?page_size=100&include_total_count=false')
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'http_status': exc.code, 'synthesis_requests': 0}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {'ok': False, 'reason': type(exc).__name__, 'synthesis_requests': 0}
    cache = {'models': [{'id': row['model_id'], 'name': row.get('name', row['model_id'])}
                        for row in models if row.get('can_do_text_to_speech')],
             'voices': [{'id': row['voice_id'], 'name': row.get('name', '未命名音色'), 'category': row.get('category')}
                        for row in voices.get('voices', [])],
             'has_more_voices': bool(voices.get('has_more')), 'synthesis_requests': 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'ok': True, 'models': len(cache['models']), 'voices': len(cache['voices']),
            'has_more_voices': cache['has_more_voices'], 'synthesis_requests': 0, 'cache': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path.home()/'Desktop/.env')
    parser.add_argument('--output', type=Path, default=ROOT/'data/dsh/elevenlabs-catalog.json')
    args = parser.parse_args()
    result = check(args.env_file, args.output)
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(0 if result['ok'] else 1)
