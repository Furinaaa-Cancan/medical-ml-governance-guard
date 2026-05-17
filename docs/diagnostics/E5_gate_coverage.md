# E5: 33-Gate RAG Coverage Audit

## Summary
- Gates enumerated: **33** (registry at `scripts/core/_gate_registry.py` matches the canonical count cited in CLAUDE.md / SKILL.md)
- KB ground truth: **335 entries / 817 reviewer concerns / 29 distinct gate tags**
- 🟢 **Strong**: 27 gates
- 🟡 **Adequate**: 1 gate (`robustness_gate`)
- 🟠 **Sparse**: 1 gate (`prediction_replay_gate`)
- 🔴 **Empty (honest)**: 4 gates (`manifest_lock`, `request_contract_gate`, `security_audit_gate`, `self_critique_gate`) — all infrastructure / aggregation gates
- ❓ **Unknown name**: 0 gates — KB tag hygiene is clean, no `_gate` drift, no synonym fragmentation

## Method
- Registry source of truth: `scripts/core/_gate_registry.py` (33 `_register(GateSpec(...))` calls)
- KB source: `references/case-studies/peer-review-kb.json` (817 concerns, each with `mlgg_gates: [...]`)
- For each gate: synthesized query from typical failure codes → called `hybrid_rank(query, gate=<name>, failure_codes=[...], top_k=5)` directly (imported from `scripts/rag/retrieval/hybrid` to bypass a circular import in `scripts/rag/__init__.py` that prevents `from scripts.core.gate_rag_bridge import rag_context_for_failure`)
- "Method A" (empty query, gate filter only) **crashed for every gate** with `ValueError: query must be a non-empty string` — see "Systemic issues" #1 below
- "Method B" (typical codes as query, gate filter) succeeded for all 29 KB-tagged gates

## Coverage table

| Gate | KB count | RAG count (B) | Top-1 score | Coverage | Notes |
|------|----------|---------------|-------------|----------|-------|
| calibration_dca_gate | 103 | 5 | 0.574 | 🟢 | over-broad (>100 concerns) |
| ci_matrix_gate | 22 | 5 | 0.675 | 🟢 |  |
| clinical_metrics_gate | 163 | 5 | 0.545 | 🟢 | over-broad |
| cohort_definition_gate | 207 | 5 | 0.698 | 🟢 | over-broad |
| covariate_shift_gate | 38 | 5 | 0.650 | 🟢 |  |
| definition_variable_guard | 14 | 5 | 0.649 | 🟢 |  |
| distribution_generalization_gate | 59 | 5 | 0.685 | 🟢 |  |
| evaluation_quality_gate | **255** | 5 | 0.668 | 🟢 | **most over-broad** — catch-all |
| execution_attestation_gate | 61 | 5 | 0.624 | 🟢 | mean5=0.384 (tail dilution) |
| external_validation_gate | 93 | 5 | 0.694 | 🟢 |  |
| fairness_equity_gate | 52 | 5 | 0.699 | 🟢 |  |
| feature_engineering_audit_gate | 93 | 5 | 0.718 | 🟢 |  |
| feature_lineage_gate | 74 | 5 | 0.616 | 🟢 |  |
| generalization_gap_gate | 22 | 5 | 0.661 | 🟢 |  |
| imbalance_policy_gate | 23 | 5 | 0.709 | 🟢 |  |
| leakage_gate | 37 | 5 | 0.700 | 🟢 |  |
| manifest_lock | 0 | 0 | 0.000 | 🔴 | infra integrity check — no peer-review precedent expected |
| metric_consistency_gate | 14 | 5 | 0.676 | 🟢 |  |
| missingness_policy_gate | 29 | 5 | 0.707 | 🟢 |  |
| model_selection_audit_gate | 108 | 5 | 0.699 | 🟢 | over-broad |
| permutation_significance_gate | 17 | 5 | 0.683 | 🟢 |  |
| prediction_replay_gate | **1** | 1 | **0.033** | 🟠 | KB has 1 concern; top-1 final-score 0.033 = effectively no signal |
| publication_gate | 29 | 5 | 0.642 | 🟢 | aggregator — KB tags inherited from components |
| reporting_bias_gate | 195 | 5 | 0.666 | 🟢 | over-broad |
| request_contract_gate | 0 | 0 | 0.000 | 🔴 | infra contract validator — no peer-review precedent expected |
| robustness_gate | 7 | 5 | **0.368** | 🟡 | sparse KB and weak top-1 (just below 0.4 strong threshold) |
| sample_size_gate | 29 | 5 | 0.730 | 🟢 |  |
| security_audit_gate | 0 | 0 | 0.000 | 🔴 | infra/security audit — no peer-review precedent expected |
| seed_stability_gate | 52 | 5 | 0.712 | 🟢 | mean5=0.458 |
| self_critique_gate | 0 | 0 | 0.000 | 🔴 | post-aggregation reflection — no peer-review precedent expected |
| shap_interpretability_gate | 36 | 5 | 0.719 | 🟢 |  |
| split_protocol_gate | 29 | 5 | 0.722 | 🟢 |  |
| tuning_leakage_gate | 18 | 5 | 0.650 | 🟢 |  |

## Systemic issues

1. **`hybrid_rank` rejects empty queries (high impact)** — `rag_context_for_failure(gate, failure_codes=[])` synthesizes an empty query (`""` after stripping). `hybrid_rank` raises `ValueError: query must be a non-empty string`. This means **gate-filter-only retrieval is broken**: any caller wanting "give me all reviewer concerns tagged with this gate, ranked by KB priors" cannot do so. The bridge's docstring explicitly promises "When `failure_codes` is empty and `query_hint` is `None`, … the ranker is still invoked so the `gate=` filter alone can surface gate-relevant concerns." This contract is unmet. **Fix**: either allow `hybrid_rank` to accept empty queries (fall back to BM25-skip + gate-filter prior ordering), or have the bridge synthesize a default query like `gate_name.replace("_"," ")` when codes are empty.

2. **Circular import between `scripts.core.gate_rag_bridge` and `scripts.rag.__init__`** — `from scripts.core.gate_rag_bridge import rag_context_for_failure` fails with `ImportError: cannot import name 'rag_context_for_failure' from partially initialized module` because `scripts/rag/__init__.py` re-imports the bridge during its own initialization (line 33). Gates use direct imports so this is hidden, but any external caller using the documented import path crashes. **Fix**: drop the bridge re-export from `scripts/rag/__init__.py`, or move the bridge into `scripts/rag/` and have gates import from there.

3. **`prediction_replay_gate` has effectively zero KB coverage** — KB=1, top-1 final-score=0.033. The lone tagged concern (`PR-113-C03`) is about lack of prospective validation, not prediction replay. This is a legitimate KB gap: peer reviewers rarely flag "predictions don't replay deterministically" because most papers don't ship prediction traces at all. Two paths: (a) curate 5–10 concerns about reproducibility/seed/trace integrity into this gate's tag; (b) accept it as honestly empty and stop tagging the 1 false-positive concern.

4. **`robustness_gate` is on the borderline** — KB=7, top-1=0.368 (just below the 0.4 "strong" cutoff). The top hit (`PR-012-C04`) about "overlap in data and significance driven by few outliers" is tangential. Suggest curating subgroup-stability / temporal-drift concerns explicitly to lift this above the threshold.

5. **Six over-broad "catch-all" gates** (KB-tag count > 100, in descending order): `evaluation_quality_gate` (255), `cohort_definition_gate` (207), `reporting_bias_gate` (195), `clinical_metrics_gate` (163), `model_selection_audit_gate` (108), `calibration_dca_gate` (103). These dominate the KB and likely produce somewhat noisy top-5 hits when failure codes are generic. Consider sub-tagging or introducing a secondary `mlgg_subgate` field so the ranker can prefer narrower matches when failure codes are specific.

6. **Four 🔴 EMPTY gates are honest, not bugs** — `manifest_lock`, `request_contract_gate`, `security_audit_gate`, `self_critique_gate` are infrastructure/aggregation/reflection gates. Peer reviewers do not write "your SHA-256 manifest is wrong" or "your gate self-critique missed a recommendation." Per the governance-honesty principle in the task brief, these gates should explicitly **opt out of RAG context** in their report templates rather than embed `_No related peer-review concerns retrieved._` (which reads as a curation failure). Recommend: a `rag_optional: True` flag in `GateSpec` or an early-return in the bridge for these four gate names.

7. **No gate-name drift detected** — the 29 KB tags are a strict subset of the 33 registry names, with no typos, no `_gate` suffix mismatches, no synonym fragmentation. Earlier-feared drift between e.g. `evaluation_quality_gate` ↔ `eval_gate` is **not present**. Good hygiene.

## Verdict

**Production-ready RAG for gates: CONDITIONAL.**

- Substantive: 27/33 gates (82%) have strong KB coverage and strong RAG retrieval. The 4 EMPTY infrastructure gates are honest absences; the 2 weak gates (prediction_replay, robustness) are real curation gaps, not RAG bugs.
- Blocking: **systemic issue #1 (empty-query rejection)** breaks one of two documented retrieval modes. The bridge's "Method A" path is unusable. Either fix `hybrid_rank` to accept empty queries with a gate filter, or drop the empty-query contract from the bridge docstring.
- Blocking-light: **systemic issue #2 (circular import)** — external callers using the documented import path crash; gates work because they bypass `scripts/rag/__init__.py`.

### Top 3 curation priorities

1. **`prediction_replay_gate`** — curate 5–10 KB concerns explicitly about prediction trace integrity, replay determinism, and stochastic non-reproducibility. Currently 1 mistagged concern.
2. **`robustness_gate`** — tag 5+ concerns about subgroup robustness, temporal drift, and outlier sensitivity to lift top-1 score above 0.4.
3. **Mark `manifest_lock`, `request_contract_gate`, `security_audit_gate`, `self_critique_gate` as `rag_optional=True`** in `GateSpec` so they don't display empty `peer_review_context` blocks (governance honesty: silence > false placeholder).

### Code fixes (non-curation)

1. Fix `hybrid_rank` empty-query rejection or update bridge contract.
2. Resolve circular import between `scripts.core.gate_rag_bridge` and `scripts.rag.__init__`.
