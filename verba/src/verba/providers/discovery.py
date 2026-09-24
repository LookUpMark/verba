"""Startup probe: poll local runtimes, upsert rows in `runtimes`.

Degraded mode is a normal state: no detected runtime means the app still
boots and `POST /api/runtimes/scan` re-probes anytime (architecture.md §5).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlmodel import Session

from ..config import settings
from ..models import RuntimeRecord
from .base import ModelInfo


async def _probe_openai(client: httpx.AsyncClient, base_url: str) -> list[ModelInfo]:
    r = await client.get(f"{base_url.rstrip('/')}/models")
    r.raise_for_status()
    return [ModelInfo(id=m["id"]) for m in r.json().get("data", [])]


async def _probe_ollama(client: httpx.AsyncClient, base_url: str) -> list[ModelInfo]:
    r = await client.get(f"{base_url.rstrip('/')}/api/tags")
    r.raise_for_status()
    return [
        ModelInfo(id=m["name"], fmt="gguf", size_bytes=int(m.get("size", 0)))
        for m in r.json().get("models", [])
    ]


async def discover(session: Session) -> dict[str, Any]:
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=settings.probe_timeout_s) as client:
        for probe in settings.probes:
            try:
                if probe.runtime_id == "ollama":
                    models = await _probe_ollama(client, probe.base_url)
                else:
                    models = await _probe_openai(client, probe.base_url)
            except Exception:
                models = []

            record = session.get(RuntimeRecord, probe.runtime_id)
            if record is None:
                record = RuntimeRecord(id=probe.runtime_id, name=probe.name, endpoint=probe.base_url)
            record.status = "detected" if models else "missing"
            record.models = json.dumps([{"id": m.id, "fmt": m.fmt, "size_bytes": m.size_bytes} for m in models])
            session.add(record)
            results[probe.runtime_id] = {"status": record.status, "models": [m.id for m in models]}
    session.commit()
    return results
