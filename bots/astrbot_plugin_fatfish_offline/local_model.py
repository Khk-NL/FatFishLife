"""Local Ollama client for the offline brain.

No AstrBot imports, so the module can be tested and reused outside the plugin.
The model is loaded on demand and unloaded with ``keep_alive=0``; the base URL
and model name come from config so the same code works on a server.
"""

from __future__ import annotations

import httpx


class LocalModel:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:1.5b",
        timeout: float = 30.0,
        enabled: bool = True,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.enabled = enabled and bool(self.base_url) and bool(model)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def chat(
        self,
        system: str,
        user: str,
        *,
        keep_alive: str | int = "5m",
        num_predict: int = 48,
    ) -> str | None:
        if not self.enabled:
            return None
        try:
            response = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": 0.75,
                        "num_predict": num_predict,
                        "top_p": 0.9,
                    },
                },
            )
            if response.status_code != 200:
                return None
            text = (response.json().get("message") or {}).get("content") or ""
            return text.strip() or None
        except Exception:
            return None

    async def warmup(self) -> None:
        if not self.enabled:
            return
        try:
            await self._client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": "", "keep_alive": "10m"},
            )
        except Exception:
            pass

    async def unload(self) -> None:
        if not self.enabled:
            return
        try:
            await self._client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": "", "keep_alive": 0},
            )
        except Exception:
            pass

    async def close(self) -> None:
        await self._client.aclose()
