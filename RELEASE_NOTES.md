Brand round: Verba finally looks the part — a designed app icon, a public-facing README with real screenshots, and the release notes you are reading — plus one real bug fix found while shooting those screenshots.

## App icon

- **A speech bubble holding the V of "Verba", with an AI spark, in the app's coral on a warm near-black squircle** — designed as SVG in the repository (`assets/icon.svg`), studied against the UI palette (coral `#d97757` on the warm near-black ground) and rendered at every size from 16 px to the macOS dock; the 32 px thumbnail still reads clearly. The icon ships in the DMG, the Windows and Linux bundles, and the README header.

## README for a public repo

- **Real screenshots from a real run** — path, lesson (a task generated live by the local model), tutor with the judge flagging "I am agree" and "I have 25 years" at 40/100, the FSRS review queue, and the detected runtime — shot against oMLX and embedded in a restructured README: why-Verba differentiators, per-platform quickstart with the Gatekeeper unblock guide, per-runtime setup table, from-source build, first-run verification and privacy notes.

## Fixed

- **Discovery never refreshed a runtime's endpoint** — the probe result was written onto an existing `runtimes` row without updating its endpoint, so an address recorded by an older run (or an old `VERBA_MLX_ENDPOINT`, or an oMLX port change) stayed "detected" while the app dialed a dead port. Every scan now rewrites endpoint and name. Found live: the runtime looked green while every LLM call failed with connection errors.
- **Retry budget outlasts cold model loads** — a local server can refuse or hold connections for a couple of minutes while it loads a big model; the MLX provider's transient-error deadline is now 180 s (was 90 s) so the first call after a cold start waits instead of failing.
- **A stray apostrophe rendered inside every diagnosis card** — a leftover quote character in the card template showed a floating `'` between the score and the first error. Caught by the README screenshots; the cards are clean.

## Installers

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Verba_0.1.4_aarch64.dmg` |
| Windows | `Verba_0.1.4_x64-setup.exe` / `Verba_0.1.4_x64_en-US.msi` |
| Linux | `Verba_0.1.4_amd64.AppImage` / `Verba_0.1.4_amd64.deb` |

Builds are unsigned — macOS requires the Gatekeeper unblock above on first launch. Upgrading from 0.1.x: install over the existing app, no data migration (`~/.verba/verba.db` is kept and the tasks-uniqueness index is added on boot).

See the [README](https://github.com/LookUpMark/verba#readme) for setup and usage.
