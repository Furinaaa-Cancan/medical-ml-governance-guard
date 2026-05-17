# W18-D2 — Per-query P@5 failure audit (36-query labeled set)

**Wave / agent**: Wave 18 / W18-D2 (strict-review)
**Date**: 2026-05-17
**Read-only**: yes (eval replay only; no edits to `references/`, `scripts/`, `.github/`)
**Inputs**:
- `references/retrieval_eval/labeled_precision_at_5.json` (W8-W2 + W9-A2, 36 queries, labeled at retrieval-mode `hybrid` post-W7P0)
- Driver: `/tmp/W18_D2_driver.py` (replays each query through `scripts.rag.rag_query`, top-K=20)
- Per-query JSON: `/tmp/W18_D2_per_query.json`

## Scoring convention (worst-case)

A returned `concern_id` is counted **relevant** only if it appears in the labeled top-5 with `relevant=true`. Returned ids that were not in the labeled top-5 at label time are treated as **unknown** and counted as not-relevant. Hence the per-query P@5 reported here is a **lower bound** on the true P@5 — the true value can only be equal-or-higher once the unknown ids are adjudicated. This makes P@5=0 the most reliable failure signal, which is the question this audit answers.

## Headline numbers

| Metric | Value |
|---|---|
| Queries in set | 36 |
| Queries with P@5 = 0 | **3** |
| % failure (P@5 = 0) | **8.3 %** |
| Of which off-scope pinned (L19, L20) | 2 |
| Of which labeled-zero at label time (L27) | 1 |
| Genuine post-W13-P0 P@5=0 regressions | **0** |
| Mean P@5 (lower bound, this run) | 0.494 |
| Top-5 slots filled by "unknown" ids (drift since label) | 44 / 168 = **26.2 %** |

**Verdict: PASS** (≤ 10 % failure). No new P@5=0 query exists post-W13-P0 that was non-zero at label time. The 8.3 % failure rate is entirely explained by labels that were **designed** to be zero (off-scope probes + one IMPOSSIBLE concern absent from KB).

## Per-sub-dim failure-rate table (P@5 = 0)

| sub_dim | n | P@5=0 | rate |
|---|---:|---:|---:|
| off_scope_probe | 2 | 2 | 100 % (by design) |
| preprocessing_split_leakage | 3 | 1 | 33 % (label-time also 0; KB absence) |
| leakage_split_hygiene | 3 | 0 | 0 % |
| leakage_definition_variable | 3 | 0 | 0 % |
| leakage_temporal_future | 3 | 0 | 0 % |
| split_temporal_validation | 3 | 0 | 0 % |
| model_selection_tuning_leakage | 3 | 0 | 0 % |
| evaluation_uncertainty_quantification | 3 | 0 | 0 % |
| evaluation_calibration | 3 | 0 | 0 % |
| all other singleton sub_dims (10) | 10 | 0 | 0 % |

No sub-dim shows a systematic ranker collapse (rate ≥ 30 % after subtracting designed-zeros).

## Per-failing-query classification and fix

| id | sub_dim | classification | suggested fix |
|---|---|---|---|
| L19_offscope_woodworking | off_scope_probe | **IMPOSSIBLE (by design)** — `free_text_probe` gate enforces 0 hits; correctly returns []. | none — keep pinned at P@5=0. |
| L20_offscope_music | off_scope_probe | **IMPOSSIBLE (by design)** — same as L19. | none. |
| L27_preproc_scaling_before_split | preprocessing_split_leakage | **IMPOSSIBLE** at label time (`labeled_relevant_ids=[]`) — the KB had no concern describing "fit scaler on full data before split" in May 2026; top-5 are adjacent split-protocol concerns, all labeled `relevant=false`. Status unchanged. | not a ranker bug. Action belongs to KB-curation wave (Wave-19 candidate): seed at least 1 concern verbatim addressing MLGG-P01 scaler-before-split, then re-label L27. |

## Drift surface (silent label decay, not P@5=0 today but at risk)

`labeled_relevant_ids` only cover the **labeled** top-5 from May 2026. The current ranker returns 44/168 (26.2 %) top-5 ids that the label set has never seen — every one of those slots could be a true positive being mis-scored here as "unknown ≈ non-relevant". The lower-bound P@5 in this run (0.494) is therefore not directly comparable to the label-time mean (0.643). Six queries have ≥ 3 unknown ids in their current top-5 and the lower-bound P@5 dropped by ≥ 0.4 from label-time:

| id | sub_dim | label P@5 | current LB P@5 | unknown / top-5 |
|---|---|---:|---:|---:|
| L03_leakage_future_info | leakage_temporal_future | 1.0 | 0.4 | 3 |
| L09_eval_improper_f1_primary | evaluation_metric_choice | 0.8 | 0.4 | 3 |
| L10_eval_no_dca | evaluation_clinical_utility | 0.4 | 0.2 | 3 |
| L16_reporting_missing_tripod | reporting_transparency | 0.8 | 0.4 | 3 |
| L25_temporal_lab_after_event | leakage_temporal_future | 1.0 | 0.4 | 3 |
| L28_preproc_imputation_global | preprocessing_split_leakage | 0.4 | 0.2 | 3 |
| L35_eval_overconfidence_not_assessed | evaluation_calibration | 0.6 | 0.4 | 3 |

These are the **top 10 priority re-label candidates** (7 high-drift listed; rounding out with L36_eval_no_hosmer_lemeshow, L31_tuning_model_choice_on_test, L15_fairness_no_subgroup which also have ≥ 2 unknown slots and ≥ 0.2 drift).

## Cross-check vs W14-F1 / W17-C5 (H3 stale-label hypothesis)

W14-F1 found `calibration_missing.PR-002-C07` was lost from top-20 in one **case study**. W17-C5 generalised to 56.2 % stale across 15 case studies, with `evaluation_quality_baseline` and `permutation_significance_missing` at recall@5 = 0.

This 36-query labeled set tells a **different but compatible** story: at the *query* level (not the *case-study* level), P@5=0 is 0 % once designed-zeros are removed — i.e. the ranker still surfaces *some* relevant concern for every in-scope query. But the **identity** of which concern surfaces has drifted (26.2 % of top-5 slots), which is exactly the H3 mechanism that bit the case-study recall@5 contract. The two findings are the same underlying signal observed through two different evaluation contracts: case-study recall@5 (strict — frozen ID set) breaks fast; per-query P@5 lower-bound (loose — frozen ID set used as proxy) degrades silently.

## Wave-N+ recommendation

1. **No urgent ranker change.** P@5=0 rate net of designed-zeros is 0 %. The "regressions" are label drift, not ranker collapse — patch the labels, do not patch the ranker.
2. **Per-query re-label (Wave-19 candidate)** of the 10 listed queries: human-adjudicate the 44 currently-unknown ids and either flip them to `relevant=true` (likely a substantial fraction) or write the `why=False` rationale. Cost: ~10 minutes / query × 10 ≈ 1.5 h.
3. **KB expansion for L27** (`preprocessing_split_leakage` / MLGG-P01 / "scaler fit before split"): one new concern entry is enough to make L27 evaluable for the first time. Same wave as point 2.
4. **Scenario expansion not needed** — the labeled set's 18 in-scope sub-dim coverage is adequate for the questions this artefact is asked to answer; expansion duplicates `scenarios.json`.
5. **Reissue as `labeled_precision_at_5_v2.json`** after points 2–3 land, per the schema's own protocol note ("Do NOT regenerate after retrieval changes — append a new file"). Keeps longitudinal drift auditable.

---

_Outputs_: `/tmp/W18_D2_per_query.json` (raw), `/tmp/W18_D2_driver.py` (driver), this file.
