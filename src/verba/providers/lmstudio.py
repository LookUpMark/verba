"""LM Studio adapter — OpenAI-compatible endpoint (default :1234/v1)."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator

import httpx

from .base import LLMProvider, Message, ModelInfo

# One pooled client per endpoint, shared across role calls: a fresh client
# per complete() paid TCP setup on every tutor turn (the hot path). Closed
# from the app lifespan via close_clients().
_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _shared_client(base_url: str) -> httpx.AsyncClient:
    client = _CLIENTS.get(base_url)
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=10.0))
        _CLIENTS[base_url] = client
    return client


async def close_clients() -> None:
    for c in _CLIENTS.values():
        with contextlib.suppress(Exception):
            await c.aclose()
    _CLIENTS.clear()


class LMStudioProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model_id: str,
        *,
        headers: dict[str, str] | None = None,
        extra_body: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.headers = headers
        self.extra_body = extra_body or {}

    async def list_models(self) -> list[ModelInfo]:
        client = _shared_client(self.base_url)
        r = await client.get(f"{self.base_url}/models", headers=self.headers, timeout=4.0)
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
        body.update(self.extra_body)
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": json_schema},
            }
        client = _shared_client(self.base_url)
        async with client.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=self.headers) as r:
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
