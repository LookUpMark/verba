"""FastAPI app — full milestone 1-6 surface + the prototype UI at /.

Binds to 127.0.0.1 only. CORS is permissive for dev (SPA on another port);
under Tauri the sidecar serves the UI same-origin.
"""

from __future__ import annotations

import atexit
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from . import __version__
from .api import routes_chat, routes_lessons, routes_path, routes_review, routes_stats
from .config import settings
from .db import engine, get_session, init_db
from .models import ProfileEntry, RoleAssignment, RuntimeRecord
from .providers import discovery
from .providers.base import resolve_roles
from .seed.loader import seed_all
from .services import runtime_lifecycle

PROFILE_DEFAULTS: dict[str, str] = {
    "level": "",
    "xp": "0",
    "streak": "0",
    "goal_target": "20",
    "goal_done": "0",
    "theme": "",
    "ui_lang": "en",
    "onboarded": "",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        seed_all(session)
        await discovery.discover(session)
    # Probe the MLX runtime and spawn `omlx serve` if needed (never blocks
    # boot; only an app-owned server is killed on shutdown). Osusume pattern.
    runtime_lifecycle.ensure_llm_server()
    yield
    runtime_lifecycle.shutdown_backend()
    from .providers import lmstudio

    await lmstudio.close_clients()


# uvicorn owns the signal handlers, so SIGTERM skips exit hooks — atexit is
# the reliable last line of defense for killing an owned LLM server.
atexit.register(runtime_lifecycle.shutdown_backend)


app = FastAPI(title="Verba", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Explicit dev ports: browsers always include the port in the Origin header
    # and Starlette matches origins exactly, so a bare "http://localhost" never
    # matches a real dev SPA. Under Tauri the serving is same-origin; the Origin
    # guard below is what actually protects /api from hostile web pages.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:1420", "http://127.0.0.1:1420"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Local-only guard. The API is a localhost service without auth: CORS
    alone cannot stop a drive-by page, because simple cross-origin requests
    are *sent* regardless (only the response is unreadable). Every
    cross-origin POST carries an Origin header, and a DNS-rebinding page
    shows up in the Host header — both are rejected here, so a hostile web
    page can neither trigger state changes (shutdown, LLM generations) nor
    read responses. Stronger v0.2 option: shared-secret token passed from
    the Tauri shell to the sidecar via env and required on every /api call.
    """
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    origin = request.headers.get("origin", "")
    if origin:
        origin_host = urlparse(origin).hostname or ""
        if origin_host not in _LOCAL_HOSTS:
            return JSONResponse({"detail": "cross-origin requests are not allowed"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """CSP and content-type hardening. The webview loads the UI from this
    HTTP sidecar and Tauri's CSP is null, so this header is the only
    browser-side mitigation. Inline script/style stays allowed because the
    UI is one inline file; the point is blocking exfiltration channels
    (connect-src 'self') and plugin/base-uri abuse."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self' data:; object-src 'none'; base-uri 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

for router in (
    routes_path.router,
    routes_chat.router,
    routes_lessons.router,
    routes_review.router,
    routes_stats.router,
):
    app.include_router(router, prefix="/api")

# The validated UI prototype ships with the backend: same product, one file.
# Frozen sidecar: PyInstaller bundles it next to the binary (sys._MEIPASS,
# added by build-sidecar.py --add-data). Dev/editable: the repo root.
_INDEX_CANDIDATES = (
    Path(getattr(sys, "_MEIPASS", "")) / "static" / "index.html",
    Path(__file__).resolve().parents[2] / "index.html",
)
_INDEX = next((p for p in _INDEX_CANDIDATES if p.is_file()), _INDEX_CANDIDATES[-1])


@app.get("/")
def root() -> Any:
    if _INDEX.exists():
        return FileResponse(_INDEX, media_type="text/html")
    return {"app": "Verba", "docs": "/docs"}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version, "db": str(settings.db_path)}


def _runtimes_payload(session: Session) -> dict[str, Any]:
    rows = session.exec(select(RuntimeRecord)).all()
    return {
        "runtimes": [
            {
                "id": r.id,
                "name": r.name,
                "endpoint": r.endpoint,
                "status": r.status,
                "models": json.loads(r.models),
            }
            for r in rows
        ],
        "roles": resolve_roles(session),
    }


@app.get("/api/runtimes")
def list_runtimes(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _runtimes_payload(session)


@app.post("/api/runtimes/scan")
async def scan_runtimes(session: Session = Depends(get_session)) -> dict[str, Any]:
    await discovery.discover(session)
    return _runtimes_payload(session)


class RoleUpdate(BaseModel):
    role: Literal["tutor", "judge", "generator"]
    runtime: str
    model_id: str


@app.put("/api/roles")
def set_role(body: RoleUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    rt = session.get(RuntimeRecord, body.runtime)
    if rt is None or rt.status != "detected":
        raise HTTPException(status_code=404, detail=f"runtime '{body.runtime}' is not detected")
    known = {m["id"] for m in json.loads(rt.models)}
    if body.model_id not in known:
        raise HTTPException(status_code=400, detail=f"model '{body.model_id}' not available on '{body.runtime}'")
    row = session.get(RoleAssignment, body.role)
    if row is None:
        row = RoleAssignment(role=body.role)
    row.runtime = body.runtime
    row.model_id = body.model_id
    session.add(row)
    session.commit()
    return resolve_roles(session)


@app.get("/api/profile")
def get_profile(session: Session = Depends(get_session)) -> dict[str, str]:
    stored = {p.key: p.value for p in session.exec(select(ProfileEntry)).all()}
    out = dict(PROFILE_DEFAULTS)
    out.update(stored)
    return out


@app.post("/api/shutdown")
def shutdown() -> dict[str, str]:
    """Graceful stop, called by the desktop shell on quit.

    SIGTERM kills uvicorn without running its exit handlers (always on
    Windows), so the shell asks the server to stop itself first. Any LLM
    server this process spawned goes down with it.
    """
    runtime_lifecycle.shutdown_backend()
    server = getattr(app.state, "server", None)
    if server is None:
        raise HTTPException(status_code=409, detail="not running under a uvicorn.Server instance")
    server.should_exit = True
    return {"status": "stopping"}


def serve() -> None:
    import uvicorn

    uvicorn.run("verba.main:app", host="127.0.0.1", port=8000, reload=False)
