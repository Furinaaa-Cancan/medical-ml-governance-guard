# Model Families Reference (23 Families)

> MLGG validates the 9-phase pipeline across **23 model families**, all targeting **binary classification** on retrospective cohort data (EHR / registry / case-control / cross-sectional). The 33-gate suite is **family-aware**: e.g., `calibration_dca_gate` flags resampling-induced miscalibration for `balanced_random_forest`/`easy_ensemble`/`rusboost`; `leakage_gate` switches feature-importance proxies between linear coefficients (LR/SVM-linear) and split-gain (tree-based / boosting); `model_selection_audit_gate` enforces the one-SE rule across complexity tiers from Gaussian NB (1) to TabPFN (17) to stacking (15000+).
>
> **Source of truth**: `scripts/training/train_select_evaluate.py::SUPPORTED_MODEL_FAMILIES` (line 122). All identifiers below match that registry verbatim. Aliases come from `MODEL_ALIASES` (line 166).
>
> **Out of scope**: survival models (Cox/RSF), multi-class (> 2 outcomes), regression endpoints, omics (TCGA/scRNA/GWAS), imaging, NLP, time-series. See [Out-of-scope](#out-of-scope-families) below.

## Quick links

- [Back to README (CN)](../../README.md) | [Back to README (EN)](../../README_EN.md)
- README §23 Model Families: [`README_EN.md` line 1149](../../README_EN.md)
- Training engine source: [`scripts/training/train_select_evaluate.py`](../../scripts/training/train_select_evaluate.py)
- Calibration gate source: [`scripts/gates/calibration_dca_gate.py`](../../scripts/gates/calibration_dca_gate.py)

---

## At-a-glance: all 23 families

| # | Family ID | Alias | Category | Complexity | External deps |
|--:|:---------|:------|:---------|:----------:|:--------------|
|  1 | `logistic_l1`              | `lr_l1`       | Linear        |  2 | — |
|  2 | `logistic_l2`              | `lr`, `lr_l2` | Linear        |  3 | — |
|  3 | `logistic_elasticnet`      | `lr_en`       | Linear        |  4 | — |
|  4 | `random_forest_balanced`   | `rf`          | Tree ensemble |  9 | — |
|  5 | `extra_trees_balanced`     | `extra_trees` | Tree ensemble | 10 | — |
|  6 | `hist_gradient_boosting_l2`| `hgb`         | Boosting      | 11 | — |
|  7 | `adaboost`                 | —             | Boosting      | 11 | — |
|  8 | `xgboost`                  | `xgb`         | Boosting      | 13 | `xgboost` |
|  9 | `catboost`                 | —             | Boosting      | 13 | `catboost` |
| 10 | `lightgbm`                 | `lgbm`        | Boosting      | 14 | `lightgbm` |
| 11 | `svm_linear`               | `svm_lin`     | Kernel        |  7 | — |
| 12 | `svm_rbf`                  | `svm`         | Kernel        |  8 | — |
| 13 | `knn`                      | —             | Instance      |  6 | — |
| 14 | `gaussian_nb`              | —             | Probabilistic |  1 | — |
| 15 | `decision_tree`            | `dt`          | Tree          |  5 | — |
| 16 | `mlp`                      | —             | Neural        | 15 | — |
| 17 | `tabpfn`                   | —             | Foundation    | 17 | `tabpfn` |
| 18 | `balanced_random_forest`   | `brf`         | Imbalance-RF  |  9 | `imbalanced-learn` |
| 19 | `easy_ensemble`            | `easy_ens`    | Imbalance-ens | 11 | `imbalanced-learn` |
| 20 | `rusboost`                 | `rusboost`    | Imbalance-boost | 11 | `imbalanced-learn` |
| 21 | `soft_voting`              | `voting`      | Meta-ensemble | 15000+ | (top-K base) |
| 22 | `weighted_voting`          | —             | Meta-ensemble | 15000+ | (top-K base) |
| 23 | `stacking`                 | `stack`       | Meta-ensemble | 15000+ | (top-K + meta) |

**Complexity** is a coarse rank used by `model_selection_audit_gate` for the one-SE rule (Breiman 1984) — ties on test AUROC break toward the lower-complexity family.

---

## Category overview

| Category | Families | Default calibration | Default leakage trap MLGG catches |
|:---------|:---------|:-------------------:|:----------------------------------|
| **Linear**            | `logistic_l1`, `logistic_l2`, `logistic_elasticnet`, `svm_linear` | Platt (sigmoid) | unscaled-feature magnitude bias; L1 selection on full data (Gate F03) |
| **Tree / boosting**   | `decision_tree`, `random_forest_balanced`, `extra_trees_balanced`, `hist_gradient_boosting_l2`, `adaboost`, `xgboost`, `catboost`, `lightgbm` | Isotonic | feature-importance over-trust; early-stopping on test (R017) |
| **Imbalance-aware ensembles** | `balanced_random_forest`, `easy_ensemble`, `rusboost` | Isotonic + post-hoc verify | internal resampling shifts predicted probabilities (van den Goorbergh 2022) |
| **Kernel**            | `svm_rbf` | Platt | bandwidth `gamma` tuned on test |
| **Instance / probabilistic** | `knn`, `gaussian_nb` | Isotonic / not-needed | distance-metric scale leakage; NB independence violation |
| **Neural / foundation** | `mlp`, `tabpfn` | Isotonic + temperature | embedding leakage; pretrain-distribution mismatch |
| **Meta-ensembles**    | `soft_voting`, `weighted_voting`, `stacking` | Inherit base | meta-learner fit on validation = leakage to test |

---

## Per-family detail

Each entry below lists: source location, hyperparameter grid (from `train_select_evaluate.py::_build_param_grid`), default calibration strategy, common leakage modes MLGG catches, and the gates that have family-specific behavior.

### 1. `logistic_l1`

- **Source**: `sklearn.linear_model.LogisticRegression(penalty='l1', solver='liblinear')`
- **Grid**: `C` in `{0.3, 0.1, 0.03, 1.0, 3.0}` (5 configs)
- **Calibration**: usually well-calibrated for moderate `C`; Platt scaling default
- **Common leakage modes**:
  - Standardization on full data before split (Gate P01, lint R027)
  - L1 selection on full data inflating apparent feature importance (Gate F03, lint R006)
  - `liblinear` does not natively support `class_weight='balanced'` with multinomial — use one-vs-rest
- **Family-aware gates**: `leakage_gate` uses `|coef_|` as importance proxy; `model_selection_audit_gate` recognizes sparsity as a complexity discount

### 2. `logistic_l2`

- **Source**: `sklearn.linear_model.LogisticRegression(penalty='l2')`, alias `lr`
- **Grid**: `C` in `{1.0, 0.3, 0.1, 0.03, 3.0}` (5 configs, ordered with default first per seed-first convention)
- **Calibration**: typically well-calibrated; Platt scaling default
- **Common leakage modes**: identical to `logistic_l1` minus the sparsity-on-full trap
- **Family-aware gates**: `calibration_dca_gate` accepts no recalibration if intercept ∈ [-0.1, 0.1] and slope ∈ [0.9, 1.1]

### 3. `logistic_elasticnet`

- **Source**: `LogisticRegression(penalty='elasticnet', solver='saga')`, alias `lr_en`
- **Grid**: seed `{C=0.8, l1_ratio=0.5}` + cross of `C ∈ {0.1, 0.3, 1.5, 0.05}` × `l1_ratio ∈ {0.2, 0.5, 0.8}` (13 configs)
- **Calibration**: Platt scaling default
- **Common leakage modes**: SAGA solver tolerance — non-converged runs can leak via warm-start across CV folds (we always reset between folds)
- **Family-aware gates**: same as `logistic_l2`

### 4. `random_forest_balanced`

- **Source**: `RandomForestClassifier(class_weight='balanced_subsample')`, alias `rf`
- **Grid**: seed `{n_estimators=200, max_depth=4, min_samples_split=20, min_samples_leaf=10, max_features='sqrt'}` + 71 random-grid combinations across `n_estimators ∈ {200, 400, 700}`, `max_depth ∈ {4, 6, 9}`, `min_samples_split ∈ {10, 20}`, `min_samples_leaf ∈ {5, 10, 20}`, `max_features ∈ {'sqrt', 0.6}`
- **Calibration**: Isotonic regression default (RF probabilities are pushed toward 0.5)
- **Common leakage modes**:
  - `feature_importances_` (Gini) biased toward high-cardinality features — `leakage_gate` recommends permutation importance for audit
  - Out-of-bag (OOB) score is NOT a substitute for held-out validation
  - Tree split decisions read entire training set — scaling-before-split (R018) is benign but reported as INFO
- **Family-aware gates**: `leakage_gate` uses permutation importance + Gini cross-check; `calibration_dca_gate` recommends isotonic over Platt

### 5. `extra_trees_balanced`

- **Source**: `ExtraTreesClassifier(class_weight='balanced')`, alias `extra_trees`
- **Grid**: cross of `n_estimators ∈ {200, 400, 700}`, `max_depth ∈ {5, 8, None}`, `min_samples_split ∈ {8, 16}`, `min_samples_leaf ∈ {4, 8, 16}`, `max_features ∈ {'sqrt', 0.7}` (108 configs)
- **Calibration**: Isotonic default
- **Common leakage modes**: same as `random_forest_balanced` plus randomized splits make `random_state` even more load-bearing (lint R016)
- **Family-aware gates**: `seed_stability_gate` runs the candidate at 5 distinct seeds and flags AUROC range > 0.02

### 6. `hist_gradient_boosting_l2`

- **Source**: `sklearn.ensemble.HistGradientBoostingClassifier(l2_regularization=...)`, alias `hgb`
- **Grid**: seed `{learning_rate=0.03, max_depth=3, max_iter=180, l2_regularization=5.0, min_samples_leaf=20}` + 287 cross-grid configs
- **Calibration**: Isotonic default; well-calibrated if `max_iter` not over-fit
- **Common leakage modes**:
  - Early stopping on test set (lint R017) — early stopping must use the validation split, not test
  - `categorical_features=` accepts the entire schema, but you must NOT fit the encoder on full data
- **Family-aware gates**: `model_selection_audit_gate` flags `max_iter` near the grid maximum as under-tuned

### 7. `adaboost`

- **Source**: `sklearn.ensemble.AdaBoostClassifier(estimator=DecisionTreeClassifier(max_depth=...))`
- **Grid**: cross of `n_estimators ∈ {80, 150, 250, 400}`, `learning_rate ∈ {0.03, 0.1, 0.3, 0.6}`, `max_depth ∈ {1, 2}` (32 configs)
- **Calibration**: Isotonic default — AdaBoost probabilities are well known to be poorly calibrated (margin-based)
- **Common leakage modes**: weak learner is a depth-1/2 tree — same Gini importance caveats; AdaBoost SAMME deprecation in scikit-learn 1.4+, MLGG pins SAMME.R
- **Family-aware gates**: `calibration_dca_gate` requires explicit Platt or isotonic; raw `decision_function` scores fail E02 (calibration panel)

### 8. `xgboost`

- **Source**: `xgboost.XGBClassifier`, alias `xgb`
- **Grid**: 7-axis cross — `n_estimators ∈ {200, 400, 700}`, `max_depth ∈ {3, 4, 5}`, `learning_rate ∈ {0.03, 0.05, 0.1}`, `subsample ∈ {0.8, 1.0}`, `colsample_bytree ∈ {0.7, 1.0}`, `reg_alpha ∈ {0.0, 0.5}`, `reg_lambda ∈ {1.0, 5.0}` (432 configs)
- **Calibration**: Isotonic default; XGBoost `predict_proba` is sometimes well-calibrated when `objective='binary:logistic'` and `reg_lambda` is moderate
- **Common leakage modes**:
  - `eval_set` pointing at test data (lint R017) — must point at validation
  - Categorical encoding via `enable_categorical=True` must use a fitted-on-train pipeline
  - `early_stopping_rounds` on test (R017)
- **Family-aware gates**: `leakage_gate` uses XGBoost's built-in gain importance + SHAP for cross-check; `model_selection_audit_gate` discounts complexity if `subsample < 1` (implicit regularization)

### 9. `catboost`

- **Source**: `catboost.CatBoostClassifier(verbose=False)`
- **Grid**: 5-axis — `iterations ∈ {200, 400, 700}`, `depth ∈ {3, 4, 5}`, `learning_rate ∈ {0.03, 0.05, 0.1}`, `l2_leaf_reg ∈ {3.0, 8.0, 15.0}`, `border_count ∈ {64, 128}` (162 configs)
- **Calibration**: Isotonic default; CatBoost has good native calibration when `auto_class_weights='Balanced'`
- **Common leakage modes**:
  - CatBoost handles categoricals natively — must pass `cat_features` indices that match the **train** column layout, not the full DataFrame
  - `text_features` is out of MLGG scope (text modality boundary)
- **Family-aware gates**: `feature_lineage_gate` checks that `cat_features` are not silently treated as numeric

### 10. `lightgbm`

- **Source**: `lightgbm.LGBMClassifier`, alias `lgbm`
- **Grid**: 7-axis — `n_estimators ∈ {200, 400, 700}`, `learning_rate ∈ {0.03, 0.05, 0.1}`, `num_leaves ∈ {15, 31, 63}`, `min_child_samples ∈ {10, 20}`, `reg_alpha ∈ {0.0, 0.5}`, `reg_lambda ∈ {1.0, 5.0}`, `subsample ∈ {0.8, 1.0}` (with `max_depth=-1`); 432 configs
- **Calibration**: Isotonic default
- **Common leakage modes**:
  - `early_stopping_rounds` on test (R017)
  - `num_leaves` > `2^max_depth` is silently capped — flagged as `hyperparam_inconsistent` (WARNING)
  - GOSS sampling makes seed stability more sensitive — `seed_stability_gate` thresholds tightened
- **Family-aware gates**: same as `xgboost`

### 11. `svm_linear`

- **Source**: `sklearn.svm.LinearSVC(class_weight='balanced')` wrapped via `CalibratedClassifierCV(method='sigmoid')`
- **Grid**: `C ∈ {0.01, 0.03, 0.1, 0.3, 1.0, 3.0}` (6 configs)
- **Calibration**: Platt (sigmoid) by default — LinearSVC has no native `predict_proba`
- **Common leakage modes**:
  - Scaling on full data (R027) — SVMs are scale-sensitive
  - Hinge-loss is not a proper score; raw `decision_function` cannot be reported as probability
- **Family-aware gates**: `calibration_dca_gate` always requires Platt or isotonic wrapper; `leakage_gate` uses `|coef_|` (linear)

### 12. `svm_rbf`

- **Source**: `sklearn.svm.SVC(kernel='rbf', probability=True)`, alias `svm`
- **Grid**: cross of `C ∈ {0.1, 1.0, 10.0, 100.0}` × `gamma ∈ {'scale', 'auto', 0.01, 0.001}` (16 configs)
- **Calibration**: Platt via `probability=True` (Platt scaling re-fit during training); isotonic optional post-hoc
- **Common leakage modes**:
  - `gamma` tuned on test (M01 violation) — MLGG enforces validation-only tuning
  - O(n²) memory blows up on n > 20k — MLGG warns at preflight
- **Family-aware gates**: `leakage_gate` uses permutation importance only (no native coefficients in RBF space); `model_selection_audit_gate` discounts complexity when `gamma='scale'` (data-derived default)

### 13. `knn`

- **Source**: `sklearn.neighbors.KNeighborsClassifier`
- **Grid**: cross of `n_neighbors ∈ {3, 5, 7, 11, 15}` × `weights ∈ {'uniform', 'distance'}` × `metric ∈ {'euclidean', 'manhattan'}` (20 configs)
- **Calibration**: Isotonic post-hoc — KNN probabilities are quantized to `k+1` values
- **Common leakage modes**:
  - Scaling on full data (R027) — distance metrics are scale-dominated
  - SMOTE inside CV without per-fold refit (R011) — KNN is hyper-sensitive to synthetic neighbors
- **Family-aware gates**: `leakage_gate` skips coefficient extraction; `calibration_dca_gate` requires isotonic (Platt is unstable on quantized scores)

### 14. `gaussian_nb`

- **Source**: `sklearn.naive_bayes.GaussianNB`
- **Grid**: `var_smoothing ∈ {1e-9, 1e-8, 1e-7, 1e-6, 1e-5}` (5 configs)
- **Calibration**: typically over-confident — isotonic recommended
- **Common leakage modes**:
  - Independence assumption is almost always violated in EHR data — `feature_lineage_gate` reports correlation matrix in evidence
  - `var_smoothing` tuned on test (M01)
- **Family-aware gates**: `model_selection_audit_gate` treats GNB as complexity rank 1 (baseline tier)

### 15. `decision_tree`

- **Source**: `sklearn.tree.DecisionTreeClassifier(class_weight='balanced')`, alias `dt`
- **Grid**: cross of `max_depth ∈ {3, 5, 7, 10, None}` × `min_samples_split ∈ {10, 20, 40}` × `min_samples_leaf ∈ {5, 10, 20}` (45 configs)
- **Calibration**: Isotonic post-hoc — single trees produce stepwise probabilities
- **Common leakage modes**: same as `random_forest_balanced` but no variance reduction — `model_selection_audit_gate` typically flags as overfit unless `max_depth ≤ 5`
- **Family-aware gates**: kept as a reference baseline; the gate suite intentionally accepts modest AUROC if interpretability is the deliverable

### 16. `mlp`

- **Source**: `sklearn.neural_network.MLPClassifier`
- **Grid**: cross of `hidden_layer_sizes ∈ {(64,), (128,), (64, 32), (128, 64)}` × `alpha ∈ {0.001, 0.01, 0.1}` × `learning_rate_init ∈ {0.001, 0.01}` (24 configs)
- **Calibration**: Isotonic + temperature scaling (`calibration_method='temperature'` supported)
- **Common leakage modes**:
  - Scaling on full data (R027)
  - `early_stopping=True` defaults to a validation slice carved out of train — must verify it is not the test set
  - Embedding leakage when one-hot encoder fitted on full data
- **Family-aware gates**: `calibration_dca_gate` accepts temperature scaling as an additional method beyond Platt/isotonic; `seed_stability_gate` thresholds loosened to AUROC range > 0.03 (neural variance)

### 17. `tabpfn`

- **Source**: `tabpfn.TabPFNClassifier` (foundation model, in-context learning)
- **Grid**: `n_estimators=16` (single config — TabPFN is not hyperparameter-tuned in the traditional sense)
- **Calibration**: typically well-calibrated; isotonic optional
- **Common leakage modes**:
  - Sample-size cap: TabPFN is pre-trained for n ≤ 1024 — MLGG enforces preflight cap
  - Feature-count cap: 100 features max — MLGG rejects with `tabpfn_feature_cap`
  - Pre-training distribution mismatch (the model was trained on synthetic tabular data, may not transfer to all clinical settings) — `covariate_shift_gate` warns
- **Family-aware gates**: `compute_resource_gate` reports inference latency separately (no train-time fitting)

### 18. `balanced_random_forest`

- **Source**: `imblearn.ensemble.BalancedRandomForestClassifier`, alias `brf`
- **Grid**: cross of `n_estimators ∈ {200, 400}` × `max_depth ∈ {4, 6, 9}` × `min_samples_split ∈ {10, 20}` × `min_samples_leaf ∈ {5, 10}` × `max_features ∈ {'sqrt', 0.6}` (48 configs)
- **Calibration**: **Required** post-hoc (van den Goorbergh et al., BMC Med Res Methodol 2022;22:312) — balanced bootstrap shifts predicted probabilities away from base rates
- **Common leakage modes**:
  - External SMOTE/`class_weight` must NOT be applied on top of internal balancing (`INTERNAL_IMBALANCE_FAMILIES` in `train_select_evaluate.py` line 151) — MLGG strips them automatically
  - Calibration miss is the dominant failure — `calibration_dca_gate` raises `resampling_calibration_risk` if intercept drifts > 0.15
- **Family-aware gates**: `calibration_dca_gate` raises a dedicated `resampling_calibration_risk` failure (line 53)

### 19. `easy_ensemble`

- **Source**: `imblearn.ensemble.EasyEnsembleClassifier`, alias `easy_ens`
- **Grid**: `n_estimators ∈ {10, 20, 30}` (3 configs; base estimator default `AdaBoostClassifier`)
- **Calibration**: required post-hoc (same citation as `balanced_random_forest`)
- **Common leakage modes**: same as `balanced_random_forest`; additionally, AdaBoost margin scores aggregated across the ensemble are particularly poorly calibrated
- **Family-aware gates**: same as `balanced_random_forest`

### 20. `rusboost`

- **Source**: `imblearn.ensemble.RUSBoostClassifier`
- **Grid**: cross of `n_estimators ∈ {100, 200, 400}` × `learning_rate ∈ {0.1, 0.5, 1.0}` (9 configs)
- **Calibration**: required post-hoc
- **Common leakage modes**: random-undersampling drops information — MLGG warns when prevalence < 0.05 (rare-event regime where RUSBoost discards too much signal)
- **Family-aware gates**: same as `balanced_random_forest`

### 21. `soft_voting`

- **Source**: `sklearn.ensemble.VotingClassifier(voting='soft')`, alias `voting`
- **Composition**: top-K base learners from the candidate pool (default `DEFAULT_ENSEMBLE_TOP_K = 3`)
- **Calibration**: inherits base learners — if any base is uncalibrated, the average is uncalibrated
- **Common leakage modes**:
  - Base learners must each be calibrated **before** averaging — MLGG enforces this in the ensemble assembly step
  - Selection of top-K on test data = meta-leakage (M01) — MLGG selects on validation
- **Family-aware gates**: `model_selection_audit_gate` requires the K selected bases to differ in family (diversity check); `calibration_dca_gate` re-verifies the averaged probabilities

### 22. `weighted_voting`

- **Source**: custom `WeightedVoting` wrapper around `VotingClassifier` with validation-set weights
- **Composition**: same top-K base learners as `soft_voting`, but weights are validation AUROC normalized
- **Calibration**: same as `soft_voting`
- **Common leakage modes**:
  - Weight derivation must come from validation set — `model_selection_audit_gate` rejects test-derived weights
  - If weights are computed from CV folds, the folds must not overlap with held-out evaluation
- **Family-aware gates**: same as `soft_voting`

### 23. `stacking`

- **Source**: `sklearn.ensemble.StackingClassifier`, alias `stack`
- **Composition**: top-K base learners + meta-learner (default `LogisticRegression`)
- **Calibration**: meta-learner output is recalibrated (isotonic on validation) — base calibration is **not** strictly required because the meta absorbs systematic bias
- **Common leakage modes**:
  - Meta-learner trained on base predictions over validation set — if validation overlaps with test (split bug, R004/S01), meta leaks directly to test
  - `passthrough=True` forwards raw features alongside base predictions, doubling feature-leakage surface — MLGG flags
  - Base learners must use the same CV folds when generating meta features (the `cv` argument of `StackingClassifier`)
- **Family-aware gates**: `leakage_gate` runs a dedicated `meta_leakage_check`; `model_selection_audit_gate` treats stacking as complexity rank 15000+ (penalized heavily under one-SE rule)

---

## Calibration support matrix

| Family | None acceptable | Platt (sigmoid) | Isotonic | Temperature | Notes |
|:-------|:---------------:|:---------------:|:--------:|:-----------:|:------|
| `logistic_l1`               | yes (often) | yes (default) | yes | — | Penalty pushes coefs toward 0; near-calibrated |
| `logistic_l2`               | yes (often) | yes (default) | yes | — | Same |
| `logistic_elasticnet`       | sometimes   | yes (default) | yes | — | Solver tolerance matters |
| `random_forest_balanced`    | no          | yes           | yes (default) | — | Pushed toward 0.5 |
| `extra_trees_balanced`      | no          | yes           | yes (default) | — | Same |
| `hist_gradient_boosting_l2` | sometimes   | yes           | yes (default) | — | OK if `max_iter` not overfit |
| `adaboost`                  | no          | yes           | yes (default) | — | Margin-based, always poor |
| `xgboost`                   | sometimes   | yes           | yes (default) | — | Native `binary:logistic` decent |
| `catboost`                  | sometimes   | yes           | yes (default) | — | Native `auto_class_weights` decent |
| `lightgbm`                  | sometimes   | yes           | yes (default) | — | Same as xgboost |
| `svm_linear`                | no          | yes (default, via wrapper) | yes | — | `LinearSVC` has no `predict_proba` |
| `svm_rbf`                   | no          | yes (default, via `probability=True`) | yes | — | Sklearn fits Platt internally |
| `knn`                       | no          | unstable      | yes (default) | — | Quantized scores |
| `gaussian_nb`               | no          | yes           | yes (default) | — | Over-confident by construction |
| `decision_tree`             | no          | yes           | yes (default) | — | Stepwise |
| `mlp`                       | rarely      | yes           | yes (default) | yes | Temperature is preferred for deep nets |
| `tabpfn`                    | yes (often) | yes           | yes | — | Pre-trained, generally well-calibrated |
| `balanced_random_forest`    | **never**   | yes           | yes (default) | — | Required post-hoc (van den Goorbergh 2022) |
| `easy_ensemble`             | **never**   | yes           | yes (default) | — | Same |
| `rusboost`                  | **never**   | yes           | yes (default) | — | Same |
| `soft_voting`               | inherits    | inherits      | inherits  | inherits | Each base must be calibrated |
| `weighted_voting`           | inherits    | inherits      | inherits  | inherits | Same |
| `stacking`                  | rare        | meta default  | yes       | — | Meta absorbs base bias |

"None acceptable" = the family is sometimes well-calibrated out of the box; MLGG still runs `calibration_dca_gate` and only accepts when intercept ∈ [-0.1, 0.1] and slope ∈ [0.9, 1.1].

---

## Family-to-gate exercise matrix

This matrix lists gates whose **behavior changes** based on model family. All 33 gates run for every family; only family-aware ones are shown.

| Gate | Linear | Tree / boosting | Imbalance-ens | Kernel | KNN | NB | Neural | TabPFN | Meta |
|:-----|:------:|:---------------:|:-------------:|:------:|:---:|:--:|:------:|:------:|:----:|
| `leakage_gate` (importance proxy) | `coef_` | gain + permutation | gain + permutation | permutation | skip | skip | permutation | permutation | per-base + meta-leak check |
| `calibration_dca_gate` (default method) | Platt | Isotonic | Isotonic + `resampling_calibration_risk` | Platt (RBF), Platt-wrapper (linear) | Isotonic | Isotonic | Isotonic + temperature OK | (any) | inherits / meta |
| `feature_lineage_gate` | — | Gini bias note | Gini bias note | — | — | independence-violation note | — | — | per-base lineage |
| `model_selection_audit_gate` (complexity rank) | 2–4 | 5–14 | 9–11 | 7–8 | 6 | 1 | 15 | 17 | 15000+ |
| `seed_stability_gate` (AUROC range threshold) | 0.01 | 0.02 | 0.02 | 0.02 | 0.02 | 0.01 | 0.03 (loosened) | 0.01 | 0.03 (loosened) |
| `compute_resource_gate` | train-time | train-time | train-time | train-time (O(n²) for RBF) | inference-time | train-time | train-time | inference-time (foundation) | train-time × K |
| `covariate_shift_gate` | normal | normal | normal | normal | normal | normal | normal | **strict** (pretrain mismatch) | normal |

---

## Imbalance-strategy compatibility

From `SUPPORTED_IMBALANCE_STRATEGIES` (line 156) and `INTERNAL_IMBALANCE_FAMILIES` (line 151):

| Family | `none` | `class_weight` | `random_oversample` | `random_undersample` | `smote` | `adasyn` |
|:-------|:------:|:--------------:|:-------------------:|:--------------------:|:-------:|:--------:|
| Linear (`logistic_*`, `svm_linear`) | yes | yes (default) | yes | yes | yes | yes |
| `random_forest_balanced`, `extra_trees_balanced` | yes | yes (default, via `balanced_subsample`) | yes | yes | yes | yes |
| `hist_gradient_boosting_l2`, `adaboost` | yes | yes | yes | yes | yes | yes |
| `xgboost`, `catboost`, `lightgbm` | yes | yes (via `scale_pos_weight` / `auto_class_weights`) | yes | yes | yes | yes |
| `svm_rbf` | yes | yes | yes | yes | yes | yes |
| `knn` | yes | — | yes | yes | yes (caution: synthetic neighbors) | yes |
| `gaussian_nb` | yes | — | yes | yes | yes | yes |
| `decision_tree` | yes | yes (default) | yes | yes | yes | yes |
| `mlp` | yes | — | yes | yes | yes | yes |
| `tabpfn` | yes | — | — (sample-size cap) | — (sample-size cap) | — (cap) | — (cap) |
| `balanced_random_forest`, `easy_ensemble`, `rusboost` | (internal) | (internal) | (internal) | (internal) | (internal) | (internal) |
| `soft_voting`, `weighted_voting`, `stacking` | per base | per base | per base | per base | per base | per base |

"(internal)" = family handles imbalance internally; MLGG strips external strategies (see `INTERNAL_IMBALANCE_FAMILIES`).

---

## How to select a family

The training engine (`train_select_evaluate.py`) defaults to a minimum candidate pool when no `--models` flag is passed (line 942):

```python
[
    "logistic_l1",
    "logistic_l2",
    "random_forest_balanced",
    "hist_gradient_boosting_l2",
    ...
]
```

This satisfies **MLGG-M03** (compare ≥ 3 model families) by default. To explicitly select:

```bash
# Single family
mlgg train --models logistic_l2

# Three families (M03 minimum)
mlgg train --models logistic_l2,random_forest_balanced,lightgbm

# All available (filtered by installed deps)
mlgg train --models all
```

Recommended starter trios by data characteristics:

| Data regime | Recommended trio | Rationale |
|:------------|:-----------------|:----------|
| n < 500, p < 30 | `logistic_l2`, `gaussian_nb`, `decision_tree` | Low complexity, interpretable |
| n ∈ [500, 5000], p ∈ [30, 100] | `logistic_elasticnet`, `random_forest_balanced`, `hist_gradient_boosting_l2` | Balanced bias / variance |
| n > 5000, p > 100 | `logistic_l2`, `lightgbm`, `xgboost` | Scale-friendly, gain-based |
| Severe imbalance (prevalence < 0.05) | `balanced_random_forest`, `easy_ensemble`, `logistic_l2` (with `class_weight`) | Imbalance-aware |
| n ≤ 1024, p ≤ 100, small-data clinical | `tabpfn`, `logistic_l2`, `random_forest_balanced` | Foundation + classical baselines |

---

## Out-of-scope families

The following are **explicitly out of scope** for MLGG. The framework will refuse to run if it detects these endpoints or modalities:

- **Survival models** (Cox proportional-hazards, Random Survival Forest, DeepSurv): MLGG validates **binary** endpoints. For survival analysis, use [scikit-survival](https://scikit-survival.readthedocs.io/) and a dedicated TRIPOD-survival framework. MLGG's `cohort_definition_gate` rejects time-to-event endpoints.
- **Multi-class** (> 2 outcomes): use one-vs-rest decomposition and run MLGG per pair (manual). The 33-gate suite assumes binary metrics (AUROC, MCC, DCA at single threshold).
- **Regression endpoints** (continuous outcome): MLGG provides no calibration framework for regression; use TRIPOD-regression checklist.
- **Omics models** (TCGA / scRNA-seq / GWAS): rejected by lint **R028 `omics-feature-prefix`** (feature names matching `gene_/probe_/snp_/cpg_/rs#/ENSG`). Use [Scanpy](https://scanpy.readthedocs.io/), [limma](https://bioconductor.org/packages/limma/), [PLINK](https://www.cog-genomics.org/plink/), or [TCGAbiolinks](https://bioconductor.org/packages/TCGAbiolinks/).
- **Imaging / NLP / time-series** (LSTM, Transformer-TS, CNN on radiology, BERT on notes): different governance requirements (CLAIM checklist for imaging, MI-CLAIM for clinical NLP). MLGG's preflight rejects tensor / sequence inputs.

---

## Related references

- [Gates reference](GATES.md) (when written) — full 33-gate behavior
- [Datasets reference](DATASETS.md) (when written) — 16 medical datasets
- [Analysis tools reference](ANALYSIS_TOOLS.md) (when written) — 21 analysis tools
- README §23 Model Families: [`README_EN.md`](../../README_EN.md) line 1149
- Source registry: [`scripts/training/train_select_evaluate.py`](../../scripts/training/train_select_evaluate.py) lines 122 (`SUPPORTED_MODEL_FAMILIES`), 166 (`MODEL_ALIASES`), 151 (`INTERNAL_IMBALANCE_FAMILIES`)
- Calibration logic: [`scripts/gates/calibration_dca_gate.py`](../../scripts/gates/calibration_dca_gate.py)
- van den Goorbergh R et al., *The harm of class imbalance corrections for risk prediction models*, BMC Med Res Methodol 2022;22:312
- Breiman L, *Random Forests*, Machine Learning 2001;45:5–32 (Rashomon effect background)
- Van Calster B et al., *Calibration: the Achilles heel of predictive analytics*, BMC Medicine 2019;17:230
