# Bench-10: Stratified Train/Dev/Test Split Specification

**Date:** 2026-05-17
**Author:** bench_10 (split + reproducibility runner)
**Seed:** `20260517`
**Ratios:** **70 / 15 / 15** (train / dev / test)
**Stratification axis:** **per slice tag**, not global
**Inputs in this round (185 scenarios):**
- `references/retrieval_eval/scenarios.json` — 30 (baseline)
- `/tmp/mlgg_eval_expand/merged.json` — 155 (agent01..agent10)

---

## 1. Why per-slice (not global) stratification

If we stratify globally on `dimension`, every time a new in-distribution agent
(`bench_01..07`) or out-of-distribution agent (`ood_01..04`) lands, the global
ratios shift and **every previously assigned scenario can flip splits**. That
is unsafe for a benchmark whose role is to track numbers across rounds.

Per-slice stratification fixes the ratio **within a slice tag** and never
touches scenarios from other slices. New slices simply get their own
independent 70/15/15 with the same seed and are concatenated. This means:

- Numbers reported on the current `test` split are valid forever for that slice.
- Adding bench_01..07 in-distribution agents extends `train`/`dev`/`test`
  but does not re-balance existing assignments.
- ood_01..04 lives in its own `ood_*` tag — its test split can be reported
  separately as an OOD generalization headline number.

## 2. Slice-tag derivation rule

For each scenario, derive `slice_tag` from `scenario_id` prefix:

| scenario_id pattern             | slice_tag             |
|---------------------------------|-----------------------|
| no `agent` prefix (baseline 30) | `baseline`            |
| `agent01_*` / `agent01-*`       | `indist_evaluation`         (agent01) |
| `agent02_*` / `agent02-*`       | `indist_evaluation_v2`      (agent02) |
| `agent03_*` / `agent03-*`       | `indist_leakage`            (agent03) |
| `agent04_*` / `agent04-*`       | `indist_study_design`       (agent04) |
| `agent05_*` / `agent05-*`       | `indist_leakage_v2`         (agent05) |
| `agent06_*` / `agent06-*`       | `indist_external_validation`(agent06) |
| `agent07_*` / `agent07-*`       | `indist_reporting`          (agent07) |
| `agent08_*` / `agent08-*`       | `indist_model_selection`    (agent08) |
| `agent09_*` / `agent09-*`       | `indist_mixed`              (agent09 — interpretability+fairness+sample_size) |
| `agent10_*` / `agent10-*`       | `adversarial`               (near-misses + distractors) |

Slice tag for agent01..09 reflects the **dominant dimension** that agent
produced. Where agent09 mixes 3 dimensions, the slice tag groups them
together (we do not subdivide by dimension within an agent's slice — the
agent boundary is the unit of "drift risk").

## 3. Split procedure (per slice)

```
for slice_tag in groupby(scenarios, key=slice_tag):
    items = sorted(scenarios_in_slice, key=lambda s: s.scenario_id)  # determinism
    rng = random.Random(20260517)
    rng.shuffle(items)
    n      = len(items)
    n_test = round(n * 0.15)
    n_dev  = round(n * 0.15)
    n_train = n - n_test - n_dev
    train = items[:n_train]
    dev   = items[n_train : n_train + n_dev]
    test  = items[n_train + n_dev :]
```

The RNG is **re-seeded per slice** with the same `20260517` so adding a new
slice later is byte-identical regardless of what other slices were merged in
the past. Sorting by `scenario_id` before shuffle removes input-order
sensitivity (the source JSONs were written by different agents in different
orders).

## 4. Role of each split

| Split | Size  | Purpose | Touch policy |
|-------|-------|---------|--------------|
| train | ~70%  | RAG hyperparameter tuning (e.g., re-tuning hybrid α/β weights, BM25 `k1`/`b`, top-K, future re-rankers). | Free to re-run as often as desired. |
| dev   | ~15%  | Harness + metric development (Recall@K curves, calibration scorers, eval-script regressions, new failure-code coverage metrics). | Touched only when changing measurement code, not when tuning the RAG. |
| test  | ~15%  | **Held out, report-only.** Final numbers in the paper / release notes come from this. | At most 1 evaluation per release. Do NOT iterate on test. |

Rationale for putting metric/harness work on **dev** rather than **test**:
metric churn (a denominator change, a new "expected_tags" field) tends to
flip the number more than RAG tuning does, so keeping it off test preserves
the integrity of the held-out signal.

## 5. Absorption rule for in-flight bench/ood outputs

`bench_01..07` (in-distribution) and `ood_01..04` (out-of-distribution) agents
are still running at split-time. When their JSONs land:

1. Tag every new scenario with a slice tag.
   - `bench_NN_*` → `indist_bench_NN` (one slice per bench agent), OR if a
     bench agent is a thin extension of an existing slice, reuse that slice tag.
   - `ood_NN_*` → `ood_NN` (one slice per OOD agent, isolated for OOD
     reporting).
2. For each **new** slice tag, run the procedure in §3 with the same seed
   (`20260517`) on **only that slice's scenarios**.
3. `cat` the new per-slice train/dev/test onto the existing
   `split_train.json` / `split_dev.json` / `split_test.json`.
4. No existing scenario's assignment changes. Sanity check: `diff` the
   pre-existing scenario_ids in each split before and after — must be empty.

This is why we use **per-slice** rather than global stratification: it makes
absorption monotonic.

## 6. Outputs (this round)

- `/tmp/mlgg_benchmark/split_train.json`
- `/tmp/mlgg_benchmark/split_dev.json`
- `/tmp/mlgg_benchmark/split_test.json`
- `/tmp/mlgg_benchmark/run_benchmark.sh` (reproducibility runner)

Each JSON carries:
```
{
  "scenarios":          [ ... ],
  "split":              "train" | "dev" | "test",
  "split_seed":         20260517,
  "slice_distribution": { slice_tag: count, ... },
  "ratio_target":       [0.70, 0.15, 0.15],
  "stratification":     "per-slice",
  "absorption_rule":    "new slices get their own 70/15/15 with same seed; merged by concat",
  "input_sources": [
    "references/retrieval_eval/scenarios.json",
    "/tmp/mlgg_eval_expand/merged.json"
  ]
}
```

## 7. Determinism guarantees

- Slice tag derivation is a pure function of `scenario_id`.
- Per-slice RNG is re-seeded with `20260517`.
- Items are sorted by `scenario_id` before shuffle.
- ⇒ Re-running on the same two input files yields byte-identical splits.
- ⇒ Re-running on the same two inputs **plus** any later bench/ood files
  yields byte-identical splits for the original 185 scenarios.

## 8. Out-of-scope / known limitations

- We do not stratify within a slice by `dimension` or `failure_codes`. Slice
  sizes (15–30) are too small for double-stratification to be statistically
  meaningful; sorted-then-shuffled with a fixed seed is the simpler and more
  defensible choice.
- Round-half-to-even in `round()` means 15% of 15 → 2 (not 3). This is
  acceptable — exact 70/15/15 isn't recoverable on small slices anyway.
- Scenarios with duplicate `scenario_id` would silently land in the same
  split. The splitter asserts uniqueness and fails loudly if violated.
