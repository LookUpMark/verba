"""In-process HF transformers fallback — deliberately not wired in milestone 1.

HTTP runtimes (LM Studio / Ollama / MLX) cover the provider layer; the HF
backend lands with milestone 2 together with outlines-constrained decoding.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import LLMProvider, Message, ModelInfo


class HFLocalProvider(LLMProvider):
    async def list_models(self) -> list[ModelInfo]:
        return []

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        raise NotImplementedError(
            "The HF transformers backend lands in milestone 2 (outlines-constrained decoding). "
            "Point VERBA_LMSTUDIO_ENDPOINT / VERBA_OLLAMA_ENDPOINT / VERBA_MLX_ENDPOINT at a local runtime instead."
        )
