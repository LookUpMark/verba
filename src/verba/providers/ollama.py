"""Ollama adapter — native API (default :11434), NDJSON streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator


from .base import LLMProvider, Message, ModelInfo
from .lmstudio import _shared_client


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id

    async def list_models(self) -> list[ModelInfo]:
        client = _shared_client(self.base_url)
        r = await client.get(f"{self.base_url}/api/tags", timeout=2.0)
        r.raise_for_status()
        return [
            ModelInfo(id=m["name"], runtime="ollama", fmt="gguf", size_bytes=int(m.get("size", 0)))
            for m in r.json().get("models", [])
        ]

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        body: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            body["format"] = json_schema
        client = _shared_client(self.base_url)
        async with client.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("done"):
                    return
                if text := chunk.get("message", {}).get("content"):
                    yield text
