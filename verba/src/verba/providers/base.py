"""LLMProvider protocol + role resolution.

Model ids are never hardcoded anywhere in Verba: roles resolve to whatever
the discovery pass actually found. Model selection is provisional and
user-deferred (see architecture.md §5 / §3).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import RoleAssignment, RuntimeRecord

ROLES: tuple[str, ...] = ("tutor", "judge", "generator")

# {"role": "...", "content": "..."}
Message = dict[str, str]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    runtime: str = ""
    fmt: str = "gguf"
    size_bytes: int | None = None


class LLMProvider(ABC):
    """One interface, four backends. See architecture.md §5."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        json_schema: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield content deltas. Pass json_schema for structured output."""
        ...  # pragma: no cover


def provider_for(runtime_id: str, base_url: str, model_id: str) -> LLMProvider:
    from .hf_local import HFLocalProvider
    from .lmstudio import LMStudioProvider
    from .mlx import MLXProvider
    from .ollama import OllamaProvider

    if runtime_id == "lmstudio":
        return LMStudioProvider(base_url, model_id)
    if runtime_id == "ollama":
        return OllamaProvider(base_url, model_id)
    if runtime_id == "mlx":
        return MLXProvider(base_url, model_id)
    if runtime_id == "hf":
        return HFLocalProvider()
    raise ValueError(f"unknown runtime: {runtime_id}")


def detected_models(session: Session) -> list[ModelInfo]:
    rows = session.exec(select(RuntimeRecord).where(RuntimeRecord.status == "detected")).all()
    out: list[ModelInfo] = []
    for row in rows:
        for m in json.loads(row.models):
            out.append(ModelInfo(runtime=row.id, **m))
    return out


def resolve_roles(session: Session) -> dict[str, dict[str, str]]:
    """role -> {runtime, model}. Explicit assignments win when the model is
    still detected; the rest auto-assign: largest -> judge, next -> tutor,
    smallest -> generator (cycling when fewer models than roles)."""
    models = detected_models(session)
    stored = {a.role: a for a in session.exec(select(RoleAssignment)).all()}
    ranked = sorted(models, key=lambda m: m.size_bytes or 0, reverse=True)
    result: dict[str, dict[str, str]] = {}
    for i, role in enumerate(("judge", "tutor", "generator")):
        a = stored.get(role)
        if a is not None and any(m.runtime == a.runtime and m.id == a.model_id for m in models):
            result[role] = {"runtime": a.runtime, "model": a.model_id}
        elif ranked:
            m = ranked[i % len(ranked)]
            result[role] = {"runtime": m.runtime, "model": m.id}
    return result
