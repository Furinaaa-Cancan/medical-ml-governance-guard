# GOAL — Strict-Review Backlog Cleanup (autonomous loop)

> Status: **ACTIVE.** Created 2026-06-05 from the 47-agent strict review
> ([[../]] — see memory `project_strict_review_2026_06_05`). 13 confirmed fixes
> already merged (batches 1-5 + [26]); this goal clears the REMAINDER.

## Mission

Work the remaining strict-review backlog to done — each item as a **granular PR**
with a **real-producer test**, **CI green before merge**, and (for security/cert
code) an **independent adversarial-verify pass**. Quality over throughput: this
harness exists to prove correctness, so the cleanup must hold itself to the same
bar that caught the `[6]` regression.

## Loop policy (per iteration)

1. `git checkout main && git pull` first (parallel sessions are active).
2. Pick the next backlog item by priority (below). One item → one branch → one PR.
3. Read the REAL producer before trusting any fixture (the failure class that bit
   this session 4×: field names, reachability, schema). Write the test against the
   real producer.
4. Lint (`ruff check scripts/`), run the affected suite, then push + open PR.
5. Wait for CI. **Never merge before green.** Re-run a "canceled"/timeout job once.
6. **Merge policy by risk:**
   - **Low-risk** (tests, docs, dead-code removal, isolated bug fix with a clear
     test): merge when CI green.
   - **Security / cert / lint-engine / cross-gate refactor**: run an adversarial
     verify workflow, open the PR, and **LEAVE IT FOR HUMAN MERGE** — do not
     auto-merge unattended.
7. Append a one-line progress entry to the log below each iteration.

## HARD STOPS (park, do not push through)

- **`.github/workflows/` edits** (so #30 xdist is PARKED until explicit approval).
- Unattended **paid/external live-LLM** call (use the deterministic double).
- `git push --force`, `main` direct push, `reset --hard`, `clean -f`, deletes.
- An item whose fix **exposes another layer** or **fails CI twice** → park it,
  log why, move on (the "pause when a fix exposes layers" rule).
- Touching `references/*.json`, `pyproject.toml`, `.gitignore`, `LICENSE`,
  SKILL.md/CLAUDE.md without explicit ask.

## Backlog (priority order)

### P1 — deferred safe items (need setup, but high value)
- **[21]** execution_attestation_gate: no signing→verification round-trip test.
  Study the real signature path first (a faked signature = a vacuous test).
- **[2]** cohort_definition_gate disease-KB-absent fail-open. Reachable only when
  `survey_source` set AND `get_codebook()` returns non-None (line ~1680) — needs a
  real codebook context (registry codebook is lightest). Re-apply the `else` +
  `MLGG_DISEASE_KB_PATH` override + a test that reaches the block.

### P2 — medium/low triage (33 unverified findings)
Verify each (adversarial), fix the confirmed-real ones (13 bug / 6 contract /
5 dead-code / 3 docs / 2 arch / 2 test / 2 perf), skip the false-positives with a
logged reason. Low-risk → merge on green.

### P3 — big refactors (HUMAN MERGE, do not auto-merge)
- **[25]** finish() signature unification across 9 gates.
- **[13]** lint taint-tracker dict/list subscript propagation.
- **[5]** publication_gate tier/seal pre-verification ordering.
- **[16]** seal-key custody across the bootstrap retry path.
- **[15]** run_dag_pipeline dep-check boolean precedence.

### PARKED (need explicit human decision)
- **#30** pytest-xdist (CI-workflow edit — HARD STOP above).
- Low-ROI: `[23][24]` perf, `[17]` markdown-fence (fix not viable as proposed).

## Progress log
- 2026-06-05: goal created; loop started. P2 triage workflow kicked off first.
