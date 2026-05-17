# ADR 0002 — Race-Proof Commit Protocol for Multi-Session Work

- Status: Accepted
- Date: 2026-05-17
- Author: W13-C0
- Related: W9-C3 (race-deletion incident), W11-F2/F3/F4/I2 + W12-A2/B* (stash-restore loops), W13-C0 (5+ dead stash cleanup)

## 1. Context

The repo supports concurrent Claude Code sessions (multiple terminals, agents, automation). Wave 9-12 saw recurring race patterns:

- **W9-C3 race-deletion**: a sibling session deleted a file that C3 was about to commit; `git commit -o <file>` recorded the deletion silently because `-o` filters by path but does NOT prevent the file being modified or deleted by sibling sessions between `Read` and `commit`.
- **W11-F2/F3/F4/I2 and W12-A2/B* stash-restore loops**: agents called `git stash` to "make room" for a clean commit, intending to restore the sibling work afterward. Restoration was forgotten, and 5 dead stashes accumulated on `main` (the W13-C0 cleanup wave finally reaped them; see below for the full list).
- **Dead-stash backlog** makes `git stash list` useless for actual stashing needs — every future agent has to first audit 5+ unrelated entries before using the stash slot for legitimate work.

The W13-C0 cleanup found seven of eight accumulated stashes were already-landed work that nobody had reaped:

| Wave | Label | Outcome |
|------|-------|---------|
| W7-P9 | other session's RAG work in progress | already in main, dropped |
| W11-F4 | unrelated pre-push hook change | already in main, dropped |
| W11-I2 | sibling F2/F3/F4 in-progress work | already in main, dropped |
| w11-m1 | temp-docs | already in main, dropped |
| W11-I2 (b) | sibling docs + my I2 work | already in main, dropped |
| W13-P0 | unrelated kb_provenance work | already in main, dropped |
| W13-G1 | unrelated rag config | already in main, dropped |
| W13-T0 | pre-rebase stash | superseded by main, dropped |

Only one stash had unique unrecovered content (`SELF_ATTESTED_LLM` enum + helper + test) and was preserved for explicit user reap-or-drop decision.

## 2. Decision

Adopt this protocol for any session working concurrently with siblings.

### Before edit

1. `git pull --rebase` to land on fresh HEAD.
2. `Read` the file (latest content).
3. Edit and verify.

### Before commit (CRITICAL)

1. `git pull --rebase` AGAIN — catches sibling commits that landed during your edit.
2. Inspect `git status`. If your file shows unexpected modifications/deletions from siblings:
   - DO NOT `git stash` — this is what creates the dead-stash backlog.
   - Instead: `git checkout HEAD -- <unrelated_sibling_files>` to undo what is not yours.
   - Re-apply your edit on the fresh state.
3. `git commit -o <ONLY-YOUR-FILES> -m "..."` — explicit per-path commit, never `git add .` or `-A`.
4. `git push`. If rejected: `git pull --rebase` + retry (max 3 times).

### What NOT to do

- `git stash` to "make room" — creates the dead-stash backlog this ADR exists to prevent.
- `git add .` or `git add -A` — sweeps in sibling work.
- `--amend` after a pre-commit hook failure — the hook failed BEFORE creating your commit, so `--amend` modifies the WRONG (previous) commit.
- `git commit --no-verify` for your OWN red — only sanctioned for UNRELATED pre-existing red (W9-D3 carve-out).

### Failure-mode acceptance

If 3 push retries fail due to siblings, hand back to the orchestrator. Do not fight the race; report and let a coordinated re-spawn pick up the work.

## 3. Consequences

- Slightly slower per-commit (one extra `git pull --rebase` before commit).
- No more dead-stash backlog.
- Sibling-file accidental-commits prevented.
- The `git stash list` slot is reserved for actual stashing needs, so future sessions can use it without first auditing 5+ unrelated entries.

## 4. Out of scope

- A true lock service would require a shared coordination layer that is not justified for the current concurrent-session volume.
- Per-agent worktrees are already supported via `Agent isolation: "worktree"` but add per-spawn overhead; this ADR keeps the cheap shared-checkout default workable.

## 5. References

- W9-C3 race-deletion incident: see commit history around the C3 file deletion event.
- W13-C0 cleanup commit: this ADR's commit.
- W9-D3 carve-out for `--no-verify` on UNRELATED pre-existing red: see W9 wave notes.
