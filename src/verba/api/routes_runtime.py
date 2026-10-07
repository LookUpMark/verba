"""Runtime setup wizard: per-runtime actionable state, start servers, pull models (§6)."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..config import settings
from ..db import get_session
from ..providers import discovery
from ..services import runtime_lifecycle
from ..services.runtime_lifecycle import _LMS_CLI, _OMLX_CLI, _OMLX_MODELS

router = APIRouter()

_PULL_JOBS: dict[str, dict[str, Any]] = {}
_PULL_LOCK = threading.Lock()

# The suggested starter model: small, strong on structured output, multi-platform.
SUGGESTED_MODEL = "qwen3:8b"


def _probe_base(runtime_id: str) -> str:
    return next(p for p in settings.probes if p.runtime_id == runtime_id).base_url.rstrip("/")


def _probe_ok(runtime_id: str) -> bool:
    # Reuse the configured probe (oMLX requires Bearer auth — a bare GET is a 401).
    probe = next(p for p in settings.probes if p.runtime_id == runtime_id)
    try:
        path = "/api/tags" if runtime_id == "ollama" else "/models"
        r = httpx.get(f"{probe.base_url.rstrip('/')}{path}", headers=probe.headers, timeout=probe.timeout_s or 1.5)
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def _rt(id_: str) -> dict[str, Any]:
    probe = next(p for p in settings.probes if p.runtime_id == id_)
    return {"id": id_, "name": probe.name, "endpoint": probe.base_url, "server_up": _probe_ok(id_)}


@router.get("/runtime/setup")
def setup_state() -> dict[str, Any]:
    """Actionable per-runtime state for the Models screen setup card."""
    mlx_cli = _OMLX_CLI.exists() or bool(shutil.which("omlx"))
    omlx_models = _OMLX_MODELS.is_dir() and any(_OMLX_MODELS.iterdir())
    return {
        "omlx": {
            **_rt("mlx"),
            "cli": mlx_cli,
            "models_present": bool(omlx_models),
            "hint": "Verba starts and stops the oMLX server with the app; put MLX models under ~/.omlx/models."
            if mlx_cli
            else "Install oMLX (prismml.com) — Verba will then start it automatically with the app.",
        },
        "ollama": {
            **_rt("ollama"),
            "cli": bool(shutil.which("ollama")),
            "suggested_model": SUGGESTED_MODEL,
            "hint": "Start it here and pull a model — no terminal needed."
            if shutil.which("ollama")
            else "Install Ollama (ollama.com); the start and model-pull buttons appear here once the CLI is on PATH.",
        },
        "lmstudio": {
            **_rt("lmstudio"),
            "cli": bool(shutil.which("lms")) or _LMS_CLI.exists(),
            "hint": "Start the server here via the lms CLI, or from the LM Studio app, and load a model."
            if shutil.which("lms") or _LMS_CLI.exists()
            else "Install LM Studio (lmstudio.ai), enable its local server, and load a model.",
        },
    }


class PullBody(BaseModel):
    model: str = SUGGESTED_MODEL


@router.post("/runtime/ollama/start")
def start_ollama() -> dict[str, str]:
    return runtime_lifecycle.start_ollama()


@router.post("/runtime/lmstudio/start")
def start_lmstudio() -> dict[str, str]:
    return runtime_lifecycle.start_lmstudio()


@router.post("/runtime/ollama/pull")
def pull_model(body: PullBody) -> dict[str, str]:
    if not shutil.which("ollama"):
        raise HTTPException(status_code=409, detail="Ollama CLI not found")
    if not _probe_ok("ollama"):
        raise HTTPException(status_code=409, detail="Ollama server is not running — start it first")
    job_id = uuid.uuid4().hex
    with _PULL_LOCK:
        _PULL_JOBS[job_id] = {"status": "pulling", "model": body.model, "percent": 0, "error": ""}
    threading.Thread(target=_pull_worker, args=(job_id, body.model), daemon=True).start()
    return {"job_id": job_id}


@router.get("/runtime/ollama/pull/{job_id}")
def pull_status(job_id: str) -> dict[str, Any]:
    with _PULL_LOCK:
        job = _PULL_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown pull job")
        return dict(job)


@router.post("/runtime/rescan")
async def rescan(session: Session = Depends(get_session)) -> dict[str, Any]:
    return await discovery.discover(session)


def _pull_worker(job_id: str, model: str) -> None:
    """Stream the Ollama pull, aggregating layer progress into one percentage."""
    layers: dict[str, tuple[int, int]] = {}
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=10.0)) as client,
            client.stream("POST", f"{_probe_base('ollama')}/api/pull", json={"model": model, "stream": True}) as r,
        ):
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if err := event.get("error"):
                    raise RuntimeError(err)
                if event.get("digest"):
                    layers[event["digest"]] = (int(event.get("total", 0)), int(event.get("completed", 0)))
                    total = sum(t for t, _ in layers.values())
                    completed = sum(c for _, c in layers.values())
                    with _PULL_LOCK:
                        _PULL_JOBS[job_id]["percent"] = int(100 * completed / total) if total else 0
                elif event.get("status") == "success":
                    with _PULL_LOCK:
                        _PULL_JOBS[job_id].update(status="success", percent=100)
                    return
        raise RuntimeError("pull stream ended without success")
    except Exception as e:  # noqa: BLE001 — surfaced to the UI via the job status
        with _PULL_LOCK:
            _PULL_JOBS[job_id].update(status="error", error=str(e))
