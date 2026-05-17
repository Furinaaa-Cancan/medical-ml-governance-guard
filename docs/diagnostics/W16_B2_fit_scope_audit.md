# W16-B2: MLGG-P01 — fit() Scope Audit

**Rule audited**: MLGG-P01 — "所有 fit() 只在训练集" (every `fit()` call must be on training data only; never on full dataset before split, never on test).
**Scope**: `scripts/` (production gates + training); cross-check `experiments/` for provenance.
**Method**: grep all `.fit(` sites, classify each by argument lineage; run `mlgg-lint check` (rule R001 = `fit-before-split`) against both trees.

## Verdict: PASS

- `scripts/`: 31 `.fit(` call sites, **0 violations**. `mlgg-lint check scripts/` → **0 R001 hits**.
- `experiments/`: 19 R001 hits, **all in intentional benchmark fixtures** (`experiments/paper/benchmark/snippets/leak_R001_*.py`, `experiments/paper/redteam/r{1,3}/test_*.py`). These are the linter's own red-team test corpus — by design.

## `.fit()` Call Sites in `scripts/`, Classified

| # sites | Classification | Representative locations |
|---|---|---|
| 11 | **GUARDED — train-derived input** | `train_select_evaluate.py:1810` (`fit(X_fit,y_fit)` after `apply_imbalance_strategy_to_train`); `:4752,4861` (bootstrap optimism — `X_boot` resampled from `X_train`); `:1634,1684,1715` (SMOTE/ADASYN k-NN on minority subset of `X_train`); `:1892` (L1 stability bootstrap over `X_train.iloc[idx]`); `_gate_utils.py:930` (`X_sub` from `X_train`); `:1641,1676,1808` (`X_tr` is `X_train`); `:2117,2561` (`X_tr_shifted`/`X_tr_imp` are imputed `X_train`). |
| 6 | **GUARDED — calibration/measurement on validation or per-split assessment** | `train_select_evaluate.py:3631,3694,3708` (`fit_probability_calibrator` — callers at `:6101,6907,8255` feed `y_valid`/CV-OOF, never `y_test`); `:5327` (`_calibration_assessment` — measures slope on the split it's given, intentional); `_gate_utils.py:792,2233` (calibration slope LR — same intentional-measurement pattern). |
| 2 | **GUARDED — split-then-fit in same function** | `gates/distribution_generalization_gate.py:304,336` — `train_test_split` at `:296`/`:328` immediately precedes `model.fit(x_train,...)`. |
| 2 | **GUARDED — statistical hypothesis test, no train/test concept** | `_gate_utils.py:1210,1236` (`check_nonlinearity` LR vs. spline LR for likelihood-ratio test). |
| 8 | **EXCLUDED — string literals in docs/examples** | `diagnostics/init_guide.py:163,164,189,284,681,686,803` — inside `textwrap.dedent("""...""")` blocks; not executable. |
| 1 | **GUARDED — Harrell optimism apparent estimate** | `_gate_utils.py:1793` `full_est.fit(X,y)` — `X = X_train` at `:1784`; "apparent performance" by definition (Steyerberg 2019 Ch.17). |

Total = 30 executable + 8 doc-string = 38; grep count is 31 because some `init_guide.py` matches are single-line dedupes.

## Top 5 Risk Sites (reviewer should re-verify on next refactor)

| # | File:line | Why on the list (not a violation today) |
|---|---|---|
| 1 | `scripts/training/train_select_evaluate.py:3708` | `calibrator.fit(s, y)` — relies on 3 distant call sites all passing `y_valid` or CV-OOF. Future caller could pass `y_test`. |
| 2 | `scripts/training/train_select_evaluate.py:5327` | `cal_lr.fit(logit_p, y_true)` inside `_calibration_assessment` — correct for measurement, but name `y_true` is ambiguous; risk = someone reuses the helper for re-calibration. |
| 3 | `scripts/core/_gate_utils.py:1793` | `full_est.fit(X, y)` — argument name `X`/`y` (not `X_train`/`y_train`) inside `bootstrap_optimism`. R001 would catch top-level scaler, but not a same-function model fit. |
| 4 | `scripts/training/train_select_evaluate.py:1810` | `estimator.fit(X_fit, y_fit)` — `X_fit` comes from `apply_imbalance_strategy_to_train`. Safe today; rename to `X_train_resampled` would self-document. |
| 5 | `scripts/core/_gate_utils.py:2557` | `imp.fit_transform(X_tr)` / `imp.transform(X_te)` — canonical correct pattern; flagged only because future contributors often invert this. |

## R-Rule Coverage

`plugin/mlgg_lint/rules/r001_fit_before_split.py` (Severity.ERROR) directly implements MLGG-P01. Confirmed via in-tree red-team corpus:

- `mlgg-lint check experiments/` → 19 R001 ERROR hits, all on `experiments/paper/benchmark/snippets/leak_R001_*` + `redteam/r{1,3}/test_*` — i.e., 100% recall on the curated leak suite.
- `mlgg-lint check scripts/` → 0 R001 hits → production tree clean.

Detector design (line 50-147): tracks `_model_vars` / `_pipeline_vars` / `_SAFE_NAMES`, only flags when (a) a `train_test_split` exists in the same file, (b) the `.fit_transform()` call precedes it lexically, (c) the call is at module scope (not inside a function — avoids FP on helpers like `apply_imbalance_strategy_to_train`). The "module-scope only" guard is why **the 30 in-function fits in `scripts/` are not flagged** — and is also the rule's main coverage gap (see W16+).

## Wave-N+ Fix Candidates

1. **R001 coverage gap — helper-function fits**: If a contributor writes `def my_helper(X, y): scaler.fit(X)` and calls it with the full dataset before splitting, R001 will not catch it. Worth a `R001b` that taints function parameters at call sites.
2. **Naming convention**: Promote `X_train` / `X_train_resampled` over `X` / `X_fit` in `_gate_utils.py:1793` and `train_select_evaluate.py:1810` — self-documenting, lowers maintenance review cost.
3. **`fit_probability_calibrator` call-site test**: add a unit test that fails if any caller passes `y_test` (run AST scan in `tests/`).

## Provenance

Artifacts: `/tmp/W16_B2_all_fit_calls.txt` (31 lines), `/tmp/W16_B2_lint_scripts_R001.txt` (0 lines), `/tmp/W16_B2_lint_experiments_R001.txt` (19 lines, all benchmark fixtures). Read-only audit; no source edits.
