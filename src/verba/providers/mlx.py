"""MLX adapter — oMLX (PrismML) and `mlx-lm serve` expose an OpenAI-compatible
API, so the wire format matches LM Studio. Differences handled here:

- Bearer auth from the local oMLX install (~/.omlx/settings.json),
- thinking-capable chat templates (Qwen & co. burn the token budget on
  invisible reasoning): thinking is disabled server-side and any leftover
  <think> span is stripped from the stream, even when split across chunks.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx

from ..config import settings
from .base import Message, ModelInfo
from .lmstudio import LMStudioProvider

_OPEN = "<think>"
_CLOSE = "</think>"

# A freshly spawned oMLX server serves /v1/models before its chat routes come
# up (~404 for a while on a cold model scan). Retry briefly instead of failing
# the very first tutor/judge/generator call of a session. ReadTimeout rides on
# TransportError and each attempt can already wait up to 120s, so the whole
# sequence is capped by a monotonic deadline instead of the delay ladder alone.
_RETRY_DELAYS = (1.0, 3.0, 7.0, 15.0, 30.0)
# Cold model loads on a local server can refuse/hold connections for a couple
# of minutes — the deadline must outlast the load, not just the warm-up.
_RETRY_DEADLINE_S = 180.0


def _partial_tag_suffix(text: str, tag: str) -> int:
    """Length of the longest suffix of `text` that is a strict prefix of `tag`."""
    for k in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:k]):
            return k
    return 0


class _ThinkStripper:
    """Streaming <think>...</think> remover; tags may split across chunks."""

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""

    def feed(self, chunk: str) -> str:
        buf = self._pending + chunk
        self._pending = ""
        out: list[str] = []
        while True:
            tag = _CLOSE if self._inside else _OPEN
            idx = buf.find(tag)
            if idx != -1:
                if not self._inside:
                    out.append(buf[:idx])
                self._inside = not self._inside
                buf = buf[idx + len(tag):]
                continue
            keep = _partial_tag_suffix(buf, tag)
            if keep:
                self._pending = buf[-keep:]
                buf = buf[:-keep]
            if not self._inside:
                out.append(buf)
            return "".join(out)


class MLXProvider(LMStudioProvider):
    def __init__(self, base_url: str, model_id: str) -> None:
        headers = None
        if settings.mlx_api_key:
            headers = {"Authorization": f"Bearer {settings.mlx_api_key}"}
        super().__init__(
            base_url,
            model_id,
            headers=headers,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

    async def list_models(self) -> list[ModelInfo]:
        models = await super().list_models()
        return [ModelInfo(id=m.id, runtime="mlx", fmt="mlx") for m in models]

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        stripper = _ThinkStripper()
        attempt = 0
        deadline = time.monotonic() + _RETRY_DEADLINE_S
        while True:
            gen = super().complete(
                messages, model=model, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens
            )
            try:
                first = await gen.__anext__()
            except StopAsyncIteration:
                return
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                transient = status in (404, 502, 503) or isinstance(e, httpx.TransportError)
                if transient and attempt < len(_RETRY_DELAYS) and time.monotonic() < deadline:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    attempt += 1
                    continue
                raise
            if cleaned := stripper.feed(first):
                yield cleaned
            async for chunk in gen:
                if cleaned := stripper.feed(chunk):
                    yield cleaned
            return
