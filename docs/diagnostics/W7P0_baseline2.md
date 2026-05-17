# RAG eval report -- 2026-05-16T22:03:21Z

- mode: `hybrid`
- scenarios source: `/Volumes/Seagate/Skill/ml-leakage-guard/references/retrieval_eval/scenarios.json`
- n_scenarios: 30 (n_evaluable=26, coverage_rate=0.867)
- **PRIMARY** mean hit@K: **1.000** (coverage = 0.87, n_evaluable=26/30)
- SECONDARY mean tag_precision@K: **0.531** (diversity-aware caveat: MMR lowers this by design; prefer hit@K for headline)
- mean top1 score: **0.635**
- zero-hit scenarios: 4
- wall time: 12106ms

## Per-scenario

| id | n_hits | top1 | hit@K | tag_p@K | wall_ms |
|----|-------:|-----:|------:|--------:|--------:|
| `leakage_discharge_icd` | 5 | 0.485 | 1 | 0.400 | 11375 |
| `evaluation_improper_f1_primary` | 5 | 0.636 | 1 | 0.800 | 58 |
| `no_external_validation_single_center` | 5 | 0.692 | 1 | 0.600 | 38 |
| `cohort_definition_selection_bias` | 5 | 0.658 | 1 | 0.600 | 35 |
| `calibration_plot_missing_no_dca` | 5 | 0.628 | 1 | 0.800 | 34 |
| `model_selection_cherry_picked_seed` | 5 | 0.643 | 1 | 0.600 | 37 |
| `split_smote_before_split` | 5 | 0.430 | 1 | 0.400 | 13 |
| `missingness_normal_range_imputation` | 5 | 0.543 | 1 | 0.400 | 13 |
| `reporting_missing_tripod_checklist` | 5 | 0.698 | 1 | 1.000 | 17 |
| `clinical_threshold_no_sensitivity_specificity` | 5 | 0.669 | 1 | 0.400 | 41 |
| `definition_variable_outcome_in_feature` | 5 | 0.644 | 1 | 0.600 | 38 |
| `imbalance_smote_without_justification` | 5 | 0.692 | 1 | 0.800 | 36 |
| `feature_selection_data_leakage` | 5 | 0.642 | 1 | 0.200 | 37 |
| `tuning_hyperparameter_on_test_set` | 5 | 0.602 | 1 | 0.800 | 12 |
| `ci_missing_or_suspiciously_narrow` | 5 | 0.679 | 1 | 0.400 | 12 |
| `fairness_subgroup_performance_gap` | 5 | 0.683 | 1 | 0.400 | 12 |
| `sample_size_epv_violated` | 5 | 0.668 | 1 | 0.800 | 30 |
| `interpretability_shap_shallow` | 5 | 0.637 | 1 | 0.800 | 37 |
| `covariate_shift_train_test` | 5 | 0.596 | 1 | 0.400 | 40 |
| `distribution_generalization_temporal` | 5 | 0.631 | 1 | 0.400 | 19 |
| `feature_lineage_undocumented` | 5 | 0.638 | 1 | 0.400 | 12 |
| `generalization_gap_optimistic` | 5 | 0.614 | 1 | 0.400 | 12 |
| `metric_consistency_cross_split` | 5 | 0.662 | 1 | 0.200 | 12 |
| `permutation_significance_missing` | 5 | 0.712 | 1 | 0.600 | 46 |
| `prediction_replay_irreproducible` | 5 | 0.664 | 1 | 0.400 | 12 |
| `robustness_no_perturbation_test` | 5 | 0.662 | 1 | 0.200 | 12 |
| `weak_offdomain_music_query` | 0 | - | - | - | 11 |
| `weak_offdomain_sailing_query` | 0 | - | - | - | 12 |
| `weak_offdomain_woodworking_query` | 0 | - | - | - | 12 |
| `zero_empty_query` | 0 | - | - | - | 29 |

## Coverage-drop guard

Coverage = N_evaluable / N_total = 0.87 (26/30)
(If this drops between runs, mean P@K may rise artificially; investigate before celebrating.)
