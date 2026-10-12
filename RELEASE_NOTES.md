The QA release: a full audit round — unit coverage gaps closed, every API endpoint exercised against a live local model, every screen driven in a real browser, adversarial "what if the user does something odd" passes, and the packaged DMG lifecycle — surfaced four real defects and a lying error message. All fixed here. No new features; if 0.2.1 worked for you, this makes it stop cheating in four specific places.

## Blank answers no longer score as correct

- **Grading of multiple-choice and gap tasks trusted `"abcd".find(answer)`** — and Python's `find("")` returns 0, so submitting an empty answer matched choice "a": every blank submission was graded CORRECT whenever the first option was the right one, inflating XP and accuracy stats. Blank answers are now always incorrect.

## Placement now lands where it should

- **Placement results unlocked the wrong missions** — the path enumerated missions in an effectively random order (sorted by a hex unit id), so placing at B2 marked a scattered set done and pointed the learner at the very first A1 lesson, while placing at A2 pre-marked the A2 missions themselves complete. The curriculum is now walked in true order (level → unit → mission), and after placement the current mission is the first one of the placed level.

## A forged completion can no longer mint XP

- **Completing a mission without answering anything trusted the client** — a `{correct: 999, total: 1000}` payload produced a 100% / +40 XP completion. Completion now requires actually recorded attempts and refuses otherwise (400); the app itself always grades through the attempts API, so normal play is untouched.

## Stats is back on narrow windows

- **The mobile bottom bar was missing its Stats button** — below a 900 px window (the desktop app can be resized down to 375 px) Statistics became unreachable. The bar now mirrors the sidebar's five screens.

## Honest degraded-mode hints

- When no model is detected, the message now points at oMLX, LM Studio or Ollama and the Models screen's Rescan — it previously named a nonexistent `/api/runtimes/scan` endpoint and omitted oMLX, the primary runtime.

## Under the hood

- The test suite grew from 38 to 58 tests: coverage for previously untested grading, FSRS scheduling, judge scoring and pronunciation-scoring branches, plus a regression test for every fix above. The full audit report — including the issues investigated and dismissed, and the product decisions deliberately left open — lives in [docs/validations/QA-20261012-verba.md](https://github.com/LookUpMark/verba/blob/main/docs/validations/QA-20261012-verba.md).

## Installers

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Verba_0.2.2_aarch64.dmg` |
| macOS (Intel) | `Verba_0.2.2_x64.dmg` |
| Windows | `Verba_0.2.2_x64-setup.exe` / `Verba_0.2.2_x64_en-US.msi` |
| Linux | `Verba_0.2.2_amd64.AppImage` / `Verba_0.2.2_amd64.deb` |

Builds are unsigned — macOS requires System Settings → Privacy & Security → Open Anyway on first launch (see the README's Gatekeeper guide). Upgrading from 0.2.x: install over the existing app, no data changes.

See the [README](https://github.com/LookUpMark/verba#readme) for setup and usage.
