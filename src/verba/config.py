"""Central configuration. Nothing else hardcodes a path or endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class ProbeEndpoint:
    runtime_id: str
    name: str
    base_url: str


@dataclass(frozen=True)
class Settings:
    db_path: Path
    probe_timeout_s: float
    probes: tuple[ProbeEndpoint, ...]


def load_settings() -> Settings:
    db_path = Path(_env("VERBA_DB", str(Path.home() / ".verba" / "verba.db")))
    probes = (
        ProbeEndpoint("lmstudio", "LM Studio", _env("VERBA_LMSTUDIO_ENDPOINT", "http://127.0.0.1:1234/v1")),
        ProbeEndpoint("ollama", "Ollama", _env("VERBA_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")),
        ProbeEndpoint("mlx", "MLX server", _env("VERBA_MLX_ENDPOINT", "http://127.0.0.1:8080/v1")),
    )
    return Settings(
        db_path=db_path,
        probe_timeout_s=float(_env("VERBA_PROBE_TIMEOUT", "0.8")),
        probes=probes,
    )


settings = load_settings()
