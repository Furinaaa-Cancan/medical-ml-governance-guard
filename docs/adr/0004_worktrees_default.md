# ADR 0004 — Worktrees Default-On for Parallel Sessions

- Status: Accepted
- Date: 2026-05-17
- Author: W14-X1
- Related: ADR 0002 (race-proof commit protocol — W13-C0), W9-C3 (race-deletion), W11-F2/F3/F4/I2, W12-A2/B*, W13-C0 (7-stash reap), W14-D2 PD-02 (sibling-unbreaker churn), W14-F3 / W14-R0 (fresh stash backlog already accumulating post-ADR-0002)

## 1. Context

ADR 0002 codified a "race-proof commit protocol" for concurrent sessions sharing one working tree: `git pull --rebase` before edit and before commit, `git commit -o <file>` for explicit paths, never `git stash` to "make room." It was Accepted on 2026-05-17.

The same day, this investigation found the stash list already at 4 entries again:

```
stash@{0}: WIP on main: f4a9407 fix(tests): update disease_kb fixtures ...
stash@{1}: On main: W14-F3 stash test_retrieval_eval_harness.py xfail change
stash@{2}: On main: W14-R0 stash before pull
stash@{3}: On main: W13-P0 stash unrelated kb_provenance work
```

ADR 0002's author wrote (in their own self-critique relayed via W14-X1's task brief): *"the real solution is worktrees default-on — each concurrent session gets its own working tree, so `git stash` is never needed and there's nothing to race on."* The fresh backlog above corroborates: protocol discipline degrades under wave pressure; structural isolation does not.

**During the authoring of this very ADR**, a sibling session reverted both new files (the ADR draft and the `setup-dev.sh` tip) between Write and the first `git commit -o` attempt. The race ADR 0004 targets reproduced live, on the file documenting the fix. Recovered via re-write; logged here as Evidence 0.

### Two distinct race surfaces

| Surface | Source | Example | Worktree-solvable? |
|---------|--------|---------|---------------------|
| **Concurrent sessions** | Multiple Claude Code instances (separate terminals / launches) operating on the same checkout | W11-F2 vs W11-F3 vs W11-I2 stash-restore loop; W14-F3 vs W14-R0 stash pair; W14-X1 ADR draft revert (this commit) | **Yes** — each session works in its own `git worktree` |
| **Concurrent agents within one session** | Sub-agents spawned by one session via the `Agent` tool, sharing the parent's working tree | W13 wave agents producing intermediate files in parallel | **Partial** — `Agent isolation: "worktree"` covers this per-spawn, but adds setup cost and is per-call opt-in |

Most of the documented race incidents (W11-F2/F3/F4/I2, W12-A2/B*, W13-C0 cleanup, W14-F3/R0 stash pair, W14-X1 ADR revert) were **concurrent-session** races, not concurrent-agent races. That's the surface this ADR targets.

### Cost of ADR 0002 alone

- Author-discipline-bound: a tired or under-context agent forgets the protocol and stashes anyway (W14-F3 / W14-R0 evidence).
- Doesn't prevent: race-deletion of files between `Write` and `commit -o` (the W9-C3 mode, reproduced live during this ADR's authoring) is reduced to a window, not eliminated.
- Sibling-fix-forward commits (W14-D2 PD-02) keep landing because two sessions diverge on `main` between rebases.

A worktree per session collapses all three failure modes: there is no shared working tree to stash from, no shared `HEAD` to drift between rebases, no shared file for a sibling to delete from under you. The shared `.git` (objects, refs, branches) is preserved, so `git pull --rebase` between worktrees is the only coordination needed and it is a fast-forward in the common case.

## 2. Decision

**Decision: A — recommend worktrees by default for concurrent sessions.** ADR 0002 stays valid as the fallback for shared-checkout work and for single-session multi-agent waves (where worktrees don't apply because sub-agents share the parent's working tree by default).

Specifically:

1. `docs/CONTRIBUTING.md` gains a "Starting a new parallel session" subsection (this ADR's companion edit) walking through the worktree-add flow. **Not done in this commit** — to be added by a follow-up wave to avoid scope creep here. The pointer in `setup-dev.sh` (Step 3 below) is enough to surface the option now.
2. `scripts/setup-dev.sh` gains a 3-line tail tip pointing at this ADR. No worktrees are auto-created — the user opts in per parallel session.
3. ADR 0002 is **not** superseded. It remains the rule for:
   - The first / primary session (the original checkout still works as before).
   - Single-session multi-agent waves (sub-agents share the working tree).
   - Anyone who declines the worktree path for disk-cost reasons.
4. The repo's CLAUDE.md is **not** modified in this ADR. Promoting `Agent isolation: "worktree"` to a repo-wide default is a separate decision with its own per-spawn cost trade-off; it's logged below as a follow-up.

### Recommended layout

```
/Volumes/Seagate/Skill/
├── ml-leakage-guard/              # primary checkout (main session)
├── ml-leakage-guard-session-2/    # `git worktree add ../ml-leakage-guard-session-2 main`
├── ml-leakage-guard-session-3/    # `git worktree add ../ml-leakage-guard-session-3 main`
```

All three share `ml-leakage-guard/.git/`. Each has its own working tree, index, and `HEAD`. Branches are still shared — two worktrees cannot check out the same branch simultaneously, so each parallel session typically works on a per-session branch (`session-2`, `session-3`) and merges back to `main` via the normal PR / push flow (or local fast-forward).

### Justification (2 sentences)

The dead-stash backlog reappeared on the same day ADR 0002 was Accepted, and a sibling session reverted this very ADR's draft mid-authoring — both demonstrating that discipline-based protocols decay under wave pressure while structural isolation does not. Worktrees cost disk (≈800 MB working tree per session; `.git/` is shared) but eliminate the entire class of stash-restore-loop, race-deletion, and sibling-fix-forward incidents that have consumed five+ waves of cleanup work.

## 3. Consequences

### Positive

- **No more dead-stash backlog** for sessions that adopt worktrees: the stash list per worktree is private to that worktree (`git stash` records into `refs/stash` per-tree).
- **No race-deletion**: sibling sessions cannot touch files in another worktree's working directory.
- **No sibling-fix-forward**: each worktree advances `HEAD` independently; `git pull --rebase` between them is the only synchronization, and it's atomic at the ref-update level.
- **Hooks deduplicated**: `core.hooksPath = .githooks` is repo-config, inherited by all worktrees automatically. `pre-commit install` writes to `.git/hooks/`, which is per-worktree — so each new worktree needs `pre-commit install` re-run once (see Migration §4).
- **Backups**: each worktree is a normal directory tree, so `rsync`-style backups already work.

### Negative

- **Disk cost**: each worktree's working tree is ≈800 MB (current checkout size, dominated by `.cache/` and conda env if co-located). For 3 parallel sessions, expect ≈2.4 GB of working-tree duplication on top of the shared 1.8 GB `.git/`. Acceptable on a 2 TB Seagate; users on smaller disks must opt out.
- **Conda env separation**: if `.venv/` lives inside the working tree, each worktree gets its own — costly and slow to provision. Recommendation: keep `.venv/` outside the repo (e.g., `~/envs/mlgg/`) or symlink a shared one. Document in CONTRIBUTING follow-up.
- **Pull-base divergence risk**: if session A and session B both `git pull --rebase` simultaneously and both have local commits, one will get a `non-fast-forward` reject on push. ADR 0002's "max 3 retries then hand back to orchestrator" rule still applies between worktrees.
- **Branch-lock surprise**: `git worktree add ../foo main` fails if another worktree already has `main` checked out (it does — the primary checkout). Workaround: `git worktree add -B session-2 ../foo main` to create and check out a per-session branch. Documented in §4 migration.
- **Mental model overhead**: contributors must learn `git worktree list`, `git worktree remove`, and the fact that branches are tree-locked. Less familiar than stash.

### Neutral

- `git log`, `git fetch`, `git push`, `git branch`, `git tag`, `git remote` all operate on the shared `.git/` — visible identically from every worktree.

## 4. Migration plan (3 steps for an active multi-session user)

For a user currently running two Claude Code sessions against `/Volumes/Seagate/Skill/ml-leakage-guard/`:

1. **In the primary session**, stop and verify a clean tree: `git status` must be clean (commit or stash anything in flight; if you stash, write it down — see ADR 0002).
2. **From the parent dir** (`/Volumes/Seagate/Skill/`), create a worktree on a new per-session branch so the branch-lock doesn't trip:
   ```bash
   cd /Volumes/Seagate/Skill
   git -C ml-leakage-guard worktree add -B session-2 ../ml-leakage-guard-session-2 main
   cd ml-leakage-guard-session-2
   ./scripts/setup-dev.sh   # re-installs per-worktree pre-commit hook
   ```
3. **Point your second Claude Code session at the new directory.** It is now isolated: edits, commits, and stashes in session 2 cannot touch session 1's working tree. When session 2's work lands on `main` (via push + sibling rebase), `git -C ml-leakage-guard pull --rebase` in session 1 picks it up.

To retire a worktree after merging its branch:

```bash
git worktree remove ../ml-leakage-guard-session-2
git branch -d session-2   # if merged; -D to force-delete unmerged
```

## 5. Detection / KPI

Track these to validate the decision (review at W18 retrospective):

- **Stash count over time**: `git stash list | wc -l` sampled per wave. Baseline 2026-05-17: 4 entries. Target post-adoption: ≤1 average, primarily from primary-checkout single-session flow.
- **Sibling-unbreaker commit rate**: count of commits whose message contains `CI unbreaker`, `sibling`, or matches the W14-D2 PD-02 pattern, per wave. Baseline: W11–W14 saw ≥5 such commits. Target: ≤1/wave.
- **`git worktree list` adoption**: informal — how many parallel sessions a user reports running via worktrees vs shared checkout.
- **Disk pressure incidents**: any user reports of disk-full during worktree provisioning.

If after W18 the stash count remains ≥3 average or unbreaker rate ≥3/wave, revisit Decision B (worktrees-everywhere, including `Agent isolation: "worktree"` as repo default).

## 6. Shared `.venv/` strategy (W20-P2 follow-through)

**Problem.** Decision §2 isolates working trees but says nothing about the Python environment. Three plausible layouts:

| Option | Description | Disk | Race surface | Lifecycle |
|--------|-------------|------|--------------|-----------|
| **A. Per-worktree env** | Each worktree provisions its own `.venv/` (or conda env) | ≈800 MB × N | None (clean) | Bound to worktree (clean) |
| **B. Shared `~/.cache/mlgg-venv/`** | One env in `$HOME`, all worktrees activate it | ≈800 MB total | `pip install -e .` from any worktree mutates env for all | Outlives any repo; orphaned on repo delete |
| **C. Primary `.venv/` is source of truth, worktrees symlink it** | `.venv/` lives in the primary checkout; each worktree has `.venv -> /abs/path/to/primary/.venv` | ≈800 MB total | Same as B (any worktree's `pip install -e .` mutates shared env) | Bound to primary checkout (clean if primary is the canonical repo) |

**Decision: C.** The primary checkout's `.venv/` is the single source of truth. Worktrees get a symlink, not their own env.

**Justification (1 paragraph).** Option A's disk cost (a fresh PyTorch + sentence-transformers stack runs ≈1.5 GB once `pip install -e .[dev]` lands) defeats the "worktrees are cheap, just do it" pitch that §2 needs to land. Option B places shared state outside any repo, creating two confusion modes (env survives `rm -rf ml-leakage-guard/`; env name `mlgg-venv` doesn't tell you which checkout owns it). Option C keeps the env's lifecycle bound to the primary checkout — the same checkout users already think of as canonical — so `git worktree remove` plus `rm -rf` of the primary cleans up everything. The shared-state mutation risk (any worktree's `pip install -e .` affects all) is the same in B and C, and is acceptable because `pip install -e .` is rare (dependency add) and announced; it is *not* a per-commit operation the way `git stash` was. The symlink is preferred over `python -m venv --symlinks` (which still creates a per-worktree directory with linked binaries) because a single symlink is one `ls -la` away from being verifiable, whereas the venv-with-symlinks form requires inspecting `pyvenv.cfg` and a matching-version Python on the spawning machine.

**Failure mode (self-challenge).** If a contributor runs `python -m venv .venv` (or `uv venv`) from inside a worktree without first checking, they will create a real directory that shadows the would-be-symlink and silently de-shares the env — re-introducing Option A's disk cost without the cleanliness benefit (now you have two `.venv/` directories whose `pip install -e .` paths diverge). `scripts/setup-dev.sh` mitigates this by detecting the worktree case and warning if `.venv/` is a real directory instead of a symlink (Step §7.3 below).

**Caveat — Conda envs.** This ADR's §6 covers the venv case. Contributors using a conda env (the historical default for some of the team) should `conda activate` the same env name from every worktree; conda's per-process activation is fine for parallel use, but `pip install -e .` from one worktree still mutates the shared site-packages and `egg-info` (the same risk class as venv). No symlink needed for conda.

## 7. Worktree setup commands (the actual contributor flow)

The 5-line recipe a contributor runs to create a worktree that shares the primary `.venv/`:

```bash
# From the primary checkout (one-time, if .venv doesn't exist yet):
cd /Volumes/Seagate/Skill/ml-leakage-guard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Per new parallel session (this is the helper added in setup-dev.sh):
./scripts/setup-dev.sh setup-worktree session-2
# → creates ../ml-leakage-guard-session-2 on branch session-2
# → symlinks ../ml-leakage-guard-session-2/.venv -> /abs/.../ml-leakage-guard/.venv
# → re-installs the per-worktree pre-commit hook
```

After the helper runs, the contributor:

```bash
cd ../ml-leakage-guard-session-2
source .venv/bin/activate           # follows the symlink; same env as primary
pytest -q                            # confirms shared env works
```

**Verifying the symlink is intact:**

```bash
ls -la .venv
# expected: .venv -> /Volumes/Seagate/Skill/ml-leakage-guard/.venv
# if you see "drwxr-xr-x  ...  .venv" (directory, not symlink), the share is broken
# — `rm -rf .venv && ln -s /abs/.../ml-leakage-guard/.venv .venv` to restore
```

**Retiring a worktree:**

```bash
git worktree remove ../ml-leakage-guard-session-2   # removes the worktree dir (including the symlink, not its target)
git branch -d session-2
```

The symlink is removed by `git worktree remove`; the primary `.venv/` is untouched. Confirmed by `git worktree remove`'s docs: it deletes the worktree directory, which removes the symlink entry but does not follow it.

## 8. References

- ADR 0002 (`docs/adr/0002_race_proof_commit_protocol.md`) — the protocol this ADR layers on top of, not replaces.
- `git worktree` manual: `git help worktree`.
- Claude Code `Agent` tool `isolation: "worktree"` parameter — the per-spawn analog for sub-agents.
- W13-C0 dead-stash reap commit (see ADR 0002 §1 table).
- W14-D2 PD-02 sibling-unbreaker pattern (see W14 wave notes).
- W14-X1 mid-authoring revert incident (this commit's first attempt — recovered).
