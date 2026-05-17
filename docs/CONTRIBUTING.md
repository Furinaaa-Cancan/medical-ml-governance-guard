# Contributing to MLGG

## Local hooks (required for new contributors)

MLGG has TWO complementary hook systems to catch issues before CI:

### 1. pre-commit hook (catches drift + lint, runs on every commit)

Activate ONCE per checkout:

```bash
pip install pre-commit
pre-commit install
```

This wires `.pre-commit-config.yaml` which runs on every `git commit`:

- `ruff check` on scripts/ and tests/
- README drift detection (matches `check_readme_stats.py`)
- KB hygiene checks
- Various MLGG-specific validators

Bypass once (NOT recommended): `git commit --no-verify`

### 2. pre-push hook (catches RAG smoke + final drift)

Add a layer that runs on `git push`:

```bash
make install-hooks  # one-shot
```

Or manually: `git config core.hooksPath .githooks`

This wires `.githooks/pre-push` which runs ~30s before any push:

- Final README drift check
- RAG layer importorskip smoke
- Ruff if installed

Bypass once: `git push --no-verify`

## Why we have both

Pre-commit catches issues early (per-commit, fast). Pre-push catches issues that pre-commit might miss (e.g., RAG smoke that needs sentence-transformers installed).

Historical context: 8 waves of RAG fixes accumulated **5 separate drift fix-forward commits** because contributors skipped hook activation. Don't be one.

## One-shot setup

```bash
./scripts/setup-dev.sh  # installs both hook systems + checks deps
```

## Verifying activation

```bash
git config core.hooksPath          # should print ".githooks"
pre-commit run --all-files         # should run without "pre-commit not installed"
```

## Concurrent sessions (multi-agent / multi-terminal)

If you run more than one Claude Code session (or other agent / terminal) against this repo at the same time, follow the race-proof commit protocol in [`docs/adr/0002_race_proof_commit_protocol.md`](adr/0002_race_proof_commit_protocol.md). The short version: `git pull --rebase` before edit AND before commit, commit explicit paths via `git commit -o <file>`, never `git stash` to "make room" (that path produced the W13-C0 dead-stash cleanup wave), and never `git add .` / `-A` in a shared checkout. If three push retries fail, hand back to the orchestrator rather than fight the race.
