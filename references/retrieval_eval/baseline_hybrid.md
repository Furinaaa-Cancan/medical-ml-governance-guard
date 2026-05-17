# RAG eval report -- 2026-05-17T06:07:07Z

- mode: `hybrid`
- scenarios source: `/Volumes/Seagate/Skill/ml-leakage-guard/references/retrieval_eval/scenarios.json`
- n_scenarios: 30 (n_evaluable=26, coverage_rate=0.867)
- **PRIMARY** mean hit@K: **1.000** (coverage = 0.87, n_evaluable=26/30)
- SECONDARY mean tag_precision@K: **0.669** (diversity-aware caveat: MMR lowers this by design; prefer hit@K for headline)
- mean top1 score: **0.583**
- zero-hit scenarios: 4
- wall time: 17599ms

## Per-scenario

| id | n_hits | top1 | hit@K | tag_p@K | wall_ms |
|----|-------:|-----:|------:|--------:|--------:|
| `leakage_discharge_icd` | 5 | 0.526 | 1 | 0.800 | 16959 |
| `evaluation_improper_f1_primary` | 5 | 0.714 | 1 | 0.600 | 43 |
| `no_external_validation_single_center` | 5 | 0.864 | 1 | 1.000 | 25 |
| `cohort_definition_selection_bias` | 5 | 0.736 | 1 | 1.000 | 28 |
| `calibration_plot_missing_no_dca` | 5 | 0.626 | 1 | 0.800 | 24 |
| `model_selection_cherry_picked_seed` | 5 | 0.627 | 1 | 1.000 | 34 |
| `split_smote_before_split` | 5 | 0.487 | 1 | 0.400 | 14 |
| `missingness_normal_range_imputation` | 5 | 0.474 | 1 | 0.800 | 13 |
| `reporting_missing_tripod_checklist` | 5 | 0.572 | 1 | 1.000 | 16 |
| `clinical_threshold_no_sensitivity_specificity` | 5 | 0.543 | 1 | 0.400 | 36 |
| `definition_variable_outcome_in_feature` | 5 | 0.561 | 1 | 0.600 | 25 |
| `imbalance_smote_without_justification` | 5 | 0.680 | 1 | 1.000 | 23 |
| `feature_selection_data_leakage` | 5 | 0.547 | 1 | 0.400 | 24 |
| `tuning_hyperparameter_on_test_set` | 5 | 0.478 | 1 | 1.000 | 14 |
| `ci_missing_or_suspiciously_narrow` | 5 | 0.574 | 1 | 0.400 | 14 |
| `fairness_subgroup_performance_gap` | 5 | 0.559 | 1 | 0.600 | 14 |
| `sample_size_epv_violated` | 5 | 0.787 | 1 | 1.000 | 24 |
| `interpretability_shap_shallow` | 5 | 0.534 | 1 | 0.800 | 23 |
| `covariate_shift_train_test` | 5 | 0.481 | 1 | 0.600 | 25 |
| `distribution_generalization_temporal` | 5 | 0.495 | 1 | 0.400 | 15 |
| `feature_lineage_undocumented` | 5 | 0.541 | 1 | 0.400 | 15 |
| `generalization_gap_optimistic` | 5 | 0.501 | 1 | 0.600 | 14 |
| `metric_consistency_cross_split` | 5 | 0.569 | 1 | 0.200 | 10 |
| `permutation_significance_missing` | 5 | 0.591 | 1 | 0.800 | 23 |
| `prediction_replay_irreproducible` | 5 | 0.551 | 1 | 0.600 | 14 |
| `robustness_no_perturbation_test` | 5 | 0.539 | 1 | 0.200 | 14 |
| `weak_offdomain_music_query` | 0 | - | - | - | 12 |
| `weak_offdomain_sailing_query` | 0 | - | - | - | 12 |
| `weak_offdomain_woodworking_query` | 0 | - | - | - | 10 |
| `zero_empty_query` | 0 | - | - | - | 81 |

## Coverage-drop guard

Coverage = N_evaluable / N_total = 0.87 (26/30)
(If this drops between runs, mean P@K may rise artificially; investigate before celebrating.)
