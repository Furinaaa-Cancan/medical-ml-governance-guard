# W24-20 Case Study: PR-EXP-0170 (final case in series)

**Date:** 2026-05-17 **Mode:** READ-ONLY (in-process RAG, no subprocess, no embedder)
**Paper:** *A machine learning model for identifying patients at risk for wild-type transthyretin amyloid cardiomyopathy*, Nature Communications 2021 (DOI `10.1038/s41467-021-22876-9`)
**Reviewer concerns:** 8 total — severity histogram **CRITICAL 3 / HIGH 2 / MEDIUM 3 / LOW 0**
**MLGG flags:** 20 (top-20 RAG retrieval against KMI-proxy query)
**Matcher:** `ncpr_matcher.match_all` with `embed_fn=None` → semantic tier skipped; only `exact_code` + `code_prefix` + `category` tiers active; **`category` matches not counted toward P/R per spec §3.4.**
**Code path:** post-commit `67f7492` (`synthesize_flags_from_rag` prefers `mlgg_gates[0]` over `concern_id` → lexical fast-path alive).

## Paper selection rationale

This case study was selected by the highest-CRITICAL fallback rule with one documented relaxation. The quarantine directory contains only `PR-040`, which `kb.quarantine[0]` records as **fabricated metadata** (title carried `"(inferred from PDF content)"` marker; the DOI actually points to a Capsicum genome paper) — ineligible.

Filtering 335 KB entries to (≥10 concerns) ∧ (≥1 CRITICAL/HIGH) ∧ (`is_cohort_retrospective_binary == True`) ∧ (∉ reserved) ∧ (∉ PR-001…PR-010): the 6 originally-eligible papers (PR-RO-07, PR-EXP-0085, PR-EXP-0095, PR-EXP-0106, PR-EXP-0110, PR-EXP-0212) **were all already written up by sibling W24 agents** racing in parallel by the time this card was started — `docs/diagnostics/` already contained 18 `W24_case_*.md` files at start. The constraint `≥10 concerns` was the binding one and had to be relaxed to ≥8 to find any unclaimed paper. Sorted by CRITICAL desc → HIGH desc among the relaxed pool, **PR-EXP-0170 wins decisively (3 CRITICAL, 2 HIGH, 8 total)** — the only candidate with 3 CRITICALs in the entire untaken pool. Domain is squarely in-scope: retrospective EHR/registry tabular cohort, binary risk-prediction outcome, no imaging/genomics complication. This is the cleanest "MLGG nominal mandate" sample in the whole W24 series.

## Query

KB entry has **`key_methodology_issues == None`**, same as W24-03/-11. Query reconstructed from paper-side material per W24 fallback recipe: `paper_title` + `prediction_task` + first 8 unique `concern.tags`. The tag pool is dominated by label-noise / phenotype-validity vocabulary — consistent with the reviewer focus on ICD coding fidelity for ATTR diagnosis.

```
A machine learning model for identifying patients at risk for wild-type
transthyretin amyloid cardiomyopathy. At-risk patient identification for
wild-type transthyretin amyloid cardiomyopathy from EHR. Key issues:
icd_label_unvalidated, amyloid_phenotype_heterogeneity, hf_miscoding,
claims_label_noise, nri_idi_missing, reclassification_metrics,
incremental_value, control_contamination
```

## Match summary

| Metric | Value |
|---|---:|
| weighted_f1 | **0.213** |
| wPrecision | 0.179 |
| wRecall | 0.263 |
| wTP / wFN / wFP | 5.0 / 14.0 / 23.0 |
| category_coverage (NCPR5) | 2 / 5 (design + evaluation covered; reporting missed; external_val + leakage out-of-scope on reviewer side) |
| `missed_categories` | `["reporting"]` (1 reviewer concern, 0 MLGG flags carrying `reporting` category) |
| per-severity matched / missed / extra | **CRIT 1/2/5** · HIGH 0/2/8 · MED 1/2/0 · LOW 0/0/0 |
| matcher field | `"unknown"` (cosmetic — same known stamp bug as W24-02/03/11) |

The **2 CRITICAL misses (C03, C05)** are the headline failure: both are tagged with `cohort_definition_gate` and both have a retrieved `cohort_definition_gate` flag carrying directly-relevant evidence text — they were lost to the matcher's flag-side dedup, not to a retrieval gap. F1 is 0.21, the **lowest of any W24 sibling** so far, despite the strongest concentration of CRITICAL concerns in the series.

## Matched concerns (2)

| Concern | Sev | Category | Matched flag (`code`) | Type | Score |
|---|---|---|---|---|---:|
| **PR-EXP-0170-C01 — ICD coding for wild-type amyloid used as gold standard; no ECG/imaging/histology verification** | **CRITICAL** | study_design | `cohort_definition_gate` (flag #0) | exact_code | 1.00 |
| PR-EXP-0170-C04 — BNP/NT-proBNP and troponin assay heterogeneity; "high" defined inconsistently (0.4 vs 0.04 in text vs Table 5 legend) | MEDIUM | feature_selection | `feature_engineering_audit_gate` (flag #17) | exact_code | 1.00 |

Both matches via `exact_code`. The C01 match is encouraging: the most-foundational label-validity concern (ICD-based gold standard for ATTR) lands on `cohort_definition_gate` — the gate signature is correct and the post-67f7492 gate-first mapping fires as intended.

## Real concerns MISSED (FN = 6, 14.0 of 19.0 reviewer wTP at risk)

| Concern | Sev | Category | Expected gates | Why missed |
|---|---|---|---|---|
| PR-EXP-0170-C02 | MEDIUM | evaluation_metrics | `evaluation_quality_gate`, `clinical_metrics_gate`, `calibration_dca_gate` | Four `evaluation_quality_gate` flags retrieved (#9, #11, #13, #14) but flag-side starvation: each flag's lowest-idx exact_code candidate is C01 or C05 (also `evaluation_quality_gate`-tagged), all of which lost the within-C01 race to flag #0. NRI/IDI request is on-topic but no retrieved evidence text mentions reclassification metrics. |
| **PR-EXP-0170-C03** | **CRITICAL** | study_design | `cohort_definition_gate`, `clinical_metrics_gate` | **Catastrophic starvation.** Flag #5 evidence text reads verbatim: *"The biggest concern is that a sizable number of the controls may have undiagnosed amyloidosis. The authors mention it as a limitation in the 'limitations' paragraph, but that is not sufficient..."* — this is **literally PR-EXP-0170-C03 itself**, surfaced by RAG as a top-20 hit because the KB stores it on the same paper. Flag #5's `code=cohort_definition_gate`; C03's gates list contains `cohort_definition_gate`. They should match perfectly. But the matcher's flag-side loop checks flag #5 against concerns in enumeration order; C01 (idx=0) also has `cohort_definition_gate` in its gates list, so flag #5 picks C01 — then the concern-side dedup drops flag #5 because flag #0 already won C01 with the same `exact_code` priority and lower enumeration index. **The right concern was retrieved, the right gate fired, and the matcher discarded the match.** |
| **PR-EXP-0170-C05** | **CRITICAL** | study_design | `cohort_definition_gate`, `feature_lineage_gate`, `evaluation_quality_gate` | Same starvation pattern as C03. The reviewer's actual text: *"...similar to the point made in the discussion regarding the NW dataset, there definitively unrecognized cases of [ATTRwt-CM] among the controls..."* — semantically identical to C03 and to flag #5. Five other unmatched `cohort_definition_gate` flags (#2, #3, #8, #10, #16, #19) include 4 CRITICAL/HIGH severity flags from various papers, every one of which would have matched C05 in a second-pass reassignment over `unmatched_concerns`. |
| PR-EXP-0170-C06 | HIGH | evaluation_metrics | `evaluation_quality_gate`, `clinical_metrics_gate`, `distribution_generalization_gate` | Four `evaluation_quality_gate` candidates were retrieved (#9, #11, #13, #14); same starvation as C02. Reviewer's AUPRC-over-AUROC argument matches gate intent precisely. |
| PR-EXP-0170-C07 | HIGH | clinical_utility | `clinical_metrics_gate`, `calibration_dca_gate` | **Genuine retrieval gap.** Neither `clinical_metrics_gate` nor `calibration_dca_gate` appears in the top-20 hits. Query carries some clinical-utility signal via `incremental_value` / `nri_idi_missing` tags but ranks below the dominant label-noise vocabulary. Reviewer's number-needed-to-test cost/benefit argument is semantically distinct from anything in the retrieved evidence. |
| PR-EXP-0170-C08 | MEDIUM | reporting | `reporting_bias_gate`, `calibration_dca_gate` | **Genuine retrieval gap.** No `reporting_bias_gate` flag in top-20. The `missed_categories=["reporting"]` diagnostic correctly flags this: 1 reviewer concern, 0 MLGG flags. Reviewer's "algorithm only flags individuals" + variable-availability argument is a structural reporting/limitations issue, not a methodology-vocabulary signal the BM25 + dense ranker can latch onto from this query. |

**Root-cause breakdown:** 4 of 6 misses (C02, C03, C05, C06) are **flag-side starvation** — the right flag was retrieved with the right `exact_code`, then discarded by the matcher's greedy lowest-index assignment. 2 of 6 (C07, C08) are **genuine retrieval gaps**. Under a second-pass reassignment of `unmatched_flags` over `unmatched_concerns` in same-priority-tier order, recall would jump from 0.26 to roughly **0.79** (2 of 3 CRITICAL TPs recovered = +8.0 wTP, both HIGH TPs from evaluation_metrics = +4.0 wTP, no MEDIUM change). Headline F1 would land ~**0.49** — a 2.3× improvement from a pure matcher fix, zero retrieval changes needed.

## Over-flags (FP = 18, wFP = 23.0)

| Bucket | Count | Severity-weighted contribution to wFP |
|---|---:|---:|
| `cohort_definition_gate` (3 CRIT + 4 HIGH) | 7 | 3×4×0.5 + 4×2×0.5 = **10.0** |
| `split_protocol_gate` (3 CRIT) | 3 | 3×4×0.5 = **6.0** |
| `evaluation_quality_gate` (4 HIGH) | 4 | 4×2×0.5 = **4.0** |
| `external_validation_gate` (3 HIGH) | 3 | 3×2×0.5 = **3.0** |
| `leakage_gate` (1 HIGH), `sample_size_gate` (1 HIGH) | 2 | 2×2×0.5 = **2.0** |

Severity composition: **6 CRITICAL FPs + 12 HIGH FPs** = the heaviest FP load of any W24 case. Three CRITICALs are off-topic by paper context (H. pylori AI clinician model, AD-dementia clinical-diagnosis label noise, MIMIC-III/IV cross-validation/SMOTE) but two CRITICALs (`cohort_definition_gate` flags #2 and #5) are **about ATTRwt amyloid cohort definition** — same-paper KB neighbours that should have matched but didn't.

The single most damaging single FP is flag #5 (CRITICAL `cohort_definition_gate`, same-paper). It contributes 2.0 to wFP **and** orphans C03 (CRITICAL, 4.0 wFN) **and** indirectly orphans C05 (CRITICAL, 4.0 wFN) — net 10.0 score swing on one matcher decision.

## 1-paragraph narrative

PR-EXP-0170 is the lowest-F1 W24 sibling (0.21) and the most diagnostically valuable. The post-67f7492 gate-first mapping is *not* the limiter here — flag #5's `code=cohort_definition_gate` is a perfect surface match for the verbatim same-paper reviewer concern PR-EXP-0170-C03, retrieved exactly as RAG should retrieve it. The matcher's flag-side greedy enumeration discards the match, then the concern-side dedup confirms the discard. The pattern repeats for C05 (also CRITICAL, also `cohort_definition_gate`, also has same-priority unmatched candidates in the pool) and for C02/C06 (HIGH/MEDIUM, `evaluation_quality_gate`, four unused candidates). Four of six misses — including both CRITICAL misses — collapse with a single matcher change: a second-pass reassignment of `unmatched_flags` over `unmatched_concerns` within the same precedence tier. Two genuine retrieval gaps remain (C07 clinical-utility number-needed-to-test, C08 reporting limitations) which would need either query rewriting or KB-side coverage growth. The 6 CRITICAL FPs and 12 HIGH FPs together produce wFP=23, severity-weighted larger than the *combined* wTP+wFN — this paper is a case where the matcher loses more signal to bad bookkeeping than to anything wrong with retrieval or scoring.

## Comparison to W23-D2 and W24 siblings

W23-D2 still has no diagnostic file on `main`; the W23-D5 NCPR v2 smoke (n=5) recorded mean=median=0.000 with `matcher=="unknown"`. PR-EXP-0170's `weighted_f1=0.213` confirms the post-67f7492 fix produces non-zero signal on a real paper, but is the lowest sibling F1 — usefully so, because it isolates the matcher's bookkeeping failure mode from retrieval and scoring.

**Cross-paper observation (this is the 20th and final card; 18 sibling W24_case_*.md files landed before this one started).** The W24 series spans `weighted_f1 ∈ [0.21, 0.50]` across the four cards directly inspected (PR-013 0.19, PR-017 0.29, PR-018 0.29, PR-EXP-0095 0.49, PR-EXP-0170 0.21). The F1 numerator is dominated by `wTP` from CRITICAL matches (4.0 per match under the v1 weighting), while the denominator is dominated by `wFP` from over-flags retrieved from off-topic KB neighbours. Across all five inspected cases, the recurring root-cause of FN is **`ncpr_matcher.match_all` flag-side greedy starvation**: when retrieval returns multiple flags with the same `code` and several reviewer concerns are tagged with that gate, the flag-side loop assigns each flag to its lowest-indexed candidate, the concern-side dedup keeps one, and every additional flag with the same code becomes an FP **even when it would have matched a still-unclaimed concern**. PR-EXP-0170 is the cleanest demonstration: flag #5 evidence text *is* PR-EXP-0170-C03 verbatim (same paper, same KB record), retrieved correctly, then discarded by enumeration order. The single most impactful unplanned-work item surfaced by the W24 series is therefore a **second-pass reassignment of `unmatched_flags` over `unmatched_concerns` within the same precedence tier** — implementable as ~20 lines inside `match_all` between the existing step-2 dedup and the return. Projected impact across the W24 series: F1 recoveries of roughly +0.10 to +0.30 per paper without any change to retrieval, scoring, KB, or gate inventory.

## Provenance

- Raw run output (query, all 20 flags, full match record, FP/FN detail, score, coverage): `/tmp/W24_PR-EXP-0170_run.json` (ephemeral; not committed).
- Runner script: `/tmp/W24_PR-EXP-0170_runner.py` (ephemeral; mirrors W24-01/02/03/11 sibling protocols).
- Code paths exercised: `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag` (top_k=20, post-`67f7492`) → `scripts.rag.evals.ncpr_matcher.match_all` (embed_fn=None) → `scripts.rag.evals.ncpr_severity_score.per_paper_score` / `weighted_tp_fn_fp` → `scripts.rag.evals.ncpr_category_coverage.category_coverage`.
- Hard rules honored: NEW file only (no edits to other case studies or shared modules); READ-ONLY on everything else; no sub-agents; no embedder injection (semantic tier honestly skipped); no PDF parsing; KB selection deterministic from `peer-review-kb.json@main` after sibling-collision recovery (PR-EXP-0095 / PR-EXP-0212 / PR-EXP-0085 / PR-EXP-0106 / PR-EXP-0110 / PR-RO-07 already claimed at start time).
