"""LLM runtime lifecycle — "open with the app, close with the app" for oMLX.

Pattern ported from the Osusume reference app: the backend (not the desktop
shell) owns the local LLM server. At startup it probes the configured MLX
endpoint; if nothing answers and a local oMLX install exists (CLI + models),
it spawns `omlx serve` detached in its own session and tracks it as *owned*.
On shutdown only an owned server is killed (SIGTERM to the whole process
group) — a server someone else started (e.g. another app) is left alone.

Degraded mode stays a normal state: no oMLX install, no spawn, no errors.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import settings
from ..db import engine

_OMLX_CLI = Path.home() / ".omlx" / "bin" / "omlx"
_OMLX_MODELS = Path.home() / ".omlx" / "models"
_LOG = Path.home() / ".verba" / "llm.log"

_lock = threading.Lock()
_state = "off"  # off | starting | up
_owned: tuple[subprocess.Popen[Any], Any] | None = None  # (child, open log handle)


def _mlx_probe() -> httpx.Request | None:
    probe = next(p for p in settings.probes if p.runtime_id == "mlx")
    return probe


def _mlx_base() -> str:
    return _mlx_probe().base_url.rstrip("/")


def _mlx_headers() -> dict[str, str] | None:
    return _mlx_probe().headers


def _probe_ok(timeout: float = 4.0) -> bool:
    try:
        r = httpx.get(f"{_mlx_base()}/models", headers=_mlx_headers(), timeout=timeout)
        return r.status_code < 400  # a 404 here means the server is still warming up
    except httpx.HTTPError:
        return False


def _omlx_available() -> bool:
    cli = str(_OMLX_CLI) if _OMLX_CLI.exists() else None
    if cli is None:
        import shutil

        cli = shutil.which("omlx")
    if cli is None:
        return False
    if not _OMLX_MODELS.is_dir():
        return False
    return any(p.is_dir() for org in _OMLX_MODELS.iterdir() for p in org.iterdir())


def _spawn_omlx() -> tuple[subprocess.Popen[Any], Any]:
    port = urlparse(_mlx_base()).port or 8080
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = _LOG.open("a", buffering=1)
    logf.write(f"--- verba spawning omlx serve on 127.0.0.1:{port}\n")
    child = subprocess.Popen(  # noqa: S603 — fixed local CLI, fixed args
        [str(_OMLX_CLI if _OMLX_CLI.exists() else "omlx"), "serve", "--host", "127.0.0.1", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=logf,
        start_new_session=True,  # own process group: killpg reaches the whole tree
    )
    return child, logf


def _wait_until_up(child: subprocess.Popen[Any], budget_s: float = 150.0) -> bool:
    # Time-based budget: the old attempts×step ladder multiplied by the
    # generous 4s probe timeout could reach ~6 minutes. A short probe timeout
    # is enough here — the child was just spawned, an up server answers fast.
    import time

    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        if child.poll() is not None:  # died (port clash, bad config, ...)
            return False
        if _probe_ok(timeout=1.0):
            return True
        threading.Event().wait(2.0)
    return False


def _refresh_discovery() -> None:
    import asyncio

    from sqlmodel import Session

    from ..providers import discovery

    def run() -> None:
        with Session(engine) as session:
            asyncio.run(discovery.discover(session))

    threading.Thread(target=run, daemon=True).start()


def _worker() -> None:
    global _state, _owned
    with _lock:
        if _state != "off":
            return
        _state = "starting"
    if os.environ.get("VERBA_LLM_SPAWN", "1") == "0":  # hermetic tests / explicit opt-out
        _state = "off"
        return
    try:
        if _probe_ok():
            _state = "up"  # someone else's server — use it, never kill it
            return
        if not _omlx_available():
            _state = "off"
            return
        child, logf = _spawn_omlx()
        _owned = (child, logf)
        if _wait_until_up(child):
            _state = "up"
            _refresh_discovery()  # discovery ran before the server answered
        else:
            shutdown_backend()
    except Exception as e:  # noqa: BLE001 — lifecycle must never break boot
        print(f"[verba] llm lifecycle error: {e}", flush=True)
        with _lock:
            _state = "off"


def ensure_llm_server() -> None:
    """Fire-and-forget: probe, spawn if needed. Never blocks startup."""
    threading.Thread(target=_worker, daemon=True).start()


def shutdown_backend() -> None:
    """Kill the LLM server, but only the one this process spawned."""
    global _owned, _state
    with _lock:
        owned, _owned = _owned, None
        _state = "off"
    if owned is None:
        return
    child, logf = owned
    if hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError, PermissionError, AttributeError):
            os.killpg(os.getpgid(child.pid), signal.SIGTERM)
    else:  # pragma: no cover — Windows has no process groups
        child.terminate()
    # Reap and escalate: without wait() the SIGTERM'd child stays a zombie
    # until our own exit, and a server slow to die would survive holding the
    # port and the GPU memory while the next boot misreads it as foreign.
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError, AttributeError):
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            else:  # pragma: no cover
                child.kill()
        with contextlib.suppress(Exception):
            child.wait(timeout=5)
    with contextlib.suppress(OSError):
        logf.close()
