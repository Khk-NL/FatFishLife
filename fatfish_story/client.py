"""Model providers. The default provider talks to DeepSeek's OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict: ...


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env reader so the tool has no extra dependency."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_api_key(project_root: Path | None = None) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    root = project_root or Path(__file__).resolve().parent.parent
    key = _read_dotenv(root / ".env").get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise ProviderError("缺少 DEEPSEEK_API_KEY：请在环境变量或项目 .env 中配置")
    return key


@dataclass
class DeepSeekProvider:
    api_key: str
    model: str = "deepseek-chat"
    base_url: str = DEEPSEEK_URL
    timeout: float = 120.0
    name: str = "deepseek"

    def complete_json(self, system: str, user: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.9,
            "max_tokens": 3000,
            "stream": False,
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code in (401, 403):
                raise ProviderError(f"DeepSeek 鉴权失败（{exc.code}）：请检查 DEEPSEEK_API_KEY") from exc
            raise ProviderError(f"DeepSeek 返回 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"无法连接 DeepSeek：{exc.reason}") from exc
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("DeepSeek 响应结构异常") from exc
        return _loads_json_object(content)


def _loads_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ProviderError("模型返回的不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise ProviderError("模型返回的 JSON 必须是对象")
    return value


class MockProvider:
    """Deterministic offline storyboard for tests and dry runs."""

    name = "mock"

    def __init__(self, scenes: int = 4):
        self.scenes = scenes

    def complete_json(self, system: str, user: str) -> dict:
        captions = [
            "孩子们，今天这个话题有点意思。",
            "主包先替你看一眼，别急着划走。",
            "该说的都在这了，剩下的自己判断。",
            "觉得有用就点个关注，下期接着聊。",
            "这条就到这，别让主包等太久。",
            "有新活再喊我，今天先收工。",
            "看完了记得留个脚印，主包看得见。",
            "下一条更离谱，不信你等着。",
        ]
        template = "single"
        if "对话" in user or "双人" in user:
            template = "dialogue"
        elif "资讯" in user or "截图" in user:
            template = "news"
        count = max(1, min(self.scenes, len(captions)))
        each = 30.0 / count
        return {
            "title": "话题速览",
            "template": template,
            "scenes": [
                {
                    "duration": round(each, 2),
                    "characters": ["1001", "1002"] if template == "dialogue" and index % 2 else ["1001"],
                    "caption": captions[index],
                    "zoom": 0.015,
                }
                for index in range(count)
            ],
            "music": {"speed": 1.25, "volume": 0.65},
        }


def build_provider(name: str | None, model: str, project_root: Path | None = None) -> Provider:
    resolved = (name or os.environ.get("FATFISH_STORY_PROVIDER") or "deepseek").lower()
    if resolved == "mock":
        return MockProvider()
    if resolved == "deepseek":
        return DeepSeekProvider(resolve_api_key(project_root), model=model)
    raise ProviderError(f"未知的 provider：{resolved}，可选 deepseek 或 mock")
