"""LM Studio adapter — OpenAI-compatible endpoint (default :1234/v1)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .base import LLMProvider, Message, ModelInfo


class LMStudioProvider(LLMProvider):
    def __init__(self, base_url: str, model_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{self.base_url}/models")
            r.raise_for_status()
            return [ModelInfo(id=m["id"], runtime="lmstudio") for m in r.json().get("data", [])]

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": json_schema},
            }
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):]
                    if payload.strip() == "[DONE]":
                        return
                    delta = json.loads(payload)["choices"][0]["delta"]
                    if chunk := delta.get("content"):
                        yield chunk
