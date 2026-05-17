# W16-B4 — MLGG-M01 Tuning Scope Audit

Wave 16, Block 4. READ-ONLY audit of the unchallengeable rule **MLGG-M01 — 测试集不参与调参** (test set is never used for hyperparameter, threshold, calibration, or early-stopping tuning).

## Tuning / threshold sites and classification

| # | Site | Mechanism | Classification |
|---|------|-----------|----------------|
| 1 | `scripts/training/train_select_evaluate.py:2178` `_optuna_search_family` | Bayesian search, scored by `cv_score_pr_auc(est, X_train, y_train, ...)` (line 2303). Caller at 6635-6639 binds `optuna_X_train = X_train`. | **TRAIN-ONLY** (clean) |
| 2 | `train_select_evaluate.py:2170` random-subsample / `_family_grid` 2322+ | Candidate scoring via `cv_score_pr_auc` on `X_train` at 6582 / 6714 / 6765. | **CV-INTERNAL on train** (clean) |
| 3 | `train_select_evaluate.py:6933` primary `choose_threshold` | Inputs gated on `threshold_selection_split ∈ {valid, cv_inner}` (6841-6878). Test split never referenced. | **TRAIN-OR-VALID-ONLY** (clean) |
| 4 | `train_select_evaluate.py:8270` per-seed threshold | Same branch logic; `X_test` appears only at 8282 for one-shot post-lock metric eval. | **TRAIN-OR-VALID-ONLY** (clean) |
| 5 | `train_select_evaluate.py:6112` `_train_eval_alt_candidate` (overfit recovery) | Docstring "no test data"; gaps computed on train-valid only. | **TRAIN-OR-VALID-ONLY** (clean) |
| 6 | `scripts/diagnostics/init_guide.py:817-818` | Pedagogical template; Youden's J on `y_valid` (line 804 comment cites MLGG-M01). | **VALID-ONLY** (template OK) |
| 7 | `scripts/reporting/quick_summary.py:101` | Reads `threshold_selection` block for reporting; no compute. | N/A |

No grep hit for `GridSearchCV`, `RandomizedSearchCV`, `HalvingGridSearchCV`, `hyperopt`, or `skopt` in `scripts/`. Optuna is the only optimizer, and every invocation is bound to `X_train` / `y_train`.

## Declarative gatekeepers

- **`scripts/gates/tuning_leakage_gate.py`** (469 LOC)
  - Lines 140-143, 237-249: explicit booleans `test_used_for_{model_selection,early_stopping,threshold_selection,calibration}=true` → fail.
  - Lines 224-235: `contains_test_token()` scan of `model_selection_data`, `early_stopping_data`, `final_model_refit_scope`.
  - Lines 290-297: whitelists `model_selection_data ⊂ {valid, cv_inner, nested_cv}`.
  - Lines 186-200: whitelists `final_model_refit_scope ⊂ {train_only, train_plus_valid_no_test, outer_train_only}`.
- **`scripts/gates/model_selection_audit_gate.py:112-128`** — `_ALLOWED_TEST_KEYS` + `scan_candidate_for_test_usage` AST-walks emitted candidate JSON for any key containing `"test"` not in the allowlist; flags `model_selection_test_data_leak`.
- **`scripts/gates/clinical_metrics_gate.py:247-310`** — validates `threshold_selection.selection_split ∈ {valid, cv_inner, nested_cv}`; cross-checks `performance_policy.threshold_policy.selection_split`.
- **Runtime emission:** `train_select_evaluate.py:7098,7104` hard-codes `test_used_for_model_selection=False` in the model-selection report, so a hand-edited tuning spec cannot trick downstream gates.
- **Adversarial coverage:** `experiments/authority-e2e/run_adversarial_gate_checks.py:358` flips `test_used_for_model_selection=True`; tuning_leakage_gate must reject. (Live coverage exists.)

## Real-experiment provenance (sampled)

`experiments/{rhc,sepsis,nhanes,support2-leaky}-benchmark/configs/tuning_protocol.json` all declare:

```
model_selection_data: "valid"
early_stopping_data:  "cv_inner"
test_used_for_{model_selection,early_stopping,threshold_selection,calibration}: false
```

Even the deliberately leaky benchmark (`support2-benchmark-leaky`) leaks via *feature*, not *tuning scope* — MLGG-M01 itself remains clean.

## Verdict

**PASS — 0 violations.** Defense-in-depth: (a) source-level — `X_test` never threads into any optimizer/threshold call; (b) declarative — tuning_protocol_spec rejects test references; (c) emitted-report — model_selection_audit_gate AST-scans for stray `*test*` keys; (d) downstream — clinical_metrics_gate validates `selection_split` whitelist; (e) adversarial test exercises the failure path.

## Top 5 risk sites (residual, low)

1. `train_select_evaluate.py:8282-8284` — `X_test` evaluation is physically adjacent to per-seed `choose_threshold` (8270). Refactor risk: if someone swaps the order or hoists `test_proba_seed` above the threshold call, M01 breaks. Suggest extracting a `lock_threshold_then_eval_on_test()` helper that makes the dependency explicit.
2. `train_select_evaluate.py:6105-6111` — when `threshold_selection_split == "cv_inner"` AND `_has_valid_eval` is True, the guard split uses `y_valid` (correct). The fallback at 6108-6111 re-uses cv_oof on train. Correct, but the branch is subtle. Add an assertion that the picked `g_y` is not `y_test`.
3. `init_guide.py:817-818` — pedagogical Youden's J on valid is fine, but the template prints `Optimal threshold (Youden's J on valid)`. A student copy-pasting and substituting `y_valid → y_test` would silently violate M01. Suggest a `# DO NOT replace y_valid with y_test` comment.
4. `tuning_leakage_gate.py:147-154` — `allowed_search_methods` includes `"manual_pre_registered"`. This bypasses CV scope checks via free-form registration. Consider requiring `pre_registration_doc_sha` when this strategy is declared.
5. No static AST rule scans third-party / experiment scripts (e.g., `experiments/*/*.py`) for `GridSearchCV(X, y)` calls that pass full data. Today the repo doesn't use these APIs, but external contributors might.

## Coverage gap: static R-rule

There is **no static R-rule** that catches `sklearn.model_selection.GridSearchCV(..., X, y)` invocations where `X` is the full dataset rather than `X_train`. The repo's own training script avoids this by design (only optuna, only `X_train`), so the *current* risk surface is empty. But the moment someone adds a new training script using sklearn search APIs, the declarative tuning_protocol_spec is the only defense.

## Wave-N+ fix candidates

- **W17 candidate (low):** Add `scripts/gates/static_tuning_api_rule.py` — AST scan that flags any `GridSearchCV/RandomizedSearchCV/HalvingGridSearchCV/...` call where the second positional argument's identifier does not end in `_train` (or is not derived from a `cv_inner` split). Severity: WARN, escalate to FAIL on `final_model_refit_scope=train_only` runs.
- **W17 candidate (low):** Require `pre_registration_doc_sha` field when `search_method == "manual_pre_registered"` (tuning_leakage_gate.py:147).
- **W18 candidate (very low):** Refactor `train_select_evaluate.py` phase 5/7 to extract a `lock_threshold_then_eval_on_test()` helper that makes the temporal dependency between threshold lock and test evaluation a compile-time data-flow rather than line-ordering.
- **Documentation only:** Add inline `# DO NOT swap y_valid → y_test` warnings in `init_guide.py:813-818`.
