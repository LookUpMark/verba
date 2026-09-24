"""PyInstaller entrypoint for the Verba sidecar.

Picks a free localhost port, serves verba.main:app under an explicit
uvicorn.Server (so POST /api/shutdown can stop it gracefully — the shell
calls it before SIGTERM on quit), and announces readiness on stdout so the
Tauri shell can open the window (see src/main.rs).
"""

from __future__ import annotations

import socket
import sys


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    port = free_port()
    # Imports stay here so PyInstaller picks them up from the installed package.
    import uvicorn

    from verba.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    app.state.server = server

    print(f"VERBA_READY port={port}", flush=True)
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
