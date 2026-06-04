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
- [~] **P0.1** Run-binding. **P0.1a DONE** — `publication_gate` rejects a mixed-run evidence set
      (differing `run_id` across reports → fail-closed; no-op until gates emit run_id). **P0.1b**
      (emit `run_id` from `build_report_envelope`) → CHECKPOINT (envelope contract): draft + park.
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
- [~] **P1.1** Audit trail. **Consumer-side DONE** — `publication_gate` fingerprints the advisory
      report (content sha256) and surfaces its `meta` provenance (model / prompt_hash / evidence_seen)
      into the summary. Producer-side capture (what the LLM actually saw) lands with **P1.0**.

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

**At a CHECKPOINT, before stopping:** draft a concrete, reviewable proposal for the blocked item in
the Progress Log — the design, the test plan, and a diff *sketch* (in prose / fenced blocks, NOT
applied to the contract files). This makes the morning review actionable. Then stop. Never apply a
contract/manifest/crypto change unattended, even if it looks obvious.

Note: P0.1 splits into **P0.1a** (additive, safe — `publication_gate` reads an optional `run_id`
from each component report and warns/fails on a mixed-run set; absent → no-op) and **P0.1b**
(emit `run_id` from `build_report_envelope`, a framework/envelope contract change → CHECKPOINT).
Do P0.1a; draft-and-park P0.1b.

## Acceptance criteria
- `tests/test_publication_gate.py` stays green (no regression).
- New asymmetry tests green and cover: no-upgrade, can-block, absent-noop, malformed-fail-closed.
- `pytest -q` green on the whole suite before each push.

## Progress Log
- 2026-06-05 — branch created; P0.0 asymmetric advisory channel + tests implemented.
- 2026-06-05 — P0.1a: run-binding consistency check in `publication_gate` (mixed `run_id` →
  `mixed_run_evidence` fail-closed; no-op until P0.1b stamps run_id). +4 tests
  (`test_publication_gate_run_binding.py`), 62 green, ruff clean.
- 2026-06-05 — P1.1 (consumer-side): advisory report content-hashed (sha256) + `meta` provenance
  surfaced in `publication_gate` summary. +3 tests, 65 green, ruff clean.
- 2026-06-05 — **LOOP PARKED.** All clearly-safe additive slices done (P0.0, P0.1a, P1.1; 3 commits
  pushed, 65 tests green). Everything remaining is a CHECKPOINT — see "Checkpoint Proposals" below
  for ready-to-review designs. Awaiting your sign-off (esp. threat model + the P1.0 live-LLM call).

---

# Checkpoint Proposals (awaiting your sign-off)

> Each is drafted but NOT applied — they touch the envelope/manifest/crypto contract or a design
> fork. Pick the threat model first (it sizes P0.2–P0.4). Recommended order: P0.1b → P0.2 → P0.3 →
> P0.4 → P1.0 → P2.0 → P2.1.

## P0.1b — emit `run_id` from `build_report_envelope` (envelope contract)
- **Goal:** make the dormant P0.1a check live by stamping every gate report with the run's id.
- **Design:** `run_dag_pipeline` generates one `run_id` at run start (uuid4 hex; passed to each gate
  subprocess via `MLGG_RUN_ID` env). `build_report_envelope` (`scripts/core/_gate_framework.py:188`)
  reads `os.environ.get("MLGG_RUN_ID")` and adds top-level `run_id` to the envelope. Absent env →
  field omitted (backward compatible).
- **Why checkpoint:** changes the shared envelope all 33 gates emit (+ `envelope_version` bump to
  `2.1.0`). Needs a contract-test sweep across gates.
- **Test plan:** envelope-shape test asserts `run_id` present when env set, absent when not; one
  end-to-end DAG test asserts all reports share the run_id and P0.1a passes.

## P0.2 — enrol gate-report OUTPUTS into the manifest hash (manifest contract)
- **Goal:** make a hand-edited `*_report.json` detectable (today manifest hashes only inputs).
- **Design:** after the DAG completes, `manifest_lock` re-hashes every `evidence/*_report.json` into a
  `report_hashes` map; `publication_gate` recomputes and compares. Mismatch → fail-closed.
- **Why checkpoint:** changes `manifest_lock` contract + adds a publication_gate dependency edge.

## P0.3 — `publication_gate` verifies a run-scoped seal instead of trusting `report['status']` (crypto)
- **Goal:** close C2 — the certifier trusts unsigned JSON it didn't produce.
- **Design (threat model ii):** each gate writes `report["seal"] = HMAC(run_key, canonical(report \ seal))`
  where `run_key` is injected by the orchestrator via env (`MLGG_RUN_KEY`) and **never written to the
  evidence dir**. `publication_gate` (also given the key) recomputes and verifies each component's seal
  before trusting its status (replaces the `status_is_pass` trust at `publication_gate.py:214`). No
  valid key in the agent's hands → cannot forge a passing report.
- **DECISION NEEDED:** key custody. (i) careless-runner → run_id+manifest hash is enough, skip HMAC.
  (ii) agent-as-threat → orchestrator-held env key (above). (iii) adversarial third party → external
  secret store / real signer allowlist (heavier). Default assumed = (ii).
- **Why checkpoint:** crypto + key custody + changes the certifier's core trust logic.

## P0.4 — attestation contract re-verifies signatures (crypto)
- **Goal:** `enforce_execution_attestation_publication_contract` (`publication_gate.py:238-399`) today
  inspects only `summary` fields. Make it re-run `execution_attestation_gate` (or call
  `verify_detached_signature`) against the real `trusted_signers.json` (P0.5 wires the allowlist).

## P1.0 — live LLM synthesis step (DESIGN FORK — needs your call)
- **Goal:** the producer for `evidence/llm_review_report.json` — gather all gate evidence + RAG
  concerns → LLM → structured reviewer report (Major/Minor/Questions) in the P0.0 schema, with the
  `meta` provenance P1.1 already consumes.
- **Forks for you:** (a) who runs it — a new `mlgg llm-review` subcommand the agent calls, vs inside
  `/mlgg`? (b) model + cost per run? (c) does it auto-write the advisory report, or propose-and-confirm?
  (d) how is "evidence_seen" bounded (token budget)? I will NOT make these calls unattended.

## P2.0 — bind claim tiers (may touch SKILL.md → checkpoint)
- `leakage-audited` (gates) / `+reviewer-concerns` (LLM advisory) / `publication-grade` (both + real
  attestation). Mostly wording in `publication_gate` summary + SKILL.md routing.

## P2.1 — benchmark the BM25 path gates actually ship (scope/design fork)
- Per `RAG_PATH_FINDINGS.md`: add a default eval over the BM25 retrieval gates use (not hybrid),
  faithfully replaying the gate call shape (`gate_name+codes`, no synthesized query). Sizable; needs a
  faithful-replay design decision before coding.
