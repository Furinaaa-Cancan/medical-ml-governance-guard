# W17-C4 — scenarios × gate × failure_codes coverage matrix (post-W13 re-audit)

**Date**: 2026-05-17  **Wave**: 17 strict-review  **Mode**: READ-ONLY
**Inputs**: `references/retrieval_eval/scenarios.json` (v1.1, 30 scenarios), `references/retrieval_eval/real_gate_codes_harvest.json` (20 gates × 45 distinct codes from real reports), `scripts/core/_gate_registry.py` (33 registered gates).
**Raw matrix**: `/tmp/W17_C4_matrix.json`.

## Matrix summary

| Dimension | Count |
|---|---|
| Registry gates | 33 |
| Harvest gates (≥1 real code observed) | 20 |
| Scenario gates | 27 (26 registry + 1 phantom `free_text_probe`) |
| Scenarios total | 30 |
| Scenarios with non-empty `failure_codes` | 26 |
| **Scenarios whose codes overlap real harvest (any gate)** | **2 / 26 = 7.7 %** |
| Gap-A gates (0 scenarios) | 7 (4 of these are `rag_optional=True` by design) |
| Gap-B scenarios (codes never seen in production) | 24 / 26 = 92 % |
| Gap-C harvested codes never probed by a scenario | 42 / 45 = 93 % |

## Verdict: **RED** — unchanged from W9-C1 (2/27 → 2/26)

Overlap is still **<10 %**. W13 KB/gate evolution did not change the scenario-vs-production code mismatch because nobody touched `scenarios.json` codes; only `query_text`/`expected_relevant_tags` (H10/H11 fields) and three W4 off-domain/zero probes were added. The eval suite still tests **invented** code strings, not the codes gates actually emit.

## Gap-A — registry gates with 0 scenarios (7)

| Gate | rag_optional | Real-code volume in harvest |
|---|---|---|
| `seed_stability_gate` | no | 0 (never observed) |
| `execution_attestation_gate` | no | 8 (path_escapes_sandbox ×6, attestation_stale ×2) |
| `publication_gate` | no | 43 (component_*, manifest_*, metric_report_missing_actual) |
| `request_contract_gate` | yes | 4 (feature_group_spec_missing_or_invalid) |
| `manifest_lock` | yes | 0 |
| `security_audit_gate` | yes | 60 (sensitive_data_in_evidence) |
| `self_critique_gate` | yes | 49 (component_*, missing_or_invalid_artifact) |

Top-3 priority gaps (non-`rag_optional`, real production volume): `publication_gate`, `execution_attestation_gate`, `seed_stability_gate`.

## Gap-B — top 10 phantom scenarios (codes never fire in production)

All 24 phantom scenarios listed in `/tmp/W17_C4_matrix.json`; representative top-10 by gate priority:

1. `leakage_discharge_icd` (`discharge_finalized_icd_as_feature`, `suspicious_feature_names` — real code is `temporal_overlap`)
2. `split_smote_before_split` (`smote_before_split_detected` etc. — split_protocol_gate emits nothing in harvest)
3. `tuning_hyperparameter_on_test_set` (`tuning_on_test_set_detected` — tuning_leakage_gate emits nothing in harvest)
4. `calibration_plot_missing_no_dca` (`missing_calibration_plot` — real codes: `calibration_ece_exceeds_threshold`, `calibration_oe_ratio_out_of_range`)
5. `missingness_normal_range_imputation` (real codes: `feature_missingness_too_high`, `mechanism_assessment_invalid`)
6. `fairness_subgroup_performance_gap` (real codes: `equalized_odds_gap_exceeds_threshold` ×8, `ppv_parity_exceeds_threshold` ×6)
7. `evaluation_improper_f1_primary` (real codes: `baseline_improvement_insufficient`, `primary_metric_mismatch`)
8. `sample_size_epv_violated` (`epv_below_threshold` vs real `epv_below_minimum`)
9. `definition_variable_outcome_in_feature` (real code: `target_not_found`)
10. `cohort_definition_selection_bias` (real code: `COHORT_EPV_CRITICAL`)

## Gap-C — top harvested codes with 0 scenario probe

`sensitive_data_in_evidence` (60), `self_critique component_has_failures/component_not_passed` (22+22), `publication_gate component_has_failures/component_not_passed` (19+19), `equalized_odds_gap_exceeds_threshold` (8), `path_escapes_sandbox` (6), `temporal_overlap` (6), `ppv_parity_exceeds_threshold` (6), `performance_policy_missing_required_metric` (5), `feature_missingness_too_high` (4), `mechanism_assessment_invalid` (4).

## Recommendation — Wave-N+ scenario-set regeneration

The current `scenarios.json` is a **prose-curated wish list**, not a production-grounded eval set. Recommend a **scenarios v2.0 regeneration pass**:

1. **Derive `failure_codes` from `_gate_framework.add_failure(code=...)` call sites**, not from prose — make code strings ground-truth from source, not curator imagination.
2. **Pin each scenario to a harvested-code anchor** when one exists (Gap-C top-20 list) so the eval measures retrieval against real failure modes.
3. **Add ≥1 scenario per non-`rag_optional` Gap-A gate** (`publication_gate`, `execution_attestation_gate`, `seed_stability_gate`) using harvested codes as the anchor.
4. **Keep H10/H11 `query_text`/`expected_relevant_tags` fields** — they are the retrieval-side ground truth and remain unaffected by the code mismatch.
5. **Add a CI check**: `failure_codes ⊆ {codes_in_gate_source_or_harvest}` — fail-closed prevents future drift.

Until v2.0 lands, the 26-scenario suite measures retrieval **only** for the 2 real-code anchored scenarios. Reported eval p@5 numbers on Gap-B scenarios reflect KB-tag retrieval quality, not gate-failure-code coverage.
