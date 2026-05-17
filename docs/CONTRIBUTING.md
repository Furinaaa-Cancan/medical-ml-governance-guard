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
- Ruff on **changed files only** (since W20-P1) — protects the pusher from their own new lint regressions without blocking unrelated pushes when a sibling session left ruff red elsewhere. Full-tree ruff still runs in CI (`ci-unit.yml`) as the authoritative gate.
- Pytest smoke slice (~30s, recurring CI-red classes)

Bypass once: `git push --no-verify`

### Opt-in full-tree ruff at push time

If you want the old behaviour (block the push on *any* ruff red in `scripts/`, even sibling-introduced), set the env var:

```bash
MLGG_PRE_PUSH_STRICT=1 git push
```

**Why we narrowed the default**: W19-E4 measured PD-02 ("unbreaker" cascade — local hook forces `--no-verify`, then CI fails, then a fix-forward commit lands on top) at **12.20 / 100 commits post-W13, 8x the pre-W13 baseline** (1.56). Diagnostic: [`docs/diagnostics/W19_E4_process_debt_metrics.md`](diagnostics/W19_E4_process_debt_metrics.md). Root cause was structural, not behavioural: tree-wide ruff in pre-push meant any sibling-introduced red blocked unrelated pushes. ADR 0002 (race-proof commit protocol) couldn't fix it because the problem wasn't races — it was scope.

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

**Recommended: use git worktrees** (ADR 0004). Each parallel session gets its own working tree backed by the shared `.git/`, so there is no working file to race on. The shared `.venv/` strategy (ADR 0004 §6) keeps disk cost flat — the primary checkout's `.venv/` is the source of truth and worktrees symlink it.

One-time, in the primary checkout:

```bash
cd /Volumes/Seagate/Skill/ml-leakage-guard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./scripts/setup-dev.sh           # installs hooks; warns if .venv/ wiring is off
```

Per new parallel session:

```bash
./scripts/setup-dev.sh setup-worktree session-2
# creates ../ml-leakage-guard-session-2 on branch session-2
# symlinks its .venv/ to the primary checkout's .venv/
# installs the per-worktree pre-commit hook

cd ../ml-leakage-guard-session-2
source .venv/bin/activate         # same env as primary, via symlink
```

Point your second Claude Code session at the new directory. Edits, commits, and stashes in session 2 cannot touch session 1's working tree. When session 2's branch lands on `main` (via push + sibling rebase), `git pull --rebase` in session 1 picks it up.

To retire a worktree after merging:

```bash
git worktree remove ../ml-leakage-guard-session-2
git branch -d session-2
```

See [`docs/adr/0004_worktrees_default.md`](adr/0004_worktrees_default.md) §6-§7 for the full rationale and the `.venv/` failure mode to watch for (creating a real `.venv/` inside a worktree silently de-shares the env).

**Fallback (shared-checkout protocol):** If you decline worktrees (disk-pressure machines, or single-session multi-agent waves where sub-agents share the parent's working tree), follow the race-proof commit protocol in [`docs/adr/0002_race_proof_commit_protocol.md`](adr/0002_race_proof_commit_protocol.md). The short version: `git pull --rebase` before edit AND before commit, commit explicit paths via `git commit -o <file>`, never `git stash` to "make room" (that path produced the W13-C0 dead-stash cleanup wave), and never `git add .` / `-A` in a shared checkout. If three push retries fail, hand back to the orchestrator rather than fight the race.
