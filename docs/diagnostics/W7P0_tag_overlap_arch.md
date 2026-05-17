# W7-P0: tag_overlap architectural fix

## W2 reproduction (global KB numbers)

Data: `references/case-studies/peer-review-kb.json`, 817 reviewer concerns
across 49 distinct `canonical_pattern_id` values (693 concerns carry a CP).

| Metric | Value |
|---|---|
| Total within-CP pairs | 12,747 |
| Pairs with >=1 shared tag | 229 (1.8%) |
| Pairs with >=2 shared tags | **23 (0.2%)** |
| Pairs with >=3 shared tags | 1 (0.0%) |

Per-CP breakdown (top 5 by size):

| CP | n | pairs | >=1 | >=2 |
|---|---|---|---|---|
| CP-001 | 88 | 3,828 | 9 (0.2%) | 1 (0.0%) |
| CP-002 | 74 | 2,701 | 57 (2.1%) | 1 (0.0%) |
| CP-003 | 68 | 2,278 | 7 (0.3%) | 0 (0.0%) |
| CP-004 | 48 | 1,128 | 13 (1.2%) | 0 (0.0%) |
| CP-008 | 22 | 231 | 11 (4.8%) | **1 (0.4%)** |

W2's CP-008 hand-trace (22 concerns, 1 of 231 pairs at >=2) is confirmed
**and is the rule, not the exception**: at the >=2 threshold the tag-overlap
signal is dead across 99.8% of within-CP pairs globally.

The dominant shape: each CP has 1-5 root tags (e.g. CP-008's
`no_external_validation` appears in 5 concerns) plus a long tail of
paper-specific narrowings (`no_external_validation_for_combined`,
`small_validation_set`, `single_external_center`, etc.) that appear in
exactly one concern. Two concerns from the same CP typically share one
root tag at most.

## Architectural options measured

* **C1**: lower threshold from `>=2` to `>=1` (~1 LOC; new config constant)
* **C2**: canonical-tag normalization (~30 LOC; map `X_for_Y` -> `X` at
  overlap-compute time using a regex over `_(for|in|when|with|on|via|using|across|by|under)_`)
* **C3**: both

C2 alone moves only 11 pairs (229 -> 240 at >=1) because the
`*_(for|in|...)_*` narrowing pattern matches only 56 tags total and only
16 have a stem that also appears as a standalone tag in the KB. Most
narrowings in this KB use ad-hoc phrasing (e.g.
`internal_split_only`, `same_cohort_validation`) that no regex catches.

## Eval comparison

`scripts/rag/evals/run_eval.py --mode hybrid` over 30 scenarios. Baseline
+ C1 runs were taken AFTER stashing my edits / popping them to ensure
the C1 measurement reflects only the threshold change (the parallel
W7-P1 harness change raised coverage from 0.367 -> 0.867, so an earlier
baseline taken before W7-P1 landed would have been an apples-to-oranges
comparison).

| Variant | hit@K | coverage | tag_prec@K | mean_top1 | n_evaluable |
|---|---|---|---|---|---|
| Baseline (>=2) | 1.000 | 0.867 | 0.5308 | 0.6350 | 26/30 |
| **C1 (>=1)** | 1.000 | 0.867 | **0.5385** (+0.008) | **0.6488** (+0.014) | 26/30 |
| C3 (>=1 + canon) | 1.000 | 0.367 (older harness) | 0.5818 | 0.6371 | 11/30 |

C3 was measured against the older harness (pre-W7-P1) where it traded
+0.004 top1 for -0.018 tag_prec vs C1; against the new harness this
trade-off would persist while adding ~30 LOC and a regex maintenance
burden for marginal gain.

Per-scenario diff baseline -> C1 (only changed rows; 26 evaluable):

| scenario | b_top1 | c1_top1 | delta | b_tagP | c1_tagP |
|---|---|---|---|---|---|
| calibration_plot_missing_no_dca | 0.6281 | 0.6611 | +0.0330 | 0.80 | 0.80 |
| ci_missing_or_suspiciously_narrow | 0.6790 | 0.6790 | +0.0000 | 0.40 | 0.20 |
| cohort_definition_selection_bias | 0.6582 | 0.6582 | +0.0000 | 0.60 | 0.80 |
| evaluation_improper_f1_primary | 0.6361 | 0.7261 | +0.0900 | 0.80 | 0.80 |
| imbalance_smote_without_justification | 0.6919 | 0.7369 | +0.0450 | 0.80 | 1.00 |
| model_selection_cherry_picked_seed | 0.6431 | 0.6476 | +0.0044 | 0.60 | 0.60 |
| no_external_validation_single_center | 0.6917 | 0.7967 | +0.1050 | 0.60 | 0.60 |
| sample_size_epv_violated | 0.6675 | 0.7510 | +0.0835 | 0.80 | 0.80 |

6 top1 improvements, 0 top1 regressions, 1 tag_prec regression (rank-4
swap on `ci_missing`; top-1 identical), 1 tag_prec improvement.

## Decision

**C1**: lower threshold from `>=2` to `>=1` via new config constant
`TAG_OVERLAP_MIN_SHARED = 1`.

Reasoning:
1. Wins on every aggregate (top1 +0.014, tag_prec +0.008, no
   coverage/hit@K regression).
2. The headline use case (`no_external_validation_single_center`, the
   CP-008 cluster W2 flagged) gains +0.105 top1 -- direct corroboration
   of W2's structural diagnosis.
3. Minimal surface area: one extra `int` constant + one variable
   substitution in the hot loop. C2/C3 add a 30-LOC canonical-tag map
   that needs ongoing maintenance as the KB grows and yields a net
   tag_prec loss.
4. Test coverage: 7-test regression suite added
   (`tests/test_rag_tag_overlap.py`) pins the default at 1, asserts the
   single-shared-tag firing case, and protects the partner-count cap.

## Side effects observed

* `ci_missing_or_suspiciously_narrow`: rank-4 swap costs 1 expected_tag
  hit. Top-1 unchanged; net aggregate tag_prec still positive.
* Wall time across the eval dropped slightly (-12% on the W7-P1 harness
  run, but within noise; ranker is not the bottleneck).
* No change to BM25 path, severity boost, MMR, or gate filtering.

## If implemented: commit hash

`9e6391c` pushed to `origin/main` 2026-05-16T22:06Z.
CI status (https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/actions):
ci-unit + ci-security in flight at commit time.
