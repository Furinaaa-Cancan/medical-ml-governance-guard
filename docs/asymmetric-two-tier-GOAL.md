# GOAL — Asymmetric Two-Tier Harness

> Status: **in progress** (started 2026-06-05, branch `feature/asymmetric-two-tier`).
> Threat model assumption: **(ii) defend against the agent itself** — the seal key is custodied
> by the orchestrator/runtime, the agent never holds it. Revisit if narrowed to (i).

## Objective

Make MLGG an honest **asymmetric two-tier harness**:

1. **Deterministic floor** — the 33 gates issue a reproducible, non-fabricable pass/fail.
2. **LLM advisory layer** — fed all gate evidence + RAG concerns, it produces a reviewer report
   that can **raise concerns / lower the verdict** but can **never clear a gate failure**.

## The invariant (the heart)

> **final_verdict = min(gate_verdict, llm_verdict)**, order `FAIL < CONCERN < PASS`.

Mechanically: the LLM review report can only **append to `failures[]`/`warnings[]`** and **force
tier booleans DOWN**. There is no code path that sets a tier `True` or reduces `failure_count`
from LLM input. "Can add doubt, never remove it" is enforced by data flow, not by prompt.

## Work breakdown

### P0 — make the floor non-fabricable (foundation)
- [x] **P0.0** Asymmetric LLM advisory channel in `publication_gate` (additive, no CLI change;
      auto-discovers `<evidence_dir>/llm_review_report.json`; absent → no-op; malformed → fail-closed).
      Tests prove: LLM cannot upgrade a gate FAIL; LLM CAN block a gate PASS; absent → unchanged.
- [ ] **P0.1** Run-binding: stamp a `run_id` on every gate report; `publication_gate` rejects a
      mixed-run evidence set (reports must share one `run_id`). *(Additive: read-only check first.)*
- [ ] **P0.2** Enrol gate-report outputs (not just inputs) into the manifest hash so a hand-edited
      `*_report.json` is detectable. **CHECKPOINT: touches manifest contract — show diff, wait.**
- [ ] **P0.3** `publication_gate` stops trusting `report['status']`: verify a run-scoped seal on
      each report (key custodied by orchestrator). **CHECKPOINT: contract + key custody — wait.**
- [ ] **P0.4** `enforce_execution_attestation_publication_contract` re-verifies signatures / re-runs
      the attestation gate instead of reading only `summary` fields. **CHECKPOINT — wait.**
- [ ] **P0.5** Real `trusted_signers.json` allowlist wired (currently only `.example`). **CHECKPOINT.**

### P1 — build the LLM synthesis layer (the user's part ③)
- [ ] **P1.0** Synthesis step: all gate evidence + RAG concerns → LLM → structured reviewer report
      (Major/Minor/Questions) written to `evidence/llm_review_report.json` in the P0.0 schema.
- [ ] **P1.1** Audit trail: record which evidence the LLM saw + prompt/model + output hash.

### P2 — honest branding + measured grounding
- [ ] **P2.0** Bind claim tiers: `leakage-audited` (gates) / `+reviewer-concerns` (LLM advisory) /
      `publication-grade` (= both + real attestation).
- [ ] **P2.1** Benchmark the BM25 path gates actually ship (not hybrid). See `RAG_PATH_FINDINGS.md`.

## LLM review report schema (`evidence/llm_review_report.json`)

```json
{
  "run_id": "<must match the gate reports>",
  "concerns": [
    {"severity": "blocking|advisory", "code": "f02_post_index_feature",
     "message": "human-readable concern", "detail": {"feature": "lab_value_3"}}
  ]
}
```
- `blocking` → appended to `failures`, forces compliance to `none`, fails the gate.
- `advisory` → appended to `warnings` (caps score; fails only under `--strict`).

## Loop stop-conditions (CHECKPOINT — pause and wait for human review)

The overnight loop keeps grinding **only** the additive, test-covered slices. It MUST stop, leave a
note in the Progress Log below, and wait when it hits ANY of:
1. A change that **breaks/extends a gate CLI contract** (new required flag, changed envelope).
2. A change to **manifest contract, SKILL.md, CLAUDE.md, or `.github/workflows/`**.
3. A **key-custody / crypto** decision (P0.2–P0.5).
4. A test that **fails two iterations in a row** without a clear fix (per CLAUDE.md: no >1 auto-retry).
5. A **design fork** where my judgement should not be final.

Each safe iteration: implement one unchecked additive item → run its tests + the affected suite →
`pytest -q` green → granular commit + push → tick the box → append to Progress Log → next.

## Acceptance criteria
- `tests/test_publication_gate.py` stays green (no regression).
- New asymmetry tests green and cover: no-upgrade, can-block, absent-noop, malformed-fail-closed.
- `pytest -q` green on the whole suite before each push.

## Progress Log
- 2026-06-05 — branch created; P0.0 asymmetric advisory channel + tests implemented.
