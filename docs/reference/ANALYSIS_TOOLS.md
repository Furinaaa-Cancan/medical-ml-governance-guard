# Analysis Tools Reference (21 Standalone Functions)

> 21 reusable analysis functions complement the 33 fail-closed gates. They live
> as importable Python callables (mostly inside `scripts/core/_gate_utils.py`),
> are consumed by the gates that need them, and can also be used ad-hoc from a
> notebook or one-off audit script.

## Provenance and naming honesty

The README badge says **"21 Analysis Tools"**. Reality check from the source
tree (2026-05-17):

- **21 callables exist** — every name in the README table resolves to a real
  function definition. The count is accurate.
- **They are NOT standalone CLIs.** Earlier internal docs framed them as
  `python3 scripts/analysis/<tool>.py --help`. There is no
  `scripts/analysis/` directory; that interface never shipped. Each tool is a
  Python function invoked via `from _gate_utils import <name>` (or, for the
  two outliers, from `cohort_definition_gate.py` and
  `shap_interpretability_gate.py`).
- **Why this matters for reviewers:** if a Nature reviewer asks "show me how
  you computed the calibration slope," the answer is "we call
  `calibration_metrics()` from inside `calibration_dca_gate.py`; the gate
  emits the slope and CI into `calibration_dca_report.json`." There is no
  separate tool to invoke.

If you want a CLI surface for any of these (e.g. to reuse the calibration
triple in an external project without spinning up the full gate), the
recommended path is:

```python
# notebook or one-off script
from scripts.core._gate_utils import calibration_metrics
result = calibration_metrics(y_true, y_score, n_bins=10)
```

For project-scoped analyses, prefer the gate that wraps the function — gates
add the input contract, schema validation, and JSON report envelope.

## Quick links

- [Back to README (EN)](../../README_EN.md) - "21 Analysis Tools" table
- [Back to README (CN)](../../README.md)
- [Architecture overview](../ARCHITECTURE.md)
- Source: [`scripts/core/_gate_utils.py`](../../scripts/core/_gate_utils.py)

---

## Tool inventory by category

| Category | Tools | Primary consumer | Reviewer question |
|---|---|---|---|
| Sample size | `riley_sample_size` | `cohort_definition_gate` | "Justify n." |
| Calibration | `calibration_metrics`, `calibration_bin_ci` | `calibration_dca_gate`, `evaluation_quality_gate` | "Slope/intercept/ECE with CI?" |
| Reclassification | `compute_nri_idi` | (library; ad-hoc) | "How much better than baseline?" |
| Learning dynamics | `learning_curve_data` | `train_select_evaluate` | "Is data sufficient?" |
| Feature diagnostics | `compute_vif`, `check_nonlinearity`, `export_model_coefficients` | `train_select_evaluate` | "Collinearity? Linearity? Coefficients?" |
| Missingness | `mnar_sensitivity_analysis`, `imputation_sensitivity`, `rubins_rules_combine` | `missingness_policy_gate`, `cohort_definition_gate` | "What if MAR is wrong?" |
| Temporal | `temporal_drift_analysis` | (library; ad-hoc) | "Still accurate post-deployment?" |
| Documentation | `generate_model_card` | (library; ad-hoc) | "Structured model documentation?" |
| Subgroup clinical utility | `subgroup_dca` | `fairness_equity_gate` | "Clinical utility for minorities?" |
| Baselines & ablation | `baseline_comparisons`, `feature_ablation` | `metric_consistency_gate` | "Better than random? Which features matter?" |
| Compute reporting | `compute_resource_report` | (library; ad-hoc) | "Training resource usage?" |
| Robustness | `robustness_stress_test`, `bootstrap_optimism_correction` | `cohort_definition_gate`, `train_select_evaluate` | "Stable against outliers? Optimism corrected?" |
| Interpretability | `_compute_pdp_ice` | `shap_interpretability_gate` | "Marginal feature impact?" |
| Multiple testing | `fdr_bh_correction` | `shap_interpretability_gate` | "Multiple comparisons corrected?" |

Total: **21 tools** (matches README badge).

---

## Per-tool detail

Every entry follows the same shape:

- **Source**: file:line of the definition.
- **Signature**: positional + keyword arguments.
- **Returns**: shape of the dict / list it emits.
- **Consumer**: which gate or pipeline stage calls it (or "library" if it is
  invoked only ad-hoc).
- **Reference**: peer-reviewed methodology citation.

### 1. `riley_sample_size`

- **Source**: `scripts/gates/cohort_definition_gate.py:217`
- **Signature**: `riley_sample_size(n_events: int, n_predictors: int, expected_auc: float = 0.75, ...)`
- **Returns**: dict with `n_required`, `epv` (events-per-variable),
  `shrinkage_factor`, `meets_requirement` (bool).
- **Consumer**: `cohort_definition_gate.py:565` (auto-invoked); also referenced
  in `missingness_policy_gate.py` hint messages.
- **Reference**: Riley RD et al. *Stat Med* 2019;38(7):1276-1296.

### 2. `calibration_metrics`

- **Source**: `scripts/core/_gate_utils.py:727`
- **Signature**: `calibration_metrics(y_true, y_score, n_bins=10)`
- **Returns**: dict with `calibration_intercept` (CITL), `calibration_slope`,
  `calibration_intercept_joint` (diagnostic), `oe_ratio`, `ece`,
  `hosmer_lemeshow_chi2/df/p`, `brier`, `brier_skill_score`, `bin_data`.
- **Consumer**: `calibration_dca_gate.py` (canonical) and indirectly
  `evaluation_quality_gate` and `reporting_bias_gate` (which check that the
  artifact reported these fields).
- **Reference**: Van Calster B et al. *BMC Med* 2019;17:230. Steyerberg EW,
  *Clinical Prediction Models*, 2nd ed., 2019.
- **Note**: uses EQUAL-WIDTH binning (vs. equal-frequency in
  `evaluation_quality_gate`); the two are intentionally complementary, see
  `calibration_dca_gate.py:153`.

### 3. `calibration_bin_ci`

- **Source**: `scripts/core/_gate_utils.py:1298`
- **Signature**: `calibration_bin_ci(y_true, y_score, n_bins=10, n_bootstrap=1000, ci_level=0.95, seed=42)`
- **Returns**: list of per-bin dicts with `mean_predicted`,
  `fraction_positive`, `ci_lower`, `ci_upper`, `n`.
- **Consumer**: library / ad-hoc. Designed for the calibration plot CI
  overlay requested by NC Reviewer #2.
- **Reference**: bootstrap percentile method; rationale documented inline.

### 4. `compute_nri_idi`

- **Source**: `scripts/core/_gate_utils.py:947`
- **Signature**: `compute_nri_idi(y_true, y_score_old, y_score_new, threshold=0.5)`
- **Returns**: dict with `categorical_nri`, `continuous_nri`, `idi`,
  `event_nri`, `nonevent_nri`.
- **Consumer**: library. Use when proposing a new model vs. an existing
  reference model.
- **Reference**: Pencina MJ et al. *Stat Med* 2008;27:157-172 (categorical),
  2011;30:11-21 (continuous).

### 5. `learning_curve_data`

- **Source**: `scripts/core/_gate_utils.py:888`
  (training-side mirror at `scripts/training/train_select_evaluate.py:4794`)
- **Signature**: `learning_curve_data(estimator, X_train, y_train, X_test, y_test, fractions=None, metric="pr_auc", seed=42)`
- **Returns**: list of dicts per fraction with `fraction`, `n_train`,
  `train_score`, `test_score`.
- **Consumer**: `train_select_evaluate.py:7026` — emitted into the eval
  report so reviewers can read sample-size sufficiency directly.
- **Reference**: Figueroa RL et al. *BMC Med Inform Decis Mak* 2012;12:8.

### 6. `compute_vif`

- **Source**: `scripts/core/_gate_utils.py:1031`
- **Signature**: `compute_vif(X, feature_names=None, threshold_warn=5.0, threshold_critical=10.0)`
- **Returns**: dict with `vif_per_feature` (list), `n_warning`, `n_critical`,
  `flagged_features`.
- **Consumer**: `train_select_evaluate.py:6470` — runs over selected features
  pre-training.
- **Reference**: PMC4888898, PMC11093476. Convention: VIF > 5 investigate,
  > 10 critical.

### 7. `check_nonlinearity`

- **Source**: `scripts/core/_gate_utils.py:1120`
- **Signature**: `check_nonlinearity(X, y, feature_names, ...)`
- **Returns**: dict with per-feature linearity-test p-values and a flag list.
- **Consumer**: `train_select_evaluate.py:6479` — invoked alongside VIF as
  part of pre-training feature diagnostics.
- **Reference**: Harrell FE, *Regression Modeling Strategies*, 2nd ed., 2015.

### 8. `export_model_coefficients`

- **Source**: `scripts/core/_gate_utils.py:1364`
- **Signature**: `export_model_coefficients(estimator, feature_names)`
- **Returns**: list of dicts with `rank`, `feature`, `coefficient` (or
  `importance` for tree models), and `abs_*`.
- **Consumer**: library. Reviewer-driven (NC Reviewer #1 Comment 4) —
  invoke after `train_select_evaluate` to dump a coefficient table.
- **Reference**: standard practice; multiclass models are rejected loudly
  rather than silently flattened.

### 9. `mnar_sensitivity_analysis`

- **Source**: `scripts/core/_gate_utils.py:2056`
- **Signature**: `mnar_sensitivity_analysis(estimator, X_train, y_train, X_test, y_test, missing_mask_train, missing_mask_test, deltas=None, metric="pr_auc", seed=42)`
- **Returns**: dict with `delta_results`, `baseline_score`, `tipping_point`,
  `tipping_threshold`.
- **Consumer**: hinted by `missingness_policy_gate.py:934` and
  `cohort_definition_gate.py:1229` (gates do not auto-invoke; they emit a
  remediation hint pointing here).
- **Reference**: Cro S et al. *Stat Med* 2020;39(21):2815-2834. PMC10481859.

### 10. `temporal_drift_analysis`

- **Source**: `scripts/core/_gate_utils.py:2158`
- **Signature**: `temporal_drift_analysis(y_true, y_score, time_values, n_windows=5, n_bins=10, *, cusum_threshold=4.0, ...)`
- **Returns**: dict with per-window calibration metrics, CUSUM trace, and
  drift-onset window index.
- **Consumer**: library. Designed for post-deployment monitoring; intended
  to feed into a future deployment-monitor gate.
- **Reference**: Davis SE et al. *JAMIA* 2020;27(9):1514-1521.

### 11. `generate_model_card`

- **Source**: `scripts/core/_gate_utils.py:2334`
- **Signature**: `generate_model_card(...)` — accepts model metadata,
  performance, and dataset cards.
- **Returns**: a Mitchell-2019-compliant model card dict (JSON-serialisable).
- **Consumer**: library. Intended endpoint for the publication artefact
  bundle; not yet wired into `publication_gate`.
- **Reference**: Mitchell M et al. *FAT\** 2019.

### 12. `imputation_sensitivity`

- **Source**: `scripts/core/_gate_utils.py:2498`
- **Signature**: `imputation_sensitivity(...)` — compares model output across
  imputation strategies.
- **Returns**: dict with per-strategy metric and concordance summary.
- **Consumer**: library; pair with `rubins_rules_combine` for multiple-
  imputation pipelines.
- **Reference**: Madley-Dowd P et al. *J Clin Epidemiol* 2019.

### 13. `subgroup_dca`

- **Source**: `scripts/core/_gate_utils.py:2597`
- **Signature**: `subgroup_dca(y_true, y_score, subgroup, thresholds=None)`
- **Returns**: per-subgroup net-benefit curves.
- **Consumer**: intended consumer is `fairness_equity_gate` (not yet
  auto-invoked there; flagged for follow-up). Currently library-only.
- **Reference**: Vickers AJ, Elkin EB. *Med Decis Making* 2006;26(6):565-574.
  PROBAST+AI 2025 subgroup utility requirement.

### 14. `baseline_comparisons`

- **Source**: `scripts/core/_gate_utils.py:1495`
- **Signature**: `baseline_comparisons(y_true, y_score, y_pred)`
- **Returns**: dict with model metrics plus `prevalence_baseline`,
  `all_positive`, `all_negative`, `improvement_over_baseline`.
- **Consumer**: library (referenced by `metric_consistency_gate.py:163` in
  required-fields list).
- **Reference**: Nature Portfolio ML Checklist Item 4D.

### 15. `feature_ablation`

- **Source**: `scripts/core/_gate_utils.py:1598`
- **Signature**: `feature_ablation(estimator, X_train, y_train, X_test, y_test, feature_names, top_n=10, metric="pr_auc", seed=42)`
- **Returns**: list of dicts per ablated feature with `feature`,
  `score_without`, `score_full`, `delta`.
- **Consumer**: `metric_consistency_gate.py:163` requires the
  `feature_ablation` field in eval reports.
- **Reference**: Nature Portfolio ML Checklist Item 4F.

### 16. `compute_resource_report`

- **Source**: `scripts/core/_gate_utils.py:1698`
- **Signature**: `compute_resource_report(...)` — captures wall time, CPU/GPU
  hours, peak memory.
- **Returns**: dict with `wall_time_sec`, `cpu_hours`, `peak_memory_mb`,
  `device`.
- **Consumer**: library. Recommended at the end of `train_select_evaluate`
  to satisfy Nature checklist Item on training resource disclosure.
- **Reference**: Nature Portfolio ML Checklist.

### 17. `rubins_rules_combine`

- **Source**: `scripts/core/_gate_utils.py:1426`
- **Signature**: `rubins_rules_combine(estimates, variances=None)`
- **Returns**: dict with `pooled_estimate`, `between_variance`,
  `within_variance`, `total_variance`, `total_se`, `degrees_of_freedom`,
  `n_imputations`.
- **Consumer**: library. Required whenever you run multiple-imputation and
  report a pooled metric.
- **Reference**: Rubin DB, *Multiple Imputation for Nonresponse in Surveys*,
  Wiley 1987. Uses the large-sample df formula; Barnard-Rubin 1999 small-
  sample df is intentionally NOT computed (would require the complete-data df
  as a separate input).

### 18. `robustness_stress_test`

- **Source**: `scripts/core/_gate_utils.py:1848`
- **Signature**: `robustness_stress_test(estimator, X, y, perturbations=None, seed=42)`
- **Returns**: dict with per-perturbation metric delta and a stability flag.
- **Consumer**: `cohort_definition_gate.py:1194` hint message; also relevant
  to `robustness_gate`.
- **Reference**: original MLGG implementation; broadly aligned with
  adversarial-robustness literature.

### 19. `bootstrap_optimism_correction`

- **Source**: `scripts/core/_gate_utils.py:1743` (training-side mirror at
  `scripts/training/train_select_evaluate.py:4689`)
- **Signature**: `bootstrap_optimism_correction(estimator, X, y, n_bootstrap=200, metric="pr_auc", seed=42)`
- **Returns**: dict with `apparent_score`, `optimism`, `corrected_score`,
  `n_bootstrap_used`.
- **Consumer**: `train_select_evaluate.py:7012` — auto-runs and emits into
  the eval report.
- **Reference**: Steyerberg EW, *Clinical Prediction Models*, 2nd ed., 2019.

### 20. `_compute_pdp_ice`

- **Source**: `scripts/gates/shap_interpretability_gate.py:852`
- **Signature**: `_compute_pdp_ice(model, X, feature_idx, ...)`
- **Returns**: PDP grid + ICE curves for one feature.
- **Consumer**: `shap_interpretability_gate.py` — internal helper. Underscore
  prefix marks it as gate-internal; treat as semi-public.
- **Reference**: Friedman JH. *Annals of Statistics* 2001;29(5):1189-1232.

### 21. `fdr_bh_correction`

- **Source**: `scripts/core/_gate_utils.py:2854`
- **Signature**: `fdr_bh_correction(p_values, alpha=0.05)`
- **Returns**: dict with `adjusted_pvalues`, `rejected` (bool list),
  `n_significant`.
- **Consumer**: `shap_interpretability_gate.py:1204` — applied to per-
  feature permutation-importance p-values.
- **Reference**: Benjamini Y, Hochberg Y. *J R Stat Soc B* 1995;57(1):289-300.

---

## Tool to gate matrix

`auto` = gate calls the tool unconditionally on its inputs.
`hint` = gate emits a remediation message naming the tool but does not invoke
it.
`requires` = gate validates that a field produced by the tool is present in
upstream reports.
empty cell = no relationship.

| Tool | cohort_definition | calibration_dca | evaluation_quality | reporting_bias | missingness_policy | metric_consistency | shap_interpretability | fairness_equity | train_select_evaluate |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| riley_sample_size           | auto |      |          |          |      |          |      |      |      |
| calibration_metrics         |      | auto | requires | requires |      |          |      |      |      |
| calibration_bin_ci          |      |      |          |          |      |          |      |      |      |
| compute_nri_idi             |      |      |          |          |      |          |      |      |      |
| learning_curve_data         |      |      |          |          |      |          |      |      | auto |
| compute_vif                 |      |      |          |          |      |          |      |      | auto |
| check_nonlinearity          |      |      |          |          |      |          |      |      | auto |
| export_model_coefficients   |      |      |          |          |      |          |      |      |      |
| mnar_sensitivity_analysis   | hint |      |          |          | hint |          |      |      |      |
| temporal_drift_analysis     |      |      |          |          |      |          |      |      |      |
| generate_model_card         |      |      |          |          |      |          |      |      |      |
| imputation_sensitivity      |      |      |          |          |      |          |      |      |      |
| subgroup_dca                |      |      |          |          |      |          |      | (planned) |  |
| baseline_comparisons        |      |      |          |          |      |          |      |      |      |
| feature_ablation            |      |      |          |          |      | requires |      |      |      |
| compute_resource_report     |      |      |          |          |      |          |      |      |      |
| rubins_rules_combine        |      |      |          |          |      |          |      |      |      |
| robustness_stress_test      | hint |      |          |          |      |          |      |      |      |
| bootstrap_optimism_correction |    |      |          |          |      |          |      |      | auto |
| _compute_pdp_ice            |      |      |          |          |      |          | auto |      |      |
| fdr_bh_correction           |      |      |          |          |      |          | auto |      |      |

---

## Standalone vs. gate-invoked

- **Auto-invoked by a gate** (output appears in the gate report without user
  action): `riley_sample_size`, `calibration_metrics`, `feature_ablation`
  (validated), `_compute_pdp_ice`, `fdr_bh_correction`.
- **Auto-invoked by `train_select_evaluate`**: `learning_curve_data`,
  `compute_vif`, `check_nonlinearity`, `bootstrap_optimism_correction`.
- **Library-only** (you must call them from a notebook or audit script):
  `calibration_bin_ci`, `compute_nri_idi`, `export_model_coefficients`,
  `temporal_drift_analysis`, `generate_model_card`, `imputation_sensitivity`,
  `subgroup_dca`, `baseline_comparisons`, `compute_resource_report`,
  `rubins_rules_combine`, `robustness_stress_test`.
- **Hint-only** (gates point at the tool in remediation messages but do not
  run it): `mnar_sensitivity_analysis`, `robustness_stress_test` (also in
  this bucket from cohort_definition_gate).

The library-only count (11) is high. That is a real gap in current
publication-workflow coverage — see "Open follow-ups" below.

---

## Open follow-ups

1. **`subgroup_dca` is not wired into `fairness_equity_gate`** despite being
   the only tool that satisfies the PROBAST+AI 2025 subgroup-utility
   requirement. Recommended next step: emit `subgroup_dca` output into
   `fairness_equity_report.json` and let the gate hard-fail if it is missing
   for any protected subgroup.
2. **`generate_model_card` is not invoked by `publication_gate`.** Should be
   the final-stage publication artefact bundler.
3. **`temporal_drift_analysis` lacks a deployment-monitor gate consumer.**
   Currently usable only via direct import; no JSON report contract exists.
4. **No CLI surface for any of the 21 tools.** If a downstream user wants to
   reuse, say, `calibration_metrics` against a CSV without standing up the
   full gate, they must write Python. Consider a thin `mlgg analyze
   <tool-name> --pred preds.csv` shim under `scripts/orchestration/`.

---

## Related references

- [Architecture](../ARCHITECTURE.md) — pipeline placement of these tools.
- [KB Tag Style Guide](../KB_TAG_STYLE_GUIDE.md) — how reviewer concerns map
  to gate codes (and from there to the tools above).
- [Contributing](../CONTRIBUTING.md) — coding standards for new analysis
  functions.
- [RAG Troubleshooting](../RAG_TROUBLESHOOTING.md) — orthogonal; for the
  retrieval layer rather than the analysis layer.
