# W15-A1: Gate `finish()` Exit-Code Contract Audit

**Date**: 2026-05-17
**Auditor**: W15-A1 (READ-ONLY)
**Canonical contract** (CLAUDE.md): `should_fail = bool(failures) or (args.strict and bool(warnings))`; map to exit `2 if should_fail else 0`.

## Gates audited

33 gate scripts in `scripts/gates/*.py` (excluding `__init__.py`). 25 expose a `def finish(...)`; 7 use an internal `_finish` or inline equivalent (cohort_definition, fairness_equity, publication, sample_size, security_audit, self_critique, shap_interpretability); 1 (manifest_lock) inlines the contract.

## Verdict: **PASS**

All 33 gates implement the canonical formula verbatim and map `should_fail → 2`, else `0`. Two early-return-2 sites (cohort_definition_gate:1918, request_contract_gate:3774) are sandbox-escape security guards — exiting 2 on a path-traversal attempt is conservative-correct, not a deviation.

## Per-gate conformance table

| Gate | Variant | Conforms | Notes |
|---|---|---|---|
| calibration_dca_gate | finish() | yes | line 756 should_fail; 792 return |
| ci_matrix_gate | finish() | yes | 774, 814 |
| clinical_metrics_gate | finish() | yes | 765, 804 |
| cohort_definition_gate | _finish() | yes | 1881, 1931; sandbox early-2 at 1918 (security) |
| covariate_shift_gate | finish() | yes | 830, 871 |
| definition_variable_guard | finish() | yes | 400, 447 |
| distribution_generalization_gate | finish() | yes | 762, 808 |
| evaluation_quality_gate | finish() | yes | 707, 746 |
| execution_attestation_gate | finish() | yes | 3361, 3399 |
| external_validation_gate | finish() | yes | 736, 772 |
| fairness_equity_gate | _finish() | yes | 1029, 1058 |
| feature_engineering_audit_gate | finish() | yes | 373, 411 |
| feature_lineage_gate | finish() | yes | 469, 527 |
| generalization_gap_gate | finish() | yes | 236, 270 |
| imbalance_policy_gate | finish() | yes | 584, 644 |
| leakage_gate | finish() | yes | 616, 668 |
| manifest_lock | inline | yes | 304, 326 |
| metric_consistency_gate | finish() | yes | 418, 466 |
| missingness_policy_gate | finish() | yes | 999, 1075 |
| model_selection_audit_gate | finish() | yes | 735, 777 |
| permutation_significance_gate | finish() | yes | 234, 280 |
| prediction_replay_gate | finish() | yes | 494, 529 |
| publication_gate | inline | yes | 785, 839 |
| reporting_bias_gate | finish() | yes | 363, 396 |
| request_contract_gate | finish() | yes | 3727, 3786; sandbox early-2 at 3774 (security) |
| robustness_gate | finish() | yes | 450, 492 |
| sample_size_gate | _finish() | yes | 520, 546 |
| security_audit_gate | inline | yes | 353, 384 |
| seed_stability_gate | finish() | yes | 374, 419 |
| self_critique_gate | inline | yes | 400, 452 |
| shap_interpretability_gate | _finish() | yes | 1410, 1445 |
| split_protocol_gate | finish() | yes | 486, 550 |
| tuning_leakage_gate | finish() | yes | 425, 463 |

## Critical violations

None.

## Test cross-reference (spot check)

- `tests/test_cohort_definition_gate.py:499` expects `returncode == 2` on failure: matches.
- `tests/test_feature_lineage_gate.py:254` expects `returncode == 0` on warning-only (non-strict): matches.
- `tests/test_shap_interpretability_gate.py:568` expects `returncode == 0` on pass: matches.

## Wave-N+ fix candidates

None blocking. Optional hygiene items (severity LOW):

1. **Extract canonical helper** (LOW) — 33 inline copies of the same formula invite future drift. A `_gate_utils.compute_exit_code(failures, warnings, strict)` would centralize the contract and let future audits regress-test in one place.
2. **Lint rule** (LOW) — add an AST check in `tools/` (or pre-commit) forbidding any `return 2` / `return 0` inside `scripts/gates/` that is not gated by the canonical expression, to catch future copy-paste deviations.
3. **Document security-exit-2 carve-out** (LOW) — cohort_definition and request_contract use exit 2 for sandbox-escape; worth a one-line comment in CLAUDE.md so future auditors don't flag.
