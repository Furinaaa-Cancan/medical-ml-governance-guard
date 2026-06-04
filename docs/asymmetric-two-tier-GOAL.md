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
- [x] **P0.1** Run-binding. **P0.1a + P0.1b DONE** — gates stamp `run_id` (from `MLGG_RUN_ID`, issued
      once per pipeline by `run_dag_pipeline`); `publication_gate` rejects a mixed-run set
      (`mixed_run_evidence`, fail-closed). Envelope field is optional/backward-compatible;
      `envelope_version` bump to 2.1.0 deferred (avoids breaking exact-match assertions).
- [x] **P0.2** Folded into P0.3 — a plain report-hash manifest is theater under threat (ii): an agent
      that can edit a report can edit the hash too. The keyed HMAC seal (P0.3) is the real binding.
- [x] **P0.3 — DONE (C2 FIXED end-to-end).** Run-scoped HMAC seal replaces `report['status']` trust.
      P0.3a primitive + P0.3b-producer (seal-on-write + per-run key) + P0.3b-consumer
      (`publication_gate.verify_component_seals`: invalid → fail always; unsealed-while-key-active →
      fail under strict; no key → no-op). Orchestrated e2e proves a status-flipped report fails despite
      `status='pass'`. Key custody = env (threat ii); threat iii needs an external secret store.
- [x] **P0.4 DONE** — `enforce_execution_attestation_publication_contract` now requires POSITIVE PROOF:
      `signature_verification.verified` is true, `trust_verification.trusted` (and `checked`) is true,
      and `allow_unsigned_mode` is not set. A real attestation run emits these; the seal (P0.3) stops
      fabrication. Defense-in-depth for C1 (contract previously trusted only policy flags).
- [x] **P0.5 — codeable part DONE.** `load_trusted_signers` is already robustly fail-closed (missing /
      bad-JSON / wrong-shape / empty → `None` → caller fails closed); now locked by explicit security
      regression tests (`test_trusted_signers.py`). Provisioning is documented in
      `references/attestation/README.md` + `ONBOARDING.md`. **OPS (flagged, NOT codeable unattended):**
      create the real `references/attestation/trusted_signers.json` with your signer fingerprints — a
      key cannot be fabricated by the loop. ⇒ **all of P0 complete.**

### P1 — build the LLM synthesis layer (the user's part ③)
- [~] **P1.0** Synthesis producer. **P1.0a DONE** — `scripts/review/llm_review.py`: gathers all gate
      evidence → pluggable adapter → writes `evidence/llm_review_report.json` (P0.0 schema). Default
      adapter is a DETERMINISTIC TEST DOUBLE (no network); `LiveClaudeReviewAdapter` is guarded so no
      unattended paid call is possible. Producer→consumer integration proven (blocking→fail, advisory→
      warn). **P1.0b (user-enabled, flagged)** — wire the real Claude call (model/cost/prompt = your
      decision); the adapter seam is ready.
- [x] **P1.1 DONE.** Consumer-side — `publication_gate` fingerprints the advisory report (content
      sha256) + surfaces its `meta` provenance into the summary. Producer-side — `llm_review.py` emits
      `meta{model, prompt_hash, evidence_seen}` (satisfied by P1.0a).

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

## Loop policy (REVISED 2026-06-05 — user: "don't stop, run all night")

The loop now PROCEEDS through checkpoints on this feature branch (reversible, PR-gated), using the
recommended defaults (threat model **ii**), test-first, committing each slice with any assumed
decision flagged in the commit body for PR-time veto. It works through P0.1b → P0.2 → P0.3 → P0.4 →
P0.5 → P1.0 → P1.1-producer → P2.0 → P2.1.

**HARD STOP — never do these unattended** (park + Progress-Log note instead):
1. A **paid / external live-LLM API call** (P1.0). Build the producer with a pluggable adapter +
   deterministic test double; leave live-model wiring as a thin, clearly-marked, user-enabled adapter.
2. Push to **main**, force-push, `reset --hard`, delete files, or touch `.github/workflows/`.
3. A test **failing two iterations in a row** with no clear fix → skip that item, log it, continue
   with the next; if every remaining item is blocked, park.

**PROCEED on the branch (flag the assumption in the commit body):** envelope / manifest / crypto /
contract changes (P0.1b–P0.5); SKILL.md / CLAUDE.md edits for P2.0 (as their own clearly-marked commit).

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
- 2026-06-05 — LOOP PARKED after P0.0/P0.1a/P1.1, then **RESUMED** on user instruction ("don't stop").
  Policy revised: proceed through checkpoints on the branch with defaults (threat model ii). See
  "Loop policy" above. Proposals below retained as the design reference being implemented.
- 2026-06-05 — P0.1b: `build_report_envelope` stamps `run_id` from `MLGG_RUN_ID`; `run_dag_pipeline`
  issues one id per run (setdefault, respects external pin). +4 envelope tests; 278 green across
  envelope/contract/e2e/DAG; ruff clean. ASSUMED: no envelope_version bump (deferred).
- 2026-06-05 — P0.2 folded into P0.3 (plain report-hash is theater under threat ii). P0.3a: run-scoped
  HMAC seal primitive in `_security.py` (canonical bytes / compute / verify). +8 unit tests, 76 green,
  ruff clean. Next: P0.3b wiring (envelope seal-on-write + orchestrator key + publication_gate verify).
- 2026-06-05 — P0.3b-producer: `build_report_envelope` seals on write (lazy `_security` import,
  best-effort, no-key→no-seal); `run_dag_pipeline` issues a per-run `MLGG_RUN_KEY` (never persisted).
  +5 tests; 191 green incl. orchestrated e2e under a live key (all components seal) + contract
  compliance; ruff clean. ASSUMED: env-var key custody (threat ii); threat iii needs an external store.
- 2026-06-05 — **P0.3b-consumer (C2 FIXED).** `publication_gate.verify_component_seals` verifies every
  component seal before trusting status (invalid→fail always; unsealed→fail under strict; no key→no-op).
  +4 tests incl. the C2 attack (flip leakage status→pass without re-seal → `component_seal_invalid`,
  fail-closed); 120 green incl. orchestrated e2e + run_dag e2e (verification live, nothing breaks);
  ruff clean. **The #1 critical finding from the harness review is now closed end-to-end.**
- 2026-06-05 — P0.4: attestation contract requires verified-signature + trusted-signer proof
  (`signature_verification.verified`, `trust_verification.trusted/checked`, no `allow_unsigned_mode`).
  Updated the `_good_execution_attestation` fixture to carry the proof. +5 tests; 88 green (full
  pub_gate regression + e2e); ruff clean. C1 defense-in-depth on top of the P0.3 seal.
- 2026-06-05 — P0.5 (codeable): `load_trusted_signers` fail-closed behavior locked by +6 regression
  tests (missing/empty/bad-fp/invalid-json/non-object → None). Provisioning already documented; real
  signer-key creation flagged as an ops task (cannot fabricate a key unattended). **ALL P0 COMPLETE.**
  88 green; ruff clean.
- 2026-06-05 — P1.0a + P1.1: `scripts/review/llm_review.py` synthesis producer (gather evidence →
  pluggable adapter → P0.0-schema report). Default = deterministic no-network double; live Claude
  adapter guarded (no unattended paid call). Producer→consumer integration proven (blocking→fail,
  advisory→warn); `meta` provenance satisfies P1.1-producer. +7 tests; ruff clean. **The asymmetric
  loop (③) is now closed end-to-end.** P1.0b (live call wiring) flagged as user-enabled.

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
