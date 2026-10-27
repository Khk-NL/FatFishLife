"""本地模型客户端：峰谷切换时用。

优先 MiniCPM5-2B（llama-server，6193），备用 Ollama qwen2.5:1.5b。
只做一件事：给一段 system + user，拿回文本。不带任何 AstrBot 依赖。

环境变量：
    FATFISH_LOCAL_LLM_URL / MODEL / KEY_FILE    主用（llama-server）
    FATFISH_OLLAMA_URL / MODEL                  备用
    FATFISH_LOCAL_LLM_TIMEOUT                   默认 30 秒
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class LocalLLMError(RuntimeError):
    pass


def _key() -> str:
    path = os.environ.get("FATFISH_LOCAL_LLM_KEY_FILE", "").strip()
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get("FATFISH_LOCAL_LLM_KEY", "").strip()


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:160]
        except OSError:
            pass
        raise LocalLLMError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise LocalLLMError(f"本地模型请求失败：{exc}") from exc


def chat(system: str, user: str, *, max_tokens: int = 300, timeout: float | None = None) -> str:
    """先试 MiniCPM，失败退 Ollama；都失败抛错。"""
    limit = float(timeout or os.environ.get("FATFISH_LOCAL_LLM_TIMEOUT", "30"))
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    base = os.environ.get("FATFISH_LOCAL_LLM_URL", "").strip()
    model = os.environ.get("FATFISH_LOCAL_LLM_MODEL", "fatfish-context").strip()
    if base:
        try:
            data = _post(
                base.rstrip("/") + "/chat/completions",
                {"model": model, "messages": messages, "max_tokens": max_tokens},
                {"Authorization": f"Bearer {_key()}"},
                limit,
            )
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if text.strip():
                return text.strip()
        except LocalLLMError:
            pass

    ollama = os.environ.get("FATFISH_OLLAMA_URL", "").strip()
    if ollama:
        data = _post(
            ollama.rstrip("/") + "/api/chat",
            {
                "model": os.environ.get("FATFISH_OLLAMA_MODEL", "qwen2.5:1.5b"),
                "messages": messages,
                "stream": False,
                "keep_alive": 0,
            },
            {},
            limit,
        )
        text = (data.get("message") or {}).get("content") or ""
        if text.strip():
            return text.strip()

    raise LocalLLMError("本地模型均不可用")


def probe() -> dict:
    """连通性检查，两个后端分别报状态。"""
    out = {}
    base = os.environ.get("FATFISH_LOCAL_LLM_URL", "").strip()
    if base:
        try:
            out["minicpm"] = {"ok": True, "reply": chat("", "说一个字")[:20]}
        except LocalLLMError as exc:
            out["minicpm"] = {"ok": False, "error": str(exc)}
    ollama = os.environ.get("FATFISH_OLLAMA_URL", "").strip()
    if ollama:
        try:
            data = _post(
                ollama.rstrip("/") + "/api/chat",
                {"model": os.environ.get("FATFISH_OLLAMA_MODEL", "qwen2.5:1.5b"),
                 "messages": [{"role": "user", "content": "hi"}], "stream": False, "keep_alive": 0},
                {}, 20,
            )
            out["ollama"] = {"ok": bool((data.get("message") or {}).get("content"))}
        except LocalLLMError as exc:
            out["ollama"] = {"ok": False, "error": str(exc)}
    return out
