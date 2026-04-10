"""
Governance gates — 33 fail-closed checks for medical ML pipelines.

Each gate is a standalone CLI script with uniform contract:
    Exit 0: PASS (no issues or warnings only)
    Exit 2: FAIL (at least one failure, or --strict with warnings)
    --report PATH: Write JSON report (envelope v2.0.0)
    --strict: Promote warnings to failures

Gate categories:
    Data quality:     cohort_definition, missingness_policy, imbalance_policy
    Leakage:          leakage, definition_variable_guard, feature_lineage,
                      tuning_leakage, feature_engineering_audit
    Splitting:        split_protocol
    Evaluation:       evaluation_quality, metric_consistency, calibration_dca,
                      clinical_metrics, permutation_significance, sample_size,
                      generalization_gap, seed_stability, robustness
    Interpretability: shap_interpretability
    Fairness:         fairness_equity
    Validation:       external_validation, covariate_shift, distribution_generalization
    Compliance:       publication, reporting_bias, self_critique
    Security:         security_audit, execution_attestation, request_contract
    Model:            model_selection_audit, ci_matrix

Utility:
    manifest_lock.py  <- Gate execution state management (not a gate)
"""
