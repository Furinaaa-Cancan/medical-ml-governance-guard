# RAG eval report -- 2026-05-16T20:08:46Z

- mode: `hybrid`
- scenarios source: `/Volumes/Seagate/Skill/ml-leakage-guard/references/retrieval_eval/scenarios.json`
- n_scenarios: 30 (n_evaluable=11, coverage_rate=0.367)
- **PRIMARY** mean hit@K: **1.000** (coverage = 0.37, n_evaluable=11/30)
- SECONDARY mean tag_precision@K: **0.600** (diversity-aware caveat: MMR lowers this by design; prefer hit@K for headline)
- mean top1 score: **0.616**
- zero-hit scenarios: 19
- wall time: 11797ms

## Per-scenario

| id | n_hits | top1 | hit@K | tag_p@K | wall_ms |
|----|-------:|-----:|------:|--------:|--------:|
| `leakage_discharge_icd` | 5 | 0.485 | 1 | 0.400 | 11536 |
| `evaluation_improper_f1_primary` | 0 | - | - | - | 0 |
| `no_external_validation_single_center` | 5 | 0.692 | 1 | 0.600 | 45 |
| `cohort_definition_selection_bias` | 0 | - | - | - | 0 |
| `calibration_plot_missing_no_dca` | 5 | 0.628 | 1 | 0.800 | 35 |
| `model_selection_cherry_picked_seed` | 5 | 0.643 | 1 | 0.600 | 38 |
| `split_smote_before_split` | 5 | 0.430 | 1 | 0.400 | 11 |
| `missingness_normal_range_imputation` | 5 | 0.543 | 1 | 0.400 | 13 |
| `reporting_missing_tripod_checklist` | 5 | 0.698 | 1 | 1.000 | 13 |
| `clinical_threshold_no_sensitivity_specificity` | 0 | - | - | - | 0 |
| `definition_variable_outcome_in_feature` | 0 | - | - | - | 0 |
| `imbalance_smote_without_justification` | 5 | 0.692 | 1 | 0.800 | 25 |
| `feature_selection_data_leakage` | 0 | - | - | - | 0 |
| `tuning_hyperparameter_on_test_set` | 5 | 0.602 | 1 | 0.800 | 13 |
| `ci_missing_or_suspiciously_narrow` | 5 | 0.679 | 1 | 0.400 | 15 |
| `fairness_subgroup_performance_gap` | 5 | 0.683 | 1 | 0.400 | 14 |
| `sample_size_epv_violated` | 0 | - | - | - | 0 |
| `interpretability_shap_shallow` | 0 | - | - | - | 0 |
| `covariate_shift_train_test` | 0 | - | - | - | 0 |
| `distribution_generalization_temporal` | 0 | - | - | - | 0 |
| `feature_lineage_undocumented` | 0 | - | - | - | 0 |
| `generalization_gap_optimistic` | 0 | - | - | - | 0 |
| `metric_consistency_cross_split` | 0 | - | - | - | 0 |
| `permutation_significance_missing` | 0 | - | - | - | 0 |
| `prediction_replay_irreproducible` | 0 | - | - | - | 0 |
| `robustness_no_perturbation_test` | 0 | - | - | - | 0 |
| `weak_offdomain_music_query` | 0 | - | - | - | 12 |
| `weak_offdomain_sailing_query` | 0 | - | - | - | 12 |
| `weak_offdomain_woodworking_query` | 0 | - | - | - | 14 |
| `zero_empty_query` | 0 | - | - | - | 0 |

## Coverage-drop guard

Coverage = N_evaluable / N_total = 0.37 (11/30)
(If this drops between runs, mean P@K may rise artificially; investigate before celebrating.)
