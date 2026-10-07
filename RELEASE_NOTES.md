The v0.2.1 maintenance release: a full end-to-end audit of the installed app — backend against a live local model, every screen driven in a real browser, voice, and the packaged DMG lifecycle — surfaced three real defects. All three are fixed here. No new features; if 0.2.0 worked for you, this makes it stop lying in three specific places.

## Runtime setup card no longer reports oMLX as stopped

- **The setup wizard probed `/v1/models` without authentication** — oMLX requires Bearer auth, so the probe always got a 401 and the Models screen showed "Not running" even while Verba had the server up and detected with all models listed. The probe now reuses the configured endpoint headers (Authorization included) and timeouts, so the card tells the truth: server running, CLI present, models in place.

## The speaking task renders again in the desktop app

- **A scoping bug left the speaking screen empty** — in API mode the renderer appended its widgets to a container only defined in the file:// demo branch, after an early return: a ReferenceError fired and the learner got a bare prompt with a permanently disabled Check. Every mission was stuck at its speaking task. The container is now built once for both branches, and the desktop task shows what the demo always had, plus what whisper grading needs: **the sentence to read**, a "Hear the model" button, the mic, and the "Type instead" fallback.

## Judge diagnoses survive an early exit

- **Closing the chat stream mid-analysis lost the diagnosis** — the judge ran inside the SSE generator, so finishing the session, reloading, or quitting the app while the local model was still grading (it can take ~40s on a 12B model) cancelled the work before it committed: sessions ended "0 errors" with errors on screen, and nothing reached the review loop. The judge now runs as a detached task on its own database session — the verdict is persisted no matter what the client does — and the Finish button refuses to close a session while a reply is still being analyzed.

## Installers

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Verba_0.2.1_aarch64.dmg` |
| macOS (Intel) | `Verba_0.2.1_x64.dmg` |
| Windows | `Verba_0.2.1_x64-setup.exe` / `Verba_0.2.1_x64_en-US.msi` |
| Linux | `Verba_0.2.1_amd64.AppImage` / `Verba_0.2.1_amd64.deb` |

Builds are unsigned — macOS requires System Settings → Privacy & Security → Open Anyway on first launch (see the README's Gatekeeper guide). Upgrading from 0.2.0: install over the existing app, no data changes.

See the [README](https://github.com/LookUpMark/verba#readme) for setup and usage.
