# Lint Rules Reference (R001-R028)

> Authoritative reference for `mlgg-lint`'s AST-based static analysis rules. All rules are deterministic Python AST matchers — **no LLM in the loop**. Each rule emits a `Diagnostic` (`{rule_id, rule_name, severity, message, location, remediation, details}`) and the CLI exits 0 (no errors) or 1 (any `ERROR`-severity finding when `--exit-code` is set).
>
> This file documents the canonical 28 rules R001-R028 that ship with MLGG. The plugin also includes R029 (`credentials-in-code-availability`) as a governance/security overlay; see `plugin/mlgg_lint/rules/r029_credentials_in_code_availability.py` for that rule's source. R029 is out of scope for this reference because it is not a leakage/methodology rule.

## Quick links
- Back to README: [CN](../../README.md) | [EN](../../README_EN.md)
- Source root: `plugin/mlgg_lint/rules/`
- Architecture notes: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
- Tag style for the peer-review KB: [`docs/KB_TAG_STYLE_GUIDE.md`](../KB_TAG_STYLE_GUIDE.md)

## CLI contract

```bash
# Analyze a project tree (recursive)
mlgg-lint check path/to/project

# Disable specific rules (comma-separated)
mlgg-lint check path/to/project --disable R004,R008

# Machine-readable output
mlgg-lint check path/to/project --format json
mlgg-lint check path/to/project --format sarif

# Fail the build on ERROR-severity findings
mlgg-lint check path/to/project --exit-code

# Filter by minimum severity
mlgg-lint check path/to/project --severity warning

# List every loaded rule with name, severity, tags, and one-line description
mlgg-lint rules
```

Exit codes: `0` always unless `--exit-code` is passed and at least one `ERROR` diagnostic was emitted (then `1`). Bare `mlgg-lint check` is non-fatal so it can be used in advisory mode.

## Suppression syntax

Inline suppression uses a Flake8/Ruff-style comment placed on the offending source line:

```python
scaler.fit(X)  # noqa: R001
scaler.fit(X)  # noqa: R001, R002
scaler.fit(X)  # noqa             # bare form suppresses every rule on this line
```

Project-wide suppression goes in `.mlgg-lint.toml`:

```toml
[tool.mlgg-lint]
disabled_rules = ["R016", "R018"]    # globally off
severity_threshold = "warning"        # filter info-level diagnostics
```

Or pass `--disable R016,R018` / `--config path/to/.mlgg-lint.toml` on the command line.

## Rule taxonomy

| Group | Rules | Theme |
|---|---|---|
| Pre-split contamination | R001, R006, R020, R023, R024, R026, R027 | `fit()` / encoding / cleaning on full data before `train_test_split` |
| Test-set contamination | R002, R003, R005, R017 | Touching the holdout set during fit / threshold / early-stop |
| Splitting & sampling | R004, R008, R015 | Patient-grouping, temporal shuffle, tiny test sets |
| Cross-validation misuse | R011, R012, R025 | Resampling outside CV folds, wrong scorer, wrong Pipeline order |
| Tuning leakage | R021 | Hyperparameters tuned against the holdout |
| Target / label hazards | R007 | Target column never dropped from `X` |
| Evaluation reporting | R009, R010, R013, R022 | No CI, train-set metric, hardcoded 0.5, AUROC-only |
| Reproducibility & encoding hygiene | R014, R016, R018, R019 | Wrong encoder, missing seed, redundant scaling, multiple-comparison |
| Modality scope guard | R028 | Omics feature-name patterns reject MLGG out of scope |

Severity legend: **ERROR** (publication blocker / definite leakage), **WARNING** (likely methodological problem), **INFO** (reporting or reproducibility nit).

---

## Rule-by-rule

Each entry below mirrors the rule's source-file metadata (`id`, `name`, `severity`, `description`, `remediation`, `tags`). The "Source" link points at the file that owns the AST visitor.

### R001 — `fit-before-split` (ERROR)
- **Catches**: Preprocessor `fit()` / `fit_transform()` called at module level *before* `train_test_split` in the same file.
- **Why**: Fitting on unsplit data leaks the test distribution (mean, std, vocabulary, percentiles) into the trained pipeline.
- **AST signature**: `Call(func=Attribute(attr='fit' | 'fit_transform'))` whose receiver is not a known model / Pipeline / target encoder, evaluated before `taint.split_line`.
- **Known false-positive guards**: Skips `LogisticRegression`, every common tree / boosting / SVM class, `Pipeline` / `make_pipeline` variables, and target-encoders (`LabelEncoder`, `OrdinalEncoder` on `y`). Skips calls inside function or class bodies (helper functions may receive train-only data).
- **Example (bad)**

  ```python
  scaler = StandardScaler()
  scaler.fit(X)                          # full dataset
  X_train, X_test, y_train, y_test = train_test_split(X, y)
  ```

- **Example (good)**

  ```python
  X_train, X_test, y_train, y_test = train_test_split(X, y)
  scaler = StandardScaler().fit(X_train)
  ```

- **Remediation**: Move `fit()` after the split; better, wrap preprocessing in `sklearn.pipeline.Pipeline`.
- **Tags**: `leakage`, `preprocessing`
- **Source**: [`plugin/mlgg_lint/rules/r001_fit_before_split.py`](../../plugin/mlgg_lint/rules/r001_fit_before_split.py)

### R002 — `scaler-fit-on-test` (ERROR)
- **Catches**: `.fit()` or `.fit_transform()` whose first argument is tainted as `test` / `valid`.
- **Why**: Either leaks holdout statistics through the preprocessor or, for `GridSearchCV.fit(X_test, y_test)`, overfits hyperparameters to the holdout.
- **Example (bad)**

  ```python
  scaler.fit(X_test)                     # leaks test stats
  grid = GridSearchCV(model, params).fit(X_test, y_test)   # tunes on holdout
  ```

- **Example (good)**

  ```python
  scaler.fit(X_train)
  X_test_scaled = scaler.transform(X_test)
  grid = GridSearchCV(model, params, cv=5).fit(X_train, y_train)
  ```

- **Remediation**: Only `fit` on training data; use `.transform()` on validation / test. For HP search, run CV on the training split.
- **Tags**: `leakage`, `preprocessing`
- **Source**: [`plugin/mlgg_lint/rules/r002_scaler_on_test.py`](../../plugin/mlgg_lint/rules/r002_scaler_on_test.py)

### R003 — `resample-on-test` (ERROR)
- **Catches**: `SMOTE().fit_resample(X_test, y_test)` and variants (`ADASYN`, `BorderlineSMOTE`, `RandomOverSampler`, `RandomUnderSampler`).
- **Why**: Resampling rewrites the class balance. Doing it to validation / test destroys the only honest estimate of real-world prevalence and inflates every downstream metric.
- **Example (bad)**

  ```python
  X_test_res, y_test_res = SMOTE().fit_resample(X_test, y_test)
  auc = roc_auc_score(y_test_res, model.predict_proba(X_test_res)[:, 1])
  ```

- **Example (good)**

  ```python
  X_train_res, y_train_res = SMOTE().fit_resample(X_train, y_train)
  model.fit(X_train_res, y_train_res)
  auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
  ```

- **Remediation**: Resample only the training fold; report metrics on the untouched test set.
- **Tags**: `leakage`, `imbalance`
- **Source**: [`plugin/mlgg_lint/rules/r003_smote_on_test.py`](../../plugin/mlgg_lint/rules/r003_smote_on_test.py)

### R004 — `split-without-group` (WARNING)
- **Catches**: `train_test_split(...)` invoked in a file that also imports patient / subject / visit identifiers, with no `groups=` keyword.
- **Why**: For repeat-measures data (multiple admissions per patient, multiple slices per scan), random splitting puts the same individual in train and test — classic patient-level leakage.
- **Example (good)**

  ```python
  from sklearn.model_selection import GroupShuffleSplit
  gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
  train_idx, test_idx = next(gss.split(X, y, groups=patient_id))
  ```

- **Remediation**: Use `GroupShuffleSplit` / `GroupKFold` or pass `groups=` to `train_test_split` where supported.
- **Tags**: `leakage`, `split`
- **Source**: [`plugin/mlgg_lint/rules/r004_split_without_group.py`](../../plugin/mlgg_lint/rules/r004_split_without_group.py)

### R005 — `threshold-on-test` (ERROR)
- **Catches**: `roc_curve(y_test, ...)` / `precision_recall_curve(y_test, ...)` followed by threshold selection on the same arrays.
- **Why**: Picking an operating point on the test set is a `M01` violation — the test is no longer untouched.
- **Example (good)**

  ```python
  fpr, tpr, thresholds = roc_curve(y_valid, model.predict_proba(X_valid)[:, 1])
  best_threshold = thresholds[np.argmax(tpr - fpr)]   # tuned on valid
  test_preds = (model.predict_proba(X_test)[:, 1] >= best_threshold).astype(int)
  ```

- **Remediation**: Select thresholds on validation data; if AUC is all you need, use `roc_auc_score` directly.
- **Tags**: `leakage`, `evaluation`
- **Source**: [`plugin/mlgg_lint/rules/r005_threshold_on_test.py`](../../plugin/mlgg_lint/rules/r005_threshold_on_test.py)

### R006 — `feature-selection-on-full` (ERROR)
- **Catches**: `SelectKBest`, `RFE`, `SelectFromModel`, manual correlation filters, etc. fitted before `train_test_split`.
- **Why**: The set of "important" features is itself an estimate that uses labels — computing it on the full dataset leaks label information into the chosen columns.
- **Remediation**: Run feature selection inside a `Pipeline` so it gets refit on each CV fold or on the train split only.
- **Tags**: `leakage`, `feature-selection`
- **Source**: [`plugin/mlgg_lint/rules/r006_feature_selection_full.py`](../../plugin/mlgg_lint/rules/r006_feature_selection_full.py)

### R007 — `target-as-feature` (ERROR)
- **Catches**: `model.fit(X, y)` where `X` and `y` are both derived from the same DataFrame and the target column is never dropped from `X`.
- **Why**: The most severe form of leakage — perfect score, useless model.
- **Example (bad)**

  ```python
  X = df                       # forgot to drop 'outcome'
  y = df["outcome"]
  model.fit(X, y)
  ```

- **Example (good)**

  ```python
  y = df["outcome"]
  X = df.drop(columns=["outcome"])
  model.fit(X, y)
  ```

- **Remediation**: `X = df.drop(columns=[target])` before any `fit()`.
- **Tags**: `leakage`, `target`
- **Source**: [`plugin/mlgg_lint/rules/r007_target_as_feature.py`](../../plugin/mlgg_lint/rules/r007_target_as_feature.py)

### R008 — `temporal-split-shuffle` (WARNING)
- **Catches**: `train_test_split` with `shuffle=True` (the default) in a file that imports / uses time / date / forecast columns.
- **Why**: Random shuffling of temporal data leaks the future into the training set.
- **Remediation**: Sort by date and split chronologically, or use `TimeSeriesSplit` / a date-aware `GroupShuffleSplit`.
- **Tags**: `leakage`, `temporal`
- **Source**: [`plugin/mlgg_lint/rules/r008_temporal_split.py`](../../plugin/mlgg_lint/rules/r008_temporal_split.py)

### R009 — `no-confidence-intervals` (INFO)
- **Catches**: Evaluation metrics computed without any bootstrap / `scipy.stats.bootstrap` / `sklearn.utils.resample` call elsewhere in the file.
- **Why**: TRIPOD+AI 2024 expects 95% CI on every reported metric.
- **Remediation**: Wrap metric computation in a bootstrap (≥1000 resamples) and report `mean (95% CI)`.
- **Tags**: `reporting`, `statistics`
- **Source**: [`plugin/mlgg_lint/rules/r009_no_confidence_intervals.py`](../../plugin/mlgg_lint/rules/r009_no_confidence_intervals.py)

### R010 — `train-metric-as-final` (WARNING)
- **Catches**: `roc_auc_score(y_train, ...)` / `accuracy_score(y_train, ...)` reported as the final number.
- **Why**: Training metrics are optimistically biased; reporting them as the model's performance is misleading at best, dishonest at worst.
- **Remediation**: Compute metrics on the held-out set. Log training metrics only for overfitting diagnostics and label them as such.
- **Tags**: `evaluation`, `reporting`
- **Source**: [`plugin/mlgg_lint/rules/r010_train_metric_as_final.py`](../../plugin/mlgg_lint/rules/r010_train_metric_as_final.py)

### R011 — `cv-internal-smote` (ERROR)
- **Catches**: A `SMOTE` (or sibling) call together with a CV call (`cross_val_score`, `GridSearchCV`, etc.) where the resampler is **not** inside an `imblearn.pipeline.Pipeline`.
- **Why**: Resampling outside the CV loop also resamples each validation fold, leaking minority duplicates into evaluation and inflating CV scores.
- **Example (good)**

  ```python
  from imblearn.pipeline import Pipeline
  pipe = Pipeline([("smote", SMOTE()), ("clf", LogisticRegression())])
  cross_val_score(pipe, X_train, y_train, cv=5, scoring="average_precision")
  ```

- **Remediation**: Wrap resampling and classifier in `imblearn.pipeline.Pipeline` so resampling is applied inside each fold on training data only.
- **Tags**: `leakage`, `cross-validation`, `imbalance`
- **Source**: [`plugin/mlgg_lint/rules/r011_cv_internal_smote.py`](../../plugin/mlgg_lint/rules/r011_cv_internal_smote.py)

### R012 — `cv-accuracy-imbalanced` (WARNING)
- **Catches**: `GridSearchCV(..., scoring='accuracy')` / `cross_val_score(..., scoring='accuracy')` in a file that also imports or constructs an imbalance handler (`SMOTE`, `class_weight`, etc.).
- **Why**: Accuracy on imbalanced classes is dominated by the majority class and hides real performance.
- **Remediation**: Use `scoring='average_precision'` (AUPRC), `'roc_auc'`, or `'f1'` for imbalanced classification.
- **Tags**: `evaluation`, `imbalance`
- **Source**: [`plugin/mlgg_lint/rules/r012_cv_accuracy_imbalanced.py`](../../plugin/mlgg_lint/rules/r012_cv_accuracy_imbalanced.py)

### R013 — `hardcoded-threshold` (WARNING)
- **Catches**: Comparisons of the form `y_prob > 0.5` / `y_prob >= 0.5` followed by an `.astype(int)` cast.
- **Why**: `0.5` is the optimum threshold only when the cost of FP equals the cost of FN at prevalence = 50%. In medical contexts neither holds.
- **Remediation**: Tune the threshold on validation data using `roc_curve` / `precision_recall_curve` (then evaluate it on test — see R005).
- **Tags**: `evaluation`, `clinical`
- **Source**: [`plugin/mlgg_lint/rules/r013_hardcoded_threshold.py`](../../plugin/mlgg_lint/rules/r013_hardcoded_threshold.py)

### R014 — `label-encoder-on-features` (WARNING)
- **Catches**: `LabelEncoder` fit on feature columns (anything other than the target).
- **Why**: `LabelEncoder` was designed for `y`; using it on features imposes an arbitrary ordinal relationship that distorts distance-based and tree-based models alike.
- **Remediation**: `OrdinalEncoder` for ordinal features, `OneHotEncoder` (or `TargetEncoder` inside a Pipeline) for nominal ones.
- **Tags**: `preprocessing`, `encoding`
- **Source**: [`plugin/mlgg_lint/rules/r014_label_encoder_features.py`](../../plugin/mlgg_lint/rules/r014_label_encoder_features.py)

### R015 — `small-test-set` (WARNING)
- **Catches**: `train_test_split(..., test_size=<0.1)` — including literal floats and obvious integer rows (e.g. `test_size=50` when the dataset is large).
- **Why**: Tiny test sets yield wide CIs and unstable point estimates.
- **Remediation**: `test_size >= 0.15`; for small N consider nested cross-validation instead of a single split.
- **Tags**: `evaluation`, `split`
- **Source**: [`plugin/mlgg_lint/rules/r015_small_test_set.py`](../../plugin/mlgg_lint/rules/r015_small_test_set.py)

### R016 — `no-random-state` (INFO)
- **Catches**: Calls to stochastic sklearn / numpy APIs (splitters, ensemble models, samplers) without an explicit `random_state=` keyword.
- **Why**: Non-deterministic runs cannot be reproduced or peer-reviewed.
- **Remediation**: Pin a seed (`random_state=42`) and log it in experiment metadata.
- **Tags**: `reproducibility`
- **Source**: [`plugin/mlgg_lint/rules/r016_no_random_state.py`](../../plugin/mlgg_lint/rules/r016_no_random_state.py)

### R017 — `early-stop-on-test` (ERROR)
- **Catches**: `xgb.fit(..., eval_set=[(X_test, y_test)])` or LightGBM / CatBoost equivalents where the eval set is tainted as `test`.
- **Why**: Gradient-boosting early stopping picks the number of trees based on the eval-set loss. If that eval set is the test set, the iteration count is implicitly tuned on the holdout.
- **Remediation**: Pass a validation split — `eval_set=[(X_valid, y_valid)]` — or use nested CV.
- **Tags**: `leakage`, `tuning`
- **Source**: [`plugin/mlgg_lint/rules/r017_early_stop_on_test.py`](../../plugin/mlgg_lint/rules/r017_early_stop_on_test.py)

### R018 — `scaling-before-trees` (INFO)
- **Catches**: `StandardScaler` / `MinMaxScaler` applied to features that are immediately fed to a tree-based model (`RandomForest*`, `XGB*`, `LGBM*`, `CatBoost*`, `GradientBoosting*`).
- **Why**: Trees split on rank, not magnitude — scaling adds nothing but complexity and a Pipeline failure surface.
- **Remediation**: Drop the scaler when the downstream estimator is tree-based. Keep it for KNN / SVM / linear / MLP models.
- **Tags**: `preprocessing`, `efficiency`
- **Source**: [`plugin/mlgg_lint/rules/r018_scaling_trees.py`](../../plugin/mlgg_lint/rules/r018_scaling_trees.py)

### R019 — `multiple-comparison-no-correction` (INFO)
- **Catches**: Multiple models scored in the same file with no follow-up call to `statsmodels.stats.multitest.multipletests` (or an equivalent BH/Holm correction).
- **Why**: Comparing N candidates inflates the chance of finding a spuriously "best" one.
- **Remediation**: Apply BH FDR or Holm correction; MLGG additionally recommends the one-SE rule (Yang KDD 2023) for selecting the simplest model within 1 SE of the best validation score.
- **Tags**: `statistical`, `model-selection`
- **Source**: [`plugin/mlgg_lint/rules/r019_multiple_comparison.py`](../../plugin/mlgg_lint/rules/r019_multiple_comparison.py)

### R020 — `global-clean-before-split` (ERROR)
- **Catches**: `df.fillna(df.mean())`, `df.ffill()`, `df.bfill()`, `df.replace(...)` with global statistics applied before `train_test_split`.
- **Why**: The fill values are derived from the entire dataset (including the future test fold), leaking the test distribution into the cleaning step.
- **Remediation**: Split first, fit a `SimpleImputer` on the train split, then transform both. For temporal fills, apply within each split independently.
- **Tags**: `leakage`, `preprocessing`
- **Source**: [`plugin/mlgg_lint/rules/r020_global_clean_before_split.py`](../../plugin/mlgg_lint/rules/r020_global_clean_before_split.py)

### R021 — `test-loop-tuning` (WARNING)
- **Catches**: A loop body that both (a) mutates hyperparameters and (b) computes a metric on `X_test` / `y_test`. The `MLGG-M01` rule violation pattern.
- **Why**: Iterating over HP choices while peeking at the test score is HP tuning on the holdout in disguise.
- **Remediation**: Use a separate validation set or `GridSearchCV(..., cv=...)` for the loop; reserve the test set for one final-model evaluation.
- **Tags**: `leakage`, `model_selection`
- **Source**: [`plugin/mlgg_lint/rules/r021_test_loop_tuning.py`](../../plugin/mlgg_lint/rules/r021_test_loop_tuning.py)

### R022 — `single-metric-report` (WARNING)
- **Catches**: Only `roc_auc_score` is reported, with no companion `average_precision_score`, `brier_score_loss`, or `calibration_curve`.
- **Why**: AUROC alone hides calibration failure, class-imbalance pathology, and decision-curve harm. TRIPOD+AI 2024 and top-journal reviewers require a multi-metric panel.
- **Remediation**: Add at least AUPRC, Brier, and calibration; for clinical models also DCA and MCC.
- **Tags**: `evaluation`, `reporting`
- **Source**: [`plugin/mlgg_lint/rules/r022_single_metric_report.py`](../../plugin/mlgg_lint/rules/r022_single_metric_report.py)

### R023 — `target-encoding-leak` (ERROR)
- **Catches**: `df.groupby(<feature>)[<target>].transform(<agg>)` patterns where the value being aggregated looks like the label.
- **Why**: Target / mean encoding computed on the full dataset leaks label information into features. Done correctly it needs a leave-one-out or inner-CV strategy.
- **Remediation**: Use `category_encoders.TargetEncoder` inside a Pipeline, fitted on train only; or LOO-encoding with proper CV.
- **Tags**: `leakage`, `feature_engineering`
- **Source**: [`plugin/mlgg_lint/rules/r023_target_encoding_leak.py`](../../plugin/mlgg_lint/rules/r023_target_encoding_leak.py)

### R024 — `frequency-encoding-leak` (WARNING)
- **Catches**: `df[col].value_counts()` / `df[col].map(df[col].value_counts())` computed before `train_test_split`.
- **Why**: Category frequencies differ between splits; full-data frequencies leak the test distribution into the feature.
- **Remediation**: Compute `value_counts` on the train split only, map onto both train and test, and assign a default frequency to unseen categories.
- **Tags**: `leakage`, `feature_engineering`
- **Source**: [`plugin/mlgg_lint/rules/r024_frequency_encoding_leak.py`](../../plugin/mlgg_lint/rules/r024_frequency_encoding_leak.py)

### R025 — `smote-after-model-in-pipeline` (ERROR)
- **Catches**: `Pipeline([('clf', LogisticRegression()), ('smote', SMOTE())])` — resampler placed after the estimator.
- **Why**: Pipeline steps run in order. A resampler after the classifier never sees `fit_resample` during training and is effectively dead code that hides the missing resampling.
- **Remediation**: Reorder steps so the resampler precedes the estimator (`imputer → scaler → SMOTE → classifier`).
- **Tags**: `leakage`, `pipeline`, `imbalance`
- **Source**: [`plugin/mlgg_lint/rules/r025_smote_after_model_in_pipeline.py`](../../plugin/mlgg_lint/rules/r025_smote_after_model_in_pipeline.py)

### R026 — `fillna-before-split` (ERROR)
- **Catches**: `df.fillna(df.median())` / `df.fillna(df.mean())` and equivalents before `train_test_split`.
- **Why**: Fill values are computed from the entire dataset, leaking the test distribution into the imputation. Subset of R020 with sharper detection for the `fillna` family.
- **Remediation**: Split first, then `SimpleImputer(strategy='median')` inside a Pipeline so train statistics drive both splits.
- **Tags**: `leakage`, `preprocessing`, `imputation`
- **Source**: [`plugin/mlgg_lint/rules/r026_fillna_before_split.py`](../../plugin/mlgg_lint/rules/r026_fillna_before_split.py)

### R027 — `manual-scaling-before-split` (ERROR)
- **Catches**: Hand-rolled scaling such as `X = (X - X.mean()) / X.std()` or `X = (X - X.min()) / (X.max() - X.min())` before `train_test_split`.
- **Why**: Mean/std/min/max computed from the full dataset leak the test distribution — same hazard as R001 / R026, but the scaler is invisible to grep because no sklearn class is imported.
- **Remediation**: Split first, then `StandardScaler` / `MinMaxScaler` inside a Pipeline.
- **Tags**: `leakage`, `preprocessing`, `scaling`
- **Source**: [`plugin/mlgg_lint/rules/r027_manual_scaling_before_split.py`](../../plugin/mlgg_lint/rules/r027_manual_scaling_before_split.py)

### R028 — `omics-feature-prefix` (ERROR)
- **Catches**: A feature-name list containing ≥3 strings matching omics patterns (`gene_*`, `probe_*`, `snp_*`, `cpg_*`, `rs<digits>`, `ENSG<digits>`, `ENST<digits>`).
- **Why**: MLGG is calibrated for retrospective-cohort EHR tabular data. Omics modalities need governance MLGG does not cover (batch effects, donor-vs-cell split, the 5e-8 GWAS threshold, population stratification). Using MLGG on omics is a **modality mismatch**, not a methodology bug.
- **Remediation**: Switch to a native omics toolchain — Scanpy / scVI (scRNA-seq), TCGAbiolinks + limma / DESeq2 (TCGA bulk), PLINK + GCTA (GWAS). If you must predict clinical outcomes from molecular signatures, aggregate to a handful of scores (PRS, PAM50, risk index) before feeding MLGG.
- **Tags**: `modality`, `scope`
- **Source**: [`plugin/mlgg_lint/rules/r028_omics_feature_prefix.py`](../../plugin/mlgg_lint/rules/r028_omics_feature_prefix.py)

---

## How to add a new rule

1. Drop `r0XX_<short_name>.py` into `plugin/mlgg_lint/rules/`.
2. Subclass `BaseRule` (see `plugin/mlgg_lint/rules/base.py`) and set `id`, `name`, `severity`, `description`, `remediation`, `tags`.
3. Decorate the class with `@register` so `get_all_rules()` picks it up.
4. Override the relevant `visit_*` AST methods and call `self.report(node, message, **details)` on a finding.
5. Add fixtures under `tests/` and run `pytest plugin/mlgg_lint/tests`.
6. Append a section to this reference; run `mlgg-lint rules` to confirm the new rule is listed.

## Limitations

- AST matching is necessarily conservative. False positives in helper functions are explicitly suppressed (see R001 nested-scope guard); some genuine leakage patterns therefore slip through when they are wrapped in opaque helpers.
- Taint tracking is intra-file only — a `fit()` in `prep.py` followed by a `train_test_split` in `train.py` will not link up.
- String-based heuristics (R004 patient-id detection, R028 omics names) trade precision for recall. Use `# noqa: RXXX` to suppress documented false positives.
- The lint rules are the **first line of defense**; the 33 fail-closed runtime gates (see `scripts/gates/`) and the peer-review KB RAG layer back them up. A clean lint pass is necessary but not sufficient for publication-grade governance.

## See also

- `plugin/mlgg_lint/rules/base.py` — base class and `Diagnostic` schema
- `plugin/mlgg_lint/engine.py` — file walker, taint tracker, `# noqa` parser
- `plugin/mlgg_lint/cli.py` — argparse entrypoint for `mlgg-lint check` / `rules`
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — where lint fits in the 8-layer pipeline
- [`docs/KB_TAG_STYLE_GUIDE.md`](../KB_TAG_STYLE_GUIDE.md) — concern-tag conventions for the peer-review KB
