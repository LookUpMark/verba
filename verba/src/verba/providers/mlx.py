"""MLX adapter — `mlx-lm serve` exposes an OpenAI-compatible API, so the wire
format is identical to LM Studio. Only the default endpoint differs."""

from __future__ import annotations

from .lmstudio import LMStudioProvider


class MLXProvider(LMStudioProvider):
    pass
