"""Build the Verba sidecar binary for the current platform with PyInstaller.

Output: verba/desktop/src-tauri/binaries/verba-server-<target-triple>[.exe]
The name matches what Tauri expects for `bundle.externalBin` (it appends the
target triple at bundle time).

Prerequisites: `pip install -e ./verba pyinstaller` from the repo root.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "src-tauri" / "binaries"


def target_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if system == "Darwin":
        return f"{arch}-apple-darwin"
    if system == "Windows":
        return f"{arch}-pc-windows-msvc"
    return f"{arch}-unknown-linux-gnu"


def main() -> int:
    triple = target_triple()
    ext = ".exe" if platform.system() == "Windows" else ""
    name = f"verba-server-{triple}"
    DIST.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(DIST),
        "--workpath",
        str(HERE / "build"),
        "--specpath",
        str(HERE / "build"),
        # The verba package must be importable (pip install -e ./verba).
        "--paths",
        str(HERE.parent / "src"),
        str(HERE / "sidecar_entry.py"),
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"sidecar ready: {DIST / (name + ext)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
