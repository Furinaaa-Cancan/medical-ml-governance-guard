# W16-B5 — MLGG-E01 / MLGG-E02 Metric Panel + CI Enforcement Audit

**Scope.** MLGG-E01 (primary metric reported with 95% CI) and MLGG-E02 (full clinical panel: AUROC + calibration + MCC + DCA). Read-only review of `scripts/gates/clinical_metrics_gate.py`, `scripts/gates/ci_matrix_gate.py`, `scripts/gates/calibration_dca_gate.py`, sibling tests, and five production `experiments/*/evidence/` reports (rhc, support2, nhanes, ckd, sepsis).

## Verdict: YELLOW

Panel enforcement and percentile-bootstrap CI are both implemented fail-closed at the gate level. Two structural holes remain.

## Per-metric coverage

| Metric | Required in `clinical_metrics_gate` | Bootstrap CI in `ci_matrix_gate` |
|---|---|---|
| AUROC (`roc_auc`) | ✓ | ✓ |
| AUPRC (`pr_auc`) | ✓ | ✓ (width-gated) |
| Sensitivity | ✓ | ✓ |
| Specificity | ✓ | ✓ |
| PPV | ✓ | ✓ |
| NPV | ✓ | ✓ |
| MCC | ✓ | ✗ (excluded from `REQUIRED_METRICS`) |
| F1 | ✓ | ✓ |
| F2_beta | ✓ | ✓ (width-gated) |
| Accuracy | ✓ | ✓ |
| Brier | ✓ | ✓ (width-gated) |
| LR+ / LR- | INFORMATIONAL only (silent skip) | Computed but not in `REQUIRED_METRICS` |
| Calibration ECE / slope / intercept | Delegated to `calibration_dca_gate` (fail-closed) | n/a |
| DCA net benefit | Delegated to `calibration_dca_gate` (fail-closed) | n/a |
| O/E ratio + CITL (BMJ 2024) | `calibration_dca_gate` | n/a |

Percentile method confirmed (`ci_matrix_gate.py:280` — `np.percentile(values, [2.5, 97.5])`). Stratified resampling, default n=2000, max 4000. Not BCa — documented design choice (lines 244–274).

## Silent-skip / fail-open sites

1. `clinical_metrics_gate.INFORMATIONAL_METRICS` (line 79): LR+ / LR- never trigger `missing_required_metric`. Justified by inf semantics but means a broken pipeline that drops them is invisible at this gate.
2. `clinical_metrics_gate` does **not** verify that `ci_matrix_report` exists or that the primary metric (AUROC) carries `ci_lower`/`ci_upper`. Cross-gate dependency only enforced at `publication_gate` (artifacts list lines 540–557).
3. `ci_matrix_gate.REQUIRED_METRICS` (lines 47–59) omits MCC and LR+/-. MCC CI present in real reports but not policed — drop it from the report and no failure fires.
4. `calibration_dca_gate.cohort_evaluation_failed` (line 572) `continue`s past failed cohorts. If every cohort errors, `cohort_results` is empty with no aggregate failure — matches W15-A3 NaN-bypass flag.
5. `dca_threshold_grid_not_prespecified` is WARNING (not failure) unless `--strict` — defaults silently allowed for non-publication runs.

## Top-5 enforcement holes

1. AUROC CI is never cross-checked against `clinical_metrics_gate`’s primary panel — relies entirely on `publication_gate` orchestration.
2. MCC CI is computed but not required; reports may drop it without a fail.
3. LR+/LR- enforcement is informational on both gates.
4. `calibration_dca_gate` all-cohort-evaluation-failure produces empty summary without aggregate `no_cohorts_evaluated` fail.
5. DCA threshold grid pre-specification is soft-gated outside `--strict`.

## Wave-N+ fix candidates

- W17: add `ci_matrix_present` + AUROC `ci_95` cross-check to `clinical_metrics_gate.finish()`.
- W17: add MCC + LR+/- to `ci_matrix_gate.REQUIRED_METRICS` and add a `no_cohorts_evaluated` fail in `calibration_dca_gate`.
- W18: promote `dca_threshold_grid_not_prespecified` to failure for publication-grade tier independent of `--strict`.

## Test coverage

`tests/test_clinical_metrics_gate.py::TestMetricValidation::test_missing_metric` confirms `pr_auc` removal → exit 2 with `missing_required_metric`. `TestPerformancePolicy::test_missing_mandatory_metric_in_policy` covers policy-side panel enforcement. No equivalent "missing AUROC CI → fail" test exists for `ci_matrix_gate`.
