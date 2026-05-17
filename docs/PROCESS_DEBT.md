# PROCESS_DEBT.md — Project-Level Process Anti-Patterns

- Status: living document
- Owner: wave orchestrator
- Created: 2026-05-17 (W14-D2)
- Related: `docs/adr/0002_race_proof_commit_protocol.md`, RAG retros (W1-W8, W9-W12)

## 1. Why this file

Some anti-patterns are not tied to any single ranker, KB, or gate
component — they are *process* defects: how agents coordinate, how
work is reported, how the commit pipeline behaves under concurrent
sessions. They contaminate any layer-specific retrospective they
land in (the W13-D0 RAG retro originally absorbed a stash-debt entry
that had nothing to do with retrieval).

This file is the durable home for that class of finding. It lives
alongside ADRs because ADRs codify *decisions*; this file catalogs
*recurring defects* — many of which become the input for future
ADRs.

Cross-reference rule: a layer-specific retro may name a process
anti-pattern in passing, but the durable entry lives here. The retro
gets a 2-line stub pointing at the relevant `PD-NN` ID.

## 2. Anti-patterns

### PD-01: stash-as-concurrency-primitive

**Symptom**: `git stash list` grows monotonically across waves and
nobody can identify which entries are safe to drop.

**Root cause**: agents working in a shared checkout use
`git stash push -m "sibling work"` to clear their workspace before
edits, then forget to `git stash pop` (or pop without `git stash
drop`). The `-m` label drifts from the actual contents within hours.

**Cost observed**: 8 stashes accumulated W7-W13 before the W13-C0
cleanup pass. Of the 8: 1 (`SELF_ATTESTED_LLM` enum + helper + test)
had unique unrecovered content and was preserved for explicit user
decision; 7 were already-landed work and were dropped. Each future
agent before W13-C0 had to audit 5+ unrelated stash entries before
using the slot for legitimate stashing — a friction tax compounding
with every new wave.

**Mitigation**:
- ADR 0002 (race-proof commit protocol) prohibits `git stash` as a
  concurrency primitive. The replacement is
  `git checkout HEAD -- <unrelated_sibling_files>` to undo what is
  not yours, then re-apply your edit.
- Per-agent worktrees as default for any wave with >3 concurrent
  agents (planned future ADR 0004).
- Pre-wave hygiene check: `git stash list | wc -l > 2` is a smell
  worth investigating before starting new work.

### PD-02: sibling-fix-forward churn

**Symptom**: a wave produces multiple commits labeled "CI unbreaker"
that fix red the current wave did not introduce. The fix-forward
commits add to commit-graph noise and obscure the wave's actual
deliverables.

**Root cause**: `.githooks/pre-push` runs ruff (and other linters)
tree-wide. Any red introduced by a sibling session blocks unrelated
pushes from the current session. The current session then has two
choices: (a) fix the red so its own push lands, accumulating
sibling-debt fix commits; or (b) `--no-verify` push, accumulating
hook-bypass exceptions. (a) is what actually happens most of the
time.

**Cost observed**: W12-A2 + W13 had at least 4 such commits:
- `f4a9407` — fix(tests): update disease_kb fixtures for W11-F2 reviewer-binding triple (CI unbreaker)
- `ee9d7fe` — earlier CI unbreaker (lint scope)
- `8aba9dc` — fix(diagnostics): add argparse to render_paper_figures for --help (CI unbreaker)
- `721e8e7` — fix(diagnostics): add argparse to lint_stderr_routing for --help (CI unbreaker)

Each was reasonable in isolation; the pattern is the defect.

**Mitigation**:
- Constrain pre-push ruff to `--changed-only` (changed paths in the
  current push), so unrelated red does not block.
- OR adopt a fix-debt-first protocol: any session that finds red on
  pull MUST file an issue, then either fix or `--no-verify` with an
  explicit log line. No silent "CI unbreaker" drive-by commits.
- Either path requires consensus across orchestrator + agents; this
  is a future ADR candidate.

### PD-03: virtual-wave inflation

**Symptom**: a wave is reported as "N agents complete" but only a
fraction of N actually committed to the repo. The remaining outputs
exist in `/tmp/W*` or in transient session memory and are
unrecoverable after the session ends.

**Root cause**: audit-only / read-only waves do not require commits
by definition, so agents write findings to scratch paths and verbally
hand off to the next wave. When the next wave fails to ingest, the
audit is unreplayable. The orchestrator's "complete" count is
load-bearing for future planning but does not reflect what is on
disk.

**Cost observed**: W10 reported "10 agents complete" but only R0
committed (`2603578`, ruff cleanup). R1-R4, S1, T1-T4 outputs lived
under `/tmp/W10*` and were distilled into W11 inputs only because
the W10 → W11 dispatch happened in the same calendar day. A
hypothetical future reader trying to replay W10 sees one commit and
no evidence of the other nine audits.

**Mitigation**: every audit-only agent MUST do one of:
- Commit its `/tmp` output to `docs/diagnostics/` with a wave-tagged
  filename, OR
- Inline the full output into a commit message body (acceptable for
  short audits, ≤2KB), OR
- Inline the full output into the next wave's input prompt AND
  preserve that prompt in the wave's orchestrator log.

The "verbally distill into next wave" path is forbidden because it
leaves no replay artifact.

### PD-04: ghost regression / ghost improvement

**Symptom**: a wave optimizes against a metric or fixes a violation
that does not actually exist. Effort is consumed; the headline number
moves; the underlying system is unchanged.

**Root cause**: agents accept upstream framing (a hand-off note, an
earlier wave's diagnosis, a CI alarm) without re-verifying the
premise. The W11-S1 finding — "166 ruff red" wall was 2 real
violations + a hook misconfiguration — is the canonical case.

**Status**: named in the W1-W8 / W9-W12 RAG retro as anti-pattern
#6 ("ghost configuration debt"). Listed here for completeness
because it is process-level (any layer can be subject to it), not
RAG-specific. The 25% phantom-backlog rate W10 surfaced is the
sharpest cost estimate the project has.

**Cross-reference**: `docs/RAG_WAVE_9_TO_12_RETRO.md` anti-pattern
#6. The mitigation (every 3-5 fix waves, run a 1-wave audit) is
documented there.

## 3. Detection scripts

Quick commands to check for each PD on demand:

```sh
# PD-01: stash debt
git stash list                              # human review
git stash list | wc -l                      # smell threshold: > 2

# PD-02: sibling-fix-forward churn
git log --since="2 weeks ago" --grep="unbreaker"
git log --since="2 weeks ago" --grep="CI unbreaker" --pretty=format:"%h %s"

# PD-03: virtual-wave inflation
# (no automated check — orchestrator must compare reported "N agents
# complete" against `git log --grep="W<NN>-"` commit count + the
# count of new files under docs/diagnostics/W<NN>*)
git log --grep="W10-" --oneline | wc -l
ls docs/diagnostics/ | grep -c W10

# PD-04: ghost regression / improvement
# (no automated check — premise audit is by definition manual; see
# the W10 R/S/T-track dispatch shape as the template.)
```

## 4. Review cadence

- **End of each wave**: orchestrator skims this file and asks "did
  any of these recur in the wave just closed?" If yes, append a
  brief incident note under the relevant PD with the wave tag and
  commit hashes.
- **Every 3-5 waves**: full audit pass. Each PD's mitigation status
  is reviewed; new PDs proposed if the same defect class appears
  twice without a named PD.
- **At wave 20 / wave 30 / etc.**: cross-link any new ADRs that
  codified mitigations, so the chain
  `defect → recurring incidents → PROCESS_DEBT entry → ADR` is
  legible.

## 5. References

- `docs/adr/0002_race_proof_commit_protocol.md` — codifies PD-01's
  mitigation.
- `docs/RAG_WAVE_1_TO_8_RETRO.md`, `docs/RAG_WAVE_9_TO_12_RETRO.md`
  — historical retros where some of these patterns first surfaced
  before being relocated here.
- Future ADR 0004 (planned) — worktree-default for high-concurrency
  waves (PD-01 + PD-02 mitigation).
