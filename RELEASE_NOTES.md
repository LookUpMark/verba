The v0.2.0 milestone: Verba speaks — and listens. Local voice, a guided runtime setup that removes the terminal from onboarding, an automatic update check, full JSON-Schema validation of model output, and a native Intel macOS build.

## Local voice (whisper.cpp, on this machine)

- **Speaking answers by voice** — the speaking task records your microphone in the browser, sends a WAV to the backend, and whisper.cpp transcribes it locally; the transcript is graded with word-level accuracy and missed words are shown, then flows into the same review loop as typed answers.
- **The whisper binary ships inside the app** (compiled from whisper.cpp v1.9.4 in CI for every platform); the ~148 MB English acoustic model downloads **once, on your explicit action** from the Models → Voice card, with a progress bar — nothing is downloaded or sent anywhere without you, and audio never leaves the machine.
- **OS-native text-to-speech** behind `POST /voice/tts` (macOS `say`, Linux `espeak-ng`, Windows SAPI) as the fallback when the browser has no voices; the browser's own synthesis stays the first choice for listening tasks.

## Runtime setup, without the terminal

- **A Runtime setup card on the Models screen** — per-runtime actionable state (CLI present? server running? hint). If the Ollama CLI is installed but stopped: one click starts `ollama serve` (owned by the app, closed with it). No model yet: one click pulls the suggested `qwen3:8b` (~5 GB) with a live progress bar, then rescans and assigns roles automatically. LM Studio's server starts through its `lms` CLI the same way.

## Update check at startup

- **An install chip appears when a new release is out** — the boot sequence silently checks the signed updater feed once (desktop shell only) and shows "Update X.Y.Z available — install" in the sidebar; installing downloads, applies and relaunches on your click. The manual Check-for-updates button stays in Models.

## Model output now validated against its schema

- **Every structured LLM call is JSON-Schema validated** — `generate_structured` (judge, curriculum, tasks, drills) validates the parsed reply against the declared schema and, on violation, retries with a repair prompt carrying the schema and the exact validator error paths; 503 after two failed repairs. Task payloads additionally keep their semantic checks (ranges, non-empty targets).
- **`reply_coach` is consumed** — the judge's one-line fix is injected as a coaching hint into the tutor's next turn (woven in naturally, judge never mentioned in chat).
- **`target_categories` persisted** — AI-generated missions store the error categories they target (schema contract of §7.1), exposed on the path for the adaptive ranking to consume.

## Intel macOS

- **A native x86_64 DMG** — the release matrix now builds on the Intel `macos-13` runner (the sidecar cannot cross-compile, so no Rosetta tricks); `Verba_0.2.0_x64.dmg` joins the arm64 one.

## Installers

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Verba_0.2.0_aarch64.dmg` |
| macOS (Intel) | `Verba_0.2.0_x64.dmg` |
| Windows | `Verba_0.2.0_x64-setup.exe` / `Verba_0.2.0_x64_en-US.msi` |
| Linux | `Verba_0.2.0_amd64.AppImage` / `Verba_0.2.0_amd64.deb` |

Builds are unsigned — macOS requires System Settings → Privacy & Security → Open Anyway on first launch (see the README's Gatekeeper guide). Upgrading from 0.1.x: install over the existing app, no data migration (`~/.verba/verba.db` gains the `target_categories` column automatically on boot).

See the [README](https://github.com/LookUpMark/verba#readme) for setup and usage.
