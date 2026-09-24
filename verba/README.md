# Verba backend — milestone 1

LLM provider layer, runtime discovery and the Models/Profile endpoints.
Spec: `../architecture.md` (§5 provider layer, §6 endpoints, §4 data model).
Model selection is **provisional**: no model id is hardcoded — roles resolve
to whatever the local runtimes actually expose.

## Run

```sh
cd verba
python3.12 -m venv .venv && source .venv/bin/activate    # or: uv venv
pip install -e .
verba                       # = uvicorn verba.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs>.

With LM Studio (`:1234`) or Ollama (`:11434`) running, `GET /api/runtimes`
lists the detected models and assigns judge/tutor/generator automatically
(largest → judge, next → tutor, smallest → generator). Override any role
with `PUT /api/roles`.

## Configuration (env vars)

| Var | Default |
|---|---|
| `VERBA_DB` | `~/.verba/verba.db` |
| `VERBA_LMSTUDIO_ENDPOINT` | `http://127.0.0.1:1234/v1` |
| `VERBA_OLLAMA_ENDPOINT` | `http://127.0.0.1:11434` |
| `VERBA_MLX_ENDPOINT` | `http://127.0.0.1:8080/v1` (mlx-lm serve) |
| `VERBA_PROBE_TIMEOUT` | `0.8` (seconds) |

Nothing leaves localhost. If no runtime answers at startup, the app starts in
degraded mode and `POST /api/runtimes/scan` re-probes anytime.

## Packaging (desktop app)

One installable per OS: a Tauri v2 window pointing at the FastAPI backend,
which ships as a single PyInstaller binary (`verba-server`) picked as a
sidecar. The sidecar picks a free port, prints `VERBA_READY port=<n>` on
stdout, and the shell opens the window on that port
(`desktop/src-tauri/src/main.rs`). The Python package is untouched by the shell.

Prerequisites: Rust (stable), Python 3.12, and on Linux
`libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf`.

```sh
# 1. sidecar binary for the current platform
pip install -e ./verba pyinstaller
python verba/desktop/build-sidecar.py     # -> desktop/src-tauri/binaries/verba-server-<triple>

# 2. app icons (one-time, requires a source PNG)
cargo tauri icon path/to/app-icon.png     # writes desktop/src-tauri/icons/

# 3. dev window (expects the sidecar already built)
cargo run                                  # in verba/desktop/src-tauri

# 4. full installers for this OS
cargo tauri build                          # dmg/app | msi/nsis | deb/appimage
```

CI/CD (`.github/workflows/`):

- **CI** — `ci.yml` on push/PR: `ruff check`, sidecar smoke build, `cargo check`
  on the three OS matrix rows.
- **Release** — `release.yml` on tag `v*`: reads the version from
  `verba/pyproject.toml`, builds sidecar + installers on
  macOS (arm64 + x86_64), Windows and Linux, attaches dmg/msi/exe/deb/AppImage
  to a draft GitHub Release, then publishes it.

Optional secrets: `MACOS_CERTIFICATE` + `MACOS_CERTIFICATE_PWD` +
`KEYCHAIN_PASSWORD` (codesign/notarize), `TAURI_SIGNING_PRIVATE_KEY` (+password)
for the updater manifest. Replace `OWNER` in `tauri.conf.json` and generate the
updater pubkey with `cargo tauri signer generate`. Without them, builds ship
unsigned and the updater stays off — everything else works.

