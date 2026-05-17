# W15-A3 — Numeric Safety Audit: `math.isfinite` Guard Coverage

**Wave**: W15-A3 (strict review, READ-ONLY)
**Date**: 2026-05-17
**Scope**: `scripts/` numeric conversion safety (`to_float()` / `float()` / `np.float` / `pd.to_numeric` / `astype(float)`)
**Rule audited**: CLAUDE.md — *`to_float()` must include `math.isfinite` guard.*

## Methodology

```bash
grep -rn '\bfloat(' scripts/        # raw conversion sites
grep -rn 'np.float|pd.to_numeric|astype(float)' scripts/
grep -rn 'isfinite|isnan'           # finite-check coverage
grep -rn 'def to_float|def _to_float|def safe_float'
```

Lines were classified into three buckets:

| Bucket | Definition |
|---|---|
| **GUARDED** | Wrapped in `to_float()`, `_to_float()`, `safe_float()`, `finite_float()`, `is_finite_number()`, or with nearby `math.isfinite` / `math.isnan` check |
| **PARSE-CONTEXT** | `argparse type=float`, `dtype=float`, `float(<literal>)`, or `float(baselines[...])` / `float(args.<x>)` where source is trusted policy JSON / CLI args validated upstream |
| **UNGUARDED** | Raw `float(x)` on dynamic value (metric, dict-extracted, computed numpy/pandas scalar) without finite check in the immediate vicinity |

## Counts

| Metric | Count |
|---|---|
| Total `float(...)` grep lines across `scripts/` | **1,147** |
| Total `float(` token occurrences (multi-per-line) | **1,263** |
| Test-context lines | 27 |
| Production lines (gates+reporting+training+orch+diag) | 1,003 |
| Helper-function definitions (`to_float`, `_to_float`, `safe_float`, `_safe_float`) | 7 (in 7 files) |
| Helper **call sites** | 4 (severe under-utilisation) |
| Lines in gates with `isfinite`/`isnan` finite checks | 63 (covering 23/26 gate files) |
| `argparse type=float` callsites | 5 |
| `dtype=float` / array dtype | ~5 |
| Trusted-config casts (`float(baselines[...])`, `float(thresholds[...])`, `float(args.<flag>)`) | ~119 |

### Bucket totals (production scripts only)

| Bucket | Lines | % |
|---|---|---|
| GUARDED (helper or local `isfinite` within 3 lines) | ~95 | 9% |
| PARSE-CONTEXT (literal / argparse / dtype / trusted baselines) | ~140 | 14% |
| **UNGUARDED (dynamic-value, no isfinite within block)** | **~768** | **77%** |

### Top concentration of unguarded calls in gates

```
99 scripts/gates/request_contract_gate.py      (mostly trusted baseline reads — low risk)
55 scripts/gates/calibration_dca_gate.py       (HIGH — metric→threshold compares)
51 scripts/gates/distribution_generalization_gate.py
41 scripts/gates/ci_matrix_gate.py
26 scripts/gates/robustness_gate.py
26 scripts/gates/covariate_shift_gate.py
25 scripts/gates/external_validation_gate.py
23 scripts/gates/clinical_metrics_gate.py
18 scripts/gates/prediction_replay_gate.py
16 scripts/gates/shap_interpretability_gate.py
16 scripts/gates/evaluation_quality_gate.py
```

## Verdict

**RED** — ≥1 unguarded `float(...)` call sits directly on a **gate-verdict path** (`calibration_dca_gate.py` lines 582 / 589 / 601 / 672–673). If `calibration["ece"]` / `calibration["slope"]` / `dca["advantage_coverage"]` arrive as `NaN` or `inf`, the comparisons `NaN > x` evaluate to `False` in Python — the gate **silently passes on garbage metrics**, exactly the failure mode CLAUDE.md mandates `to_float()` to prevent.

Additionally, the project defines `to_float`/`_to_float`/`safe_float` in 7 files but only invokes a helper at 4 call sites total — helpers exist mostly for symmetry, not adoption.

## Top 10 most concerning UNGUARDED sites (gate-verdict path priority)

| # | File:Line | Risk |
|---|---|---|
| 1 | `scripts/gates/calibration_dca_gate.py:582` — `if float(calibration["ece"]) > float(thresholds["ece_max"])` | **CRITICAL.** ECE=NaN → `NaN > 0.05` False → ECE gate passes silently. |
| 2 | `scripts/gates/calibration_dca_gate.py:589` — `if float(calibration["slope"]) < ... or float(calibration["slope"]) > ...` | **CRITICAL.** Slope=NaN bypasses both bounds → calibration slope gate passes. |
| 3 | `scripts/gates/calibration_dca_gate.py:601` — `if abs(float(calibration["intercept"])) > float(thresholds["intercept_abs_max"])` | **CRITICAL.** `abs(NaN)` = NaN; NaN>x False → intercept gate passes. |
| 4 | `scripts/gates/calibration_dca_gate.py:672–673` — `float(dca["advantage_coverage"]) < ... or float(dca["average_advantage"]) < ...` | **CRITICAL.** Net-benefit insufficiency gate silently passes if DCA is NaN. |
| 5 | `scripts/gates/external_validation_gate.py:177` — `if abs(float(observed) - float(expected_f)) > float(tolerance)` (`compare_metric`) | HIGH. `expected` is `to_float`-checked, but `observed` and `tolerance` are raw → NaN in either silently passes mismatch check. |
| 6 | `scripts/gates/distribution_generalization_gate.py:606` — `if float(jsd) >= float(thresholds["top_feature_jsd_warn"])` | MEDIUM. `jsd` is guarded one line above (`isfinite(jsd)`), but the re-cast pattern invites future regressions; redundant raw cast on already-validated value. |
| 7 | `scripts/gates/external_validation_gate.py:545` — `if float(np.max(threshold_values)) - float(np.min(threshold_values)) > 1e-9` | MEDIUM. If `threshold_values` contains NaN, numpy max/min are NaN → diff NaN → False → "threshold stable" passes incorrectly. |
| 8 | `scripts/training/_diagnostics.py:65–66, 121–122` — multiple `float(np.mean(...))` for NRI/IDI deltas with no isfinite guard before downstream JSON write | MEDIUM. Stale NaN propagates to evidence/ reports consumed by downstream gates. |
| 9 | `scripts/gates/cohort_definition_gate.py:361, 397` — `null_rate = float(df[col].isna().mean())`, `at_ceiling = float((df[col] == top_val).mean())` | LOW-MED. Empty df → `.mean()` returns NaN → silent skip of null-rate / ceiling check downstream. |
| 10 | `scripts/reporting/audit_metrics.py:271–281` — `if float(ppv) < 0.50:` / `if float(sensitivity) < 0.80:` (clinical-floor screening) | MEDIUM. `is_number()` is called for some paths, but these two thresholds re-cast without re-guarding; PPV/sensitivity NaN → False → PASS message emitted falsely. |

## Recommendation — Wave-N+

**Two-track remediation, scoped tightest first:**

1. **Wave-N+1 (per-site, critical):** Fix the 5 calibration_dca_gate sites (#1–4) and the external_validation_gate `compare_metric` (#5) — these are direct violations of fail-closed semantics for fail-closed gates that decide publication eligibility. Pattern: `v = to_float(d["x"]); if v is None or v > thr: failures.append(...)` so missing/NaN routes to FAIL, not silent PASS.

2. **Wave-N+2 (codemod, hygiene):** Author a single AST codemod under `scripts/diagnostics/` that rewrites every `float(<dynamic-expr>)` outside argparse/dtype/literal contexts into `to_float(<dynamic-expr>)` and imports the helper from `_gate_utils`. Gate the codemod behind a "verdict-path-only" file allowlist to avoid noise in JSON-serialization wrappers (where NaN→null on output is actually the desired sentinel). Per-site fixes are too many (~770) to do by hand.

**Do NOT codemod blindly:** JSON-serialization `float(np.float64_scalar)` wraps where None is acceptable (`{"auc": float(score)}`) should *keep* NaN visible in the report for downstream gates to catch — converting these to `to_float()` would silently drop the field and *hide* the problem upstream of the verdict path.

## Audit artefacts

- `/tmp/W15_A3_float_calls.txt` — all 1,147 raw `float(` lines under `scripts/`
- `/tmp/W15_A3_numpy_pandas.txt` — 80 numpy/pandas conversion lines
- `/tmp/W15_A3_finite_checks.txt` — 120 `isfinite`/`isnan`/`isna` check lines
- `/tmp/W15_A3_gate_unguarded.txt` — 454 unguarded float lines under `scripts/gates/`
- `/tmp/W15_A3_summary.txt` — count breakdown

---

**Verdict: RED** — calibration_dca_gate has unguarded `float()` on the verdict path; codebase-wide ~768 unguarded dynamic-value casts vs the RED-threshold of >20 (or any verdict-path violation). Helper-adoption discipline is also broken (helpers defined, not called).
