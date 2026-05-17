# W7-P1: 19/30 zero-hit investigation

**Date**: 2026-05-17  
**Baseline file**: `references/retrieval_eval/post_wave7_baseline_hybrid.json` (renamed from `post_wave5_baseline_hybrid.json` in W8-W1 deep-int)  
**Scenarios file**: `references/retrieval_eval/scenarios.json`  
**Eval script**: `scripts/rag/evals/run_eval.py`

## Summary

19 of 30 scenarios in the post-Wave-5 hybrid baseline return `n_hits=0`. Of
those, **15 are silently dropped by `run_eval.py` before retrieval ever
runs** (wall_ms=0), and **4 are deliberate weak/zero probes** (3 of those
4 actually executed — wall_ms ~12–14 ms — and correctly returned 0 hits).

Root cause: `run_eval.py::score_one` line 73 does
`query = scenario.get("query_text") or scenario.get("query", "")`, then
passes the empty string to `rag_query(...)`. `rag_query` short-circuits
empty/whitespace queries to `[]` at line 100-101 of `scripts/rag/query.py`,
**ignoring the `gate` and `failure_codes` arguments entirely**.

This diverges from the production path. `scripts/core/gate_rag_bridge.
rag_context_for_failure` calls `_synthesize_query(failure_codes, hint,
gate_name=gate_name)` (gate_rag_bridge.py:190-228), which guarantees a
non-empty query whenever a gate name is present. So in production, a gate
with no human hint still gets retrieval; in the eval harness it silently
gets nothing.

## Bucket counts

| bucket | count | scenarios |
|---|---:|---|
| (a) Missing `query_text`, has `gate_name` + `failure_codes` — **bug** | 15 | see table |
| (b) Deliberately weak/off-domain probes (`gate_name=free_text_probe`, has query) — **honest 0** | 3 | weak_offdomain_{music,sailing,woodworking}_query |
| (b') Deliberately empty query (`zero_empty_query`, whitespace-only) — **honest 0** | 1 | zero_empty_query |
| (c) Other | 0 | — |

15 of 19 are real bug, 4 of 19 are by-design negatives.

## Per-scenario detail (the 15 bucket-(a) scenarios)

| id | gate | failure_codes (n) | cats | wall_ms | cause |
|---|---|---:|---|---:|---|
| `evaluation_improper_f1_primary` | evaluation_quality_gate | 3 | evaluation_metrics, clinical_utility | 0.0 | (a) |
| `cohort_definition_selection_bias` | cohort_definition_gate | 4 | study_design | 0.0 | (a) |
| `clinical_threshold_no_sensitivity_specificity` | clinical_metrics_gate | 3 | evaluation_metrics, clinical_utility | 0.0 | (a) |
| `definition_variable_outcome_in_feature` | definition_variable_guard | 3 | data_leakage, feature_selection, study_design | 0.0 | (a) |
| `feature_selection_data_leakage` | feature_engineering_audit_gate | 3 | preprocessing, feature_selection | 0.0 | (a) |
| `sample_size_epv_violated` | sample_size_gate | 3 | sample_size, study_design | 0.0 | (a) |
| `interpretability_shap_shallow` | shap_interpretability_gate | 3 | interpretability | 0.0 | (a) |
| `covariate_shift_train_test` | covariate_shift_gate | 3 | external_validation, study_design | 0.0 | (a) |
| `distribution_generalization_temporal` | distribution_generalization_gate | 3 | external_validation | 0.0 | (a) |
| `feature_lineage_undocumented` | feature_lineage_gate | 3 | reproducibility, preprocessing | 0.0 | (a) |
| `generalization_gap_optimistic` | generalization_gap_gate | 3 | evaluation_metrics, model_selection, external_validation | 0.0 | (a) |
| `metric_consistency_cross_split` | metric_consistency_gate | 3 | reporting, evaluation_metrics | 0.0 | (a) |
| `permutation_significance_missing` | permutation_significance_gate | 3 | evaluation_metrics, reporting | 0.0 | (a) |
| `prediction_replay_irreproducible` | prediction_replay_gate | 3 | reproducibility, external_validation | 0.0 | (a) |
| `robustness_no_perturbation_test` | robustness_gate | 3 | reporting, model_selection, external_validation | 0.0 | (a) |

All 15 have non-empty `gate_name`, ≥3 `failure_codes`, ≥1 `expected_category`,
and **empty `query_text`**.

## The 4 by-design negatives (bucket b/b')

| id | gate | query_text | wall_ms | reading |
|---|---|---|---:|---|
| `weak_offdomain_music_query` | free_text_probe | `"orchestral conductor baton tempo rubato"` | 12.1 | retrieval ran, correctly returned 0 |
| `weak_offdomain_sailing_query` | free_text_probe | `"sailing tack jibe spinnaker pole"` | 12.5 | retrieval ran, correctly returned 0 |
| `weak_offdomain_woodworking_query` | free_text_probe | `"wood joinery dovetail mortise tenon"` | 14.3 | retrieval ran, correctly returned 0 |
| `zero_empty_query` | free_text_probe | `"   "` (whitespace) | 0.0 | rag_query empty-string guard; correct |

These 4 should stay zero-hit. They are H10/H19 negative-control probes —
the system getting 0 hits on "dovetail mortise tenon" is the correct behavior.

## Recommended fix (≤5 LOC in `score_one`)

Reuse the production query-synthesis helper rather than reinvent it. This
makes the eval harness see exactly what the gate→RAG bridge would see in
real use:

```python
# scripts/rag/evals/run_eval.py::score_one  (replace line 73)
from scripts.core.gate_rag_bridge import _synthesize_query
query = scenario.get("query_text") or scenario.get("query") or ""
if not query.strip() and gate:
    # Mirror production gate_rag_bridge.rag_context_for_failure: a gate
    # name + failure codes alone must be enough to retrieve. Without this,
    # 15/30 scenarios were silently dropped at the empty-query guard in
    # rag_query and counted as honest 0 hits.
    query = _synthesize_query(codes, None, gate_name=gate)
```

Critically, do **not** touch the 4 by-design negatives — they either have
`query_text` set (weak_offdomain_*) and so skip the fallback, or have
`gate_name=free_text_probe` with empty codes, producing `"free text probe"`
which is fine to query with (still expected to return 0 relevant hits).

Wait — `zero_empty_query` has `gate=free_text_probe` and empty codes. With
the fix, it would synthesise to `"free text probe"` and actually run
retrieval, possibly returning hits. That changes its semantics.

Two clean options:
1. Gate the fallback on `gate != "free_text_probe"` (treat the probe
   scenarios as a separate test class).
2. Add `expected_difficulty: ZERO` to the 4 probes in scenarios.json and
   short-circuit those at score_one (returning the synthetic
   "deliberately empty" result without calling the ranker).

Option 1 is the smaller change and keeps scenarios.json untouched. Going
with option 1.

## Expected impact on baseline

Before fix: 15 scenarios silently fail at the empty-query guard, 11 are
evaluable, coverage=11/30=0.367.

After fix: those 15 join the evaluable set. Mean hit@K will change in
either direction depending on whether the synthesised queries land on the
right concerns. Coverage rises to roughly 26/30=0.867 (15 of 19 zero-hits
become evaluable; 4 probes stay non-evaluable as designed).

Coverage-drop guard from Wave-5 A4 will catch any regression direction.

## LOC estimate

- `scripts/rag/evals/run_eval.py`: +5 LOC (import + 3-line conditional)
- `tests/test_rag_run_eval.py` (new or existing): +20 LOC for one focused test
- Baseline JSON + MD regeneration: one command, no code change

Total: ~5 LOC fix + ~20 LOC test.
