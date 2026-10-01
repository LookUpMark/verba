"""MLX adapter — oMLX (PrismML) and `mlx-lm serve` expose an OpenAI-compatible
API, so the wire format matches LM Studio. Differences handled here:

- Bearer auth from the local oMLX install (~/.omlx/settings.json),
- thinking-capable chat templates (Qwen & co. burn the token budget on
  invisible reasoning): thinking is disabled server-side and any leftover
  <think> span is stripped from the stream, even when split across chunks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..config import settings
from .base import Message, ModelInfo
from .lmstudio import LMStudioProvider

_OPEN = "<think>"
_CLOSE = "</think>"


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
        async for chunk in super().complete(
            messages, model=model, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens
        ):
            if cleaned := stripper.feed(chunk):
                yield cleaned
