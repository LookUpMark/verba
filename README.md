# Verba backend — milestone 1

LLM provider layer, runtime discovery and the Models/Profile endpoints.
Spec: `architecture.md` (§5 provider layer, §6 endpoints, §4 data model).
Model selection is **provisional**: no model id is hardcoded — roles resolve
to whatever the local runtimes actually expose.

## Run

```sh
python3.12 -m venv .venv && source .venv/bin/activate    # or: uv venv
pip install -e .
verba                       # = uvicorn verba.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs>.

With LM Studio (`:1234`), Ollama (`:11434`) or oMLX (`:8080`, Bearer auth
read from `~/.omlx/settings.json`) running, `GET /api/runtimes` lists the
detected models and assigns judge/tutor/generator automatically (largest →
judge, next → tutor, smallest → generator). Override any role with
`PUT /api/roles`. If nothing is listening on the MLX port but an oMLX
install exists, the backend spawns `omlx serve` itself and stops it on
shutdown (only the server it started — the Osusume pattern).

## First run — end-to-end verification

```sh
# 1. backend (Python 3.12)
uv venv && uv pip install -e . && verba     # binds 127.0.0.1:8000

# 2. LLM runtime: start LM Studio's server, `ollama serve`, or just rely on
#    the oMLX auto-spawn above, then check detection + roles:
curl -s http://127.0.0.1:8000/api/runtimes | python3 -m json.tool

# 3. curriculum skeleton (11 missions A1-B2) + the UI on /
curl -s http://127.0.0.1:8000/api/path | python3 -m json.tool
open http://127.0.0.1:8000/

# 4. one mission, end to end (tasks are LLM-generated on first open)
MID=$(curl -s http://127.0.0.1:8000/api/path | python3 -c "import json,sys;print(json.load(sys.stdin)['current'])")
curl -s -X POST http://127.0.0.1:8000/api/missions/$MID/start | python3 -m json.tool
#    ... answer the six tasks via POST /api/attempts {task_id, answer, latency_ms}
#    ... then POST /api/missions/$MID/complete {correct, total}

# 5. tutor chat (SSE): session, message with classic Italian-speaker errors, stream
SID=$(curl -s -X POST http://127.0.0.1:8000/api/chat/sessions -H 'Content-Type: application/json' -d '{"scenario":"airport"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -X POST http://127.0.0.1:8000/api/chat/sessions/$SID/messages -H 'Content-Type: application/json' -d '{"text":"I am agree with you, and I have 25 years."}' >/dev/null
curl -N http://127.0.0.1:8000/api/chat/sessions/$SID/stream
#    -> token ... message_end, then a diagnosis event flagging "I am agree" and
#       "I have 25 years"; the errors land in /api/review/queue automatically
```

Every reply from a model passes the JSON-schema + repair pipeline (§5 of
`architecture.md`); the tutor and judge prompts stay separate by design.

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
pip install -e . pyinstaller
python desktop/build-sidecar.py           # -> desktop/src-tauri/binaries/verba-server-<triple>

# 2. app icons (one-time, requires a source PNG)
cargo tauri icon path/to/app-icon.png     # writes desktop/src-tauri/icons/

# 3. dev window (expects the sidecar already built)
cargo run                                  # in desktop/src-tauri

# 4. full installers for this OS
cargo tauri build                          # dmg/app | msi/nsis | deb/appimage
```

CI/CD (`.github/workflows/`):

- **CI** — `ci.yml` on push/PR: `ruff check`, sidecar smoke build, `cargo check`
  on the three OS matrix rows.
- **Release** — `release.yml` on tag `v*`: reads the version from
  `pyproject.toml`, builds sidecar + installers on
  macOS (arm64; Intel macOS needs a Rosetta sidecar, planned for v0.2),
  Windows and Linux, attaches dmg/msi/exe/deb/AppImage
  to a draft GitHub Release, then publishes it. Installers ship signed
  updater artifacts (`.sig` + `latest.json`) since v0.1.1.

Optional secrets: `MACOS_CERTIFICATE` + `MACOS_CERTIFICATE_PWD` +
`KEYCHAIN_PASSWORD` (codesign/notarize), `TAURI_SIGNING_PRIVATE_KEY` (+password)
for the updater manifest. Replace `OWNER` in `tauri.conf.json` and generate the
updater pubkey with `cargo tauri signer generate`. Without them, builds ship
unsigned and the updater stays off — everything else works.

