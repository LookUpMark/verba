# Contributing — branch model, PR gate and release flow

The repository runs a three-tier branch model. Every change reaches `main` through a reviewed pull request — never a direct push.

## Branches

| Branch | Role | What lands there |
| --- | --- | --- |
| `main` | **prod** — always releasable, tagged versions only | Promotion PRs from `test`, hotfix PRs. Branch protection requires the CI checks (`backend`, `desktop`). |
| `test` | **test/QA** — integration & acceptance before prod | Promotion PRs from `develop`. |
| `develop` | **dev** — integration of ongoing work | Feature PRs. |

## The flow

1. **Feature work**: cut `feature/<slug>` from `develop`, open a PR **into `develop`**.
2. **Promotion**: `develop` → `test` → `main`, one PR per hop.
3. **Hotfix**: cut `hotfix/<slug>` from `main`, PR **into `main`**, then bring `main` back into `develop` and `test` via PRs as well.

Every merge is a pull request. Direct pushes to `main`/`test` are not part of the flow (main additionally enforces CI via branch protection).

## The PR gate

A PR is mergeable only when **both** hold:

1. **CI green** — the `backend` and `desktop` jobs pass on the PR for every matrix runner (ubuntu/windows/macos; the required status contexts are e.g. `backend (ubuntu-latest)`).
2. **Agent approval** — the `pr-approver` agent (global agent, `~/.zcode/agents/pr-approver.md`) reviews the diff, re-runs the verification locally and posts an explicit **APPROVE** / **REQUEST_CHANGES** verdict as a PR review. Merging on REQUEST_CHANGES is not allowed; fix, push, re-review.

Squash-merge for feature PRs (one clean commit per feature); merge commits for promotion PRs (develop→test→main) to keep the group history.

## Releases

Releases are cut **only from `main`** by the `release-manager` agent (`~/.zcode/agents/release-manager.md`): semver by real user impact (this is a 0.x project — breaking changes bump MINOR), version aligned **both** in `pyproject.toml` and `desktop/src-tauri/tauri.conf.json` **before** tagging (the release workflow gates tag ↔ pyproject version), tag push triggers the build, detailed English release notes in the established "Verba X.Y.Z" style. A release PR (version bump + notes prep) follows the same agent gate.

## Local verification before opening a PR

```sh
uv sync --frozen --dev && uv run pytest -q      # backend (rootdir = repo root)
# desktop build is exercised by CI; locally: see desktop/src-tauri (cargo tauri build)
```
