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
- 2026-06-05: **P2 triage done (33 verifiers): 23 confirmed real, 10 refuted.**
  Of the 23: **17 low-risk** (loop fixes + merges on green), **6 security/refactor**
  (human-merge). NOTE: a few verifier "minimal_fix"es are behavior-changing if
  applied literally — apply JUDGMENT (e.g. `[2]` ridge default mismatch → fix the
  COMMENT to match code 20.0, do NOT change the default; `[13]` setdefault→assign
  in hybrid union changes which record wins → treat as ranking-behavior, verify;
  `[32]` test-count badge drifts as tests are added → check live count first).
  - LOW-RISK queue: [2] ridge comment, [3] redundant float(), [4] O/E zero-expected
    guard, [6] DCA degenerate band (extends merged [4]), [9] dup component-validation
    entries, [11] ARCHITECTURE layer-exception note, [13]* hybrid union record,
    [15]* R028 dynamic-prefix, [16] R017 nested tuple/list, [18] RAG concern schema
    guard, [22] move test-only fns out of _gate_utils, [24] inline redundant wrappers,
    [26] self_critique fixture align, [28] MMR micro-opt, [30] input_files encoding
    uniformity, [32] test-count badge. ([13]/[15] starred = verify behavior first.)
  - SECURITY/REFACTOR (human-merge): [7] L3-vs-extval claim consistency, [8] invalid
    seal still contributes to L3, [10] gate_name validation, [17] audit-log swallows
    errors, [19] adaptive top-k comparability, [21] authority-e2e stale cohorts.
  - [23] gate_rag_bridge: verifier says KEEP as deprecation shim → no code change.
- 2026-06-06: **P2 cleanup MERGED — [6] DCA degenerate band (#43), [26] docs
  honesty (#42), [16/idx] R017 recursive eval_set (#44).** Then KEY FINDING when
  reading the code for the next P2 items: **several "low-risk" findings are NUANCED,
  not cosmetic — the triage's `minimal_fix` would cause a REGRESSION if applied
  literally:**
  - `[3]` "redundant float()" on oe_ratio is actually defensive numpy→python
    coercion for JSON serialization — removing it could re-leak numpy floats.
  - `[2]` ridge "default mismatch": production uses the CLI default (1.0, line 569
    always passes it); the 20.0 function-signature defaults are dead fallbacks —
    changing them needs caller analysis (tests may rely on 20.0).
  So the loop must NOT auto-grind the cosmetic tail. **Genuine remaining value, in
  priority:** (1) the 6 SECURITY/REFACTOR items ([7][8][10][17][19][21], HUMAN-MERGE);
  (2) P3 big refactors (finish() ×9, taint-tracker, tier/seal, seal-custody,
  dep-check, HUMAN-MERGE); (3) P1 [21]/[2-disease-KB] (need attestation-crypto /
  codebook test contexts). The nuanced/marginal P2 tail (oe_ratio float, ridge
  default, dup-validation, ARCHITECTURE note, hybrid-union record, R028
  dynamic-prefix, RAG-concern guard, move test fns, inline wrappers, MMR micro-opt,
  input_files uniformity, test-count badge) → do with JUDGMENT, low priority, NOT
  worth unattended grinding. **Loop paused: high-value safe harvest is done
  (16 fixes merged across the session); the tail needs human judgment or human
  merge.**
