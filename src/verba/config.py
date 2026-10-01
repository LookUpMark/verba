"""Central configuration. Nothing else hardcodes a path or endpoint."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _omlx_defaults() -> dict:
    """Read the local oMLX (PrismML) install: server port + API key.

    oMLX serves an OpenAI-compatible API that requires Bearer auth; without
    the key every probe 401s and the runtime would look 'missing'. The key
    stays in memory only — never logged, never persisted by Verba.
    """
    path = Path.home() / ".omlx" / "settings.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    out: dict = {}
    with contextlib.suppress(KeyError, TypeError, ValueError):
        out["port"] = int(data["server"]["port"])
    key = (data.get("auth") or {}).get("api_key")
    if isinstance(key, str) and key:
        out["api_key"] = key
    return out


@dataclass(frozen=True)
class ProbeEndpoint:
    runtime_id: str
    name: str
    base_url: str
    headers: dict[str, str] | None = None
    timeout_s: float | None = None


@dataclass(frozen=True)
class Settings:
    db_path: Path
    probe_timeout_s: float
    probes: tuple[ProbeEndpoint, ...]
    mlx_api_key: str | None = None


def load_settings() -> Settings:
    db_path = Path(_env("VERBA_DB", str(Path.home() / ".verba" / "verba.db")))
    omlx = _omlx_defaults()
    mlx_base = _env("VERBA_MLX_ENDPOINT", f"http://127.0.0.1:{omlx.get('port', 8080)}/v1")
    mlx_headers = {"Authorization": f"Bearer {omlx['api_key']}"} if "api_key" in omlx else None
    probes = (
        ProbeEndpoint("lmstudio", "LM Studio", _env("VERBA_LMSTUDIO_ENDPOINT", "http://127.0.0.1:1234/v1")),
        ProbeEndpoint("ollama", "Ollama", _env("VERBA_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")),
        # oMLX answers slowly while busy generating (a miss would make callers
        # spawn a duplicate server), hence the generous probe timeout.
        ProbeEndpoint("mlx", "MLX (oMLX)", mlx_base, headers=mlx_headers, timeout_s=4.0),
    )
    return Settings(
        db_path=db_path,
        probe_timeout_s=float(_env("VERBA_PROBE_TIMEOUT", "0.8")),
        probes=probes,
        mlx_api_key=omlx.get("api_key"),
    )


settings = load_settings()
