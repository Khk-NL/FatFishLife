"""Local Ollama or OpenAI-compatible client for the offline brain.

No AstrBot imports, so the module can be tested and reused outside the plugin.
Ollama models load on demand and unload with ``keep_alive=0``. The shared
llama.cpp context server unloads model memory after its configured idle timeout
and wakes automatically for native chat compression or offline replies.
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
        api_key: str = "",
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.enabled = enabled and bool(self.base_url) and bool(model)
        self.openai = self.base_url.endswith("/v1")
        self.headers = {"Authorization":"Bearer " + api_key} if api_key else {}
        self._client = httpx.AsyncClient(timeout=timeout)

    async def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            response = await self._client.get(self.base_url + ("/models" if self.openai else "/api/tags"), headers=self.headers)
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
            if self.openai:
                response = await self._client.post(self.base_url + "/chat/completions", headers=self.headers,
                    json={"model":self.model, "messages":[{"role":"system","content":system},{"role":"user","content":user}],
                          "max_tokens":num_predict, "temperature":.7})
                response.raise_for_status()
                return str(response.json()["choices"][0]["message"]["content"]).strip() or None
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
        if self.openai:
            await self.available()
            return
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
        if self.openai:
            # The shared server also handles chat summaries: its native idle
            # sleep releases memory safely without killing concurrent requests.
            return
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
