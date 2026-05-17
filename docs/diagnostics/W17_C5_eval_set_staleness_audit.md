# W17-C5 — rag-eval-set stale label scan

**Date**: 2026-05-17  **Wave**: 17 strict-review  **Mode**: READ-ONLY
**Inputs**: `references/case-studies/rag-eval-set.yaml` (v1, 15 cases, 48 relevant_concern_ids), `references/case-studies/peer-review-kb.json` (817 unique concern_ids across 335 entries).
**Method**: for every case, run `scripts.rag.query.rag_query(query, gate, failure_codes, top_k=20)` in-process where `query` is the gate name + issue codes (snake-case → words), then look up each `relevant_concern_id`'s rank. Concern_ids absent from the KB are flagged `dangling`.
**Raw outputs**: `/tmp/W17_C5_per_id.csv`, `/tmp/W17_C5_per_case.csv`, `/tmp/W17_C5_summary.json`.

## Summary

| Dimension | Count |
|---|---|
| Cases scanned | 15 |
| `relevant_concern_id` total | 48 |
| In KB | 47 |
| Dangling (concern_id no longer in KB) | **1** (`PR-040-C01`) |
| Rank ≤ 5 | 21 (43.8 %) |
| Rank 6 – 20 | 20 (41.7 %) |
| Not in top-20 | 6 (12.5 %) |
| **Stale (rank > 5 OR dangling)** | **27 / 48 = 56.2 %** |
| **Severely stale (not in top-20 OR dangling)** | **7 / 48 = 14.6 %** |

## Verdict: **RED** (>30 % stale)

The W14-F1 signal generalises. Frozen `relevant_concern_ids` set against a 375-record KB lose rank in a 817-record KB: only 44 % of hand-curated relevant ids still surface in top-5. Two cases (`evaluation_quality_baseline`, `permutation_significance_missing`) score recall@5 = 0 — the eval set's `Recall@5 ≥ 0.55` contract is already violated for them. The eval set's intended baseline (lock retrieval quality so A/B-comparisons are meaningful) is no longer trustworthy without re-labelling.

## Top 5 cases needing re-label

| Rank | case_id | gate | n_rel | recall@5 | drop | notes |
|---|---|---|---:|---:|---:|---|
| 1 | `evaluation_quality_baseline` | evaluation_quality_gate | 3 | **0.00** | 1.00 | All 3 ids drift to ranks #15, #17, #19 — KB now has stronger semantic matches |
| 2 | `permutation_significance_missing` | permutation_significance_gate | 3 | **0.00** | 1.00 | All 3 ids drift to ranks #6, #12, #17 (post-W13 gate added; never re-labelled) |
| 3 | `missingness_imputation` | missingness_policy_gate | 4 | 0.25 | 0.75 | `PR-011-C04` lost top-20; only `PR-003-C02=#3` survives |
| 4 | `clinical_metrics_ppv` | clinical_metrics_gate | 4 | 0.25 | 0.75 | `PR-028-C06` lost top-20; `PR-076-C03=#13`, `PR-086-C02=#11` demoted |
| 5 | `shap_shallow` | shap_interpretability_gate | 4 | 0.25 | 0.75 | `PR-005-C06=#17`, `PR-007-C06=#13` demoted; new SHAP concerns out-rank them |

## Severely-stale concern_ids (full list)

| case_id | concern_id | status |
|---|---|---|
| `clinical_metrics_ppv` | `PR-028-C06` | not_in_top20 |
| `calibration_missing` | `PR-002-C07` | not_in_top20 (W14-F1 signal) |
| `missingness_imputation` | `PR-011-C04` | not_in_top20 |
| `external_validation_missing` | `PR-006-C04` | not_in_top20 |
| `external_validation_missing` | `PR-040-C01` | **dangling** (no longer in KB) |
| `cohort_definition_contamination` | `PR-063-C01` | not_in_top20 |
| `synonym_fit_before_split` | `PR-010-C02` | not_in_top20 |

## W14-F1 cross-check

W14-F1's calibration finding reproduces: `calibration_missing.PR-002-C07` is still not in top-20. The same family of failure is now present in **6 additional cases** — W14-F1 under-reported the problem because it only inspected one case study.

## Cases still healthy (recall@5 ≥ 1.0)

`leakage_target_in_features`, `split_patient_overlap`, `imbalance_smote`, `robustness_outliers` — all are small-N (1-2 relevant ids) with semantically unique queries; little headroom for the KB growth to displace them.

## Wave-N+ recommendation: **per-case re-label, NOT wholesale regenerate**

1. **Re-label, don't regenerate.** The eval set's selection rules (yaml header, lines 13-15) are sound; the labels just lag the KB. Per-case re-label is O(15 cases × 5 min inspection) ≈ 75 min of curator time. Wholesale auto-regeneration would lose the hand-validated "semantically matching" judgement that anchors the baseline.
2. **Re-label the 5 top-stale cases first** (table above). These hit the published `Recall@5 ≥ 0.55` contract; fixing them restores the metric's signalling value.
3. **Resolve the 1 dangling id** (`PR-040-C01`): either it was deleted in a KB compaction or renamed. Run `git log -S PR-040-C01 -- references/case-studies/peer-review-kb.json` to find the commit; if intentionally removed, drop from eval; if renamed, remap.
4. **Schedule re-label as a CI tripwire.** After every `add_robustness_permutation_gates.py` / `backfill_peer_review_gates.py` / KB-grow run, re-run this scan and fail CI if stale_pct > 30 % (the current line). The yaml's "Maintenance" note (line 17-18) is honour-system today; promote it to a gate.
5. **Do not raise the Recall@5 / MRR@5 thresholds** until re-label lands. The current 0.55 / 0.45 baseline is computed against stale ground truth and is mechanically too easy.

## Reproduce

```bash
python3 /tmp/W17_C5_audit.py    # writes /tmp/W17_C5_{per_id,per_case,summary}.{csv,json}
```
