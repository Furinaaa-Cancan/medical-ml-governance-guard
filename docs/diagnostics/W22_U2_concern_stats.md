# W22-U2 — Reviewer-Concern Density Stats for NCPR Power Analysis

**Date:** 2026-05-17  **Task:** W22-U2 (NCPR Benchmark v1 wave)
**Inputs:** `references/case-studies/peer-review-kb.json` (contract `peer_review_kb.v1.4`)
**Mode:** READ-ONLY audit. No KB / scripts / workflow edits.
**Companion artifacts:** `/tmp/W22_U2_snapshot.json`, `/tmp/W22_U2_canonical.json`, `/tmp/W22_U2_analysis.txt`

---

## 0. Headline

| Quantity | Value |
|---|---|
| KB entries (papers) | **335** |
| Papers with ≥1 reviewer concern | **154** |
| Total reviewer concerns | **817** |
| Mean concerns per **paper-with-concerns** | **5.31**  (median 5.0, σ 2.92, range 1–15) |
| Mean concerns per **all papers** | 2.44  (median 0, σ 3.30) |
| Papers with ≥1 CRITICAL concern | **32 / 154 (20.8%)** |
| Papers with ≥1 CRITICAL **or** HIGH | **126 / 154 (81.8%)** |
| Papers with only-LOW concerns | **1 / 154 (0.6%)** |
| Concern texts that are byte-unique | **817 / 817 (100%)** |
| Concerns sharing a `canonical_pattern_id` (CP-001…) | **454 / 817 (55.6%)** — i.e. only 44% are unmatched singletons |

The "154 papers / 817 concerns" framing in the task brief matches the
subset of 335 KB entries that have non-empty `reviewer_concerns`.

---

## 1. Per-paper concern histogram

Across all 335 KB entries (most have 0 — methods-only stubs):

| Bucket | All 335 papers | Papers-with-concerns (n=154) |
|---|---:|---:|
| 0 concerns | 181 | – |
| 1 | 13 | 13  (8.4%) |
| 2 | 10 | 10  (6.5%) |
| 3–5 | 61 | 61  (39.6%) |
| 6–10 | 61 | 61  (39.6%) |
| 11+ | 9 | 9   (5.8%) |

**Top-10 by concern count:** PR-EXP-0084 (15), PR-EXP-0160 (15),
PR-EXP-0086 (14), PR-EXP-0097 (14), PR-EXP-0109 (14), PR-EXP-0095 (12),
PR-003 (11), PR-EXP-0110 (11), PR-EXP-0212 (11), PR-001 (10).

---

## 2. Per-category and per-severity counts

### Categories (raw `category` field)

| Category | Count | % of 817 |
|---|---:|---:|
| evaluation_metrics | 196 | 24.0% |
| study_design | 172 | 21.1% |
| reporting | 95 | 11.6% |
| external_validation | 68 | 8.3% |
| model_selection | 58 | 7.1% |
| preprocessing | 49 | 6.0% |
| reproducibility | 45 | 5.5% |
| clinical_utility | 39 | 4.8% |
| interpretability | 31 | 3.8% |
| feature_selection | 20 | 2.4% |
| split_protocol | 18 | 2.2% |
| sample_size | 17 | 2.1% |
| data_leakage | 9 | 1.1% |

### Severities

| Severity | Count | % |
|---|---:|---:|
| MEDIUM | 412 | 50.4% |
| HIGH | 304 | 37.2% |
| LOW | 60 | 7.3% |
| CRITICAL | 41 | 5.0% |

---

## 3. Severity × category cross-tab (top 15)

| Severity | Category | n |
|---|---|---:|
| MEDIUM | evaluation_metrics | 105 |
| HIGH | evaluation_metrics | 78 |
| MEDIUM | study_design | 72 |
| HIGH | study_design | 71 |
| MEDIUM | reporting | 59 |
| HIGH | external_validation | 49 |
| MEDIUM | model_selection | 38 |
| MEDIUM | preprocessing | 28 |
| LOW | reporting | 28 |
| MEDIUM | interpretability | 27 |
| MEDIUM | clinical_utility | 26 |
| MEDIUM | reproducibility | 22 |
| CRITICAL | study_design | 21 |
| HIGH | preprocessing | 19 |
| HIGH | reproducibility | 19 |

**Observations:**
- CRITICAL is concentrated in `study_design` (21 of 41 CRITICALs, 51%).
- `external_validation` skews HIGH (49/68 = 72% HIGH), as expected — reviewers don't fail papers for it, they just demand it.
- LOW lives in `reporting` (28/60 = 47%) — minor write-up nits.

---

## 4. Per-journal mean concerns

| Journal | N papers | N with concerns | mean (all) | mean (with) |
|---|---:|---:|---:|---:|
| Nature Communications | 248 | 150 | 3.21 | 5.30 |
| Communications Medicine | 87 | 4 | 0.25 | 5.50 |

Communications Medicine is severely under-annotated (4/87 papers with
reviewer-concern data). This collapses the journal pool to effectively
**single-source (NC)** for any stratification exercise.

---

## 5. Concern uniqueness — KB diversity

- **Exact-text uniqueness:** 817/817 (100%). No two concerns share verbatim wording.
- **Canonical-pattern reuse:** 454/817 concerns (55.6%) share a `canonical_pattern_id` with ≥1 other concern. So while wording varies, **the underlying flaw types are recurrent**.

### Top-10 canonical patterns (recurrent flaw families)

| Rank | CP id | # concerns | # papers | Dominant category | Top tags |
|---|---|---:|---:|---|---|
| 1 | CP-001 | 88 | 63 | evaluation_metrics | multiple_testing, incomplete_metrics, unfair_comparison, marginal_improvement |
| 2 | CP-002 | 74 | 45 | study_design | outcome_definition, selection_bias, cohort_definition, label_validity |
| 3 | CP-003 | 68 | 51 | study_design | sensitivity_analysis, prediction_window_justification, icd_code_accuracy |
| 4 | CP-004 | 48 | 37 | reporting | manuscript_structure, model_description_unclear, accessibility |
| 5 | CP-005 | 31 | 26 | model_selection | model_justification, multiple_model_comparison, ablation_missing |
| 6 | CP-006 | 29 | 27 | evaluation_metrics | clinical_relevance, auprc_missing, auc_only, ablation_missing |
| 7 | CP-007 | 24 | 22 | reporting | no_tripod, missing_demographics_table, missing_flow_diagram |
| 8 | CP-008 | 22 | 21 | external_validation | no_external_validation, same_cohort_validation, internal_split_only |
| 9 | CP-009 | 18 | 18 | reproducibility | no_code_availability, irreproducible_methods |
| 10 | CP-011 | 16 | 15 | reproducibility | irreproducible_methods, insufficient_methods_detail |

Top-10 patterns cover **418/817 = 51.2%** of all concerns.

---

## 6. T3-holdout eligibility funnel (for W22-V1 power analysis)

Applying inclusion criteria 1, 2, 5 from
`references/benchmark/ncpr_v1_holdout_criteria.md` (the ones that this
audit can evaluate without checking eval-set membership or methods-text
existence — criteria 3 and 4):

| Filter step | Surviving papers |
|---|---:|
| Has ≥1 concern | 154 |
| Has ≥3 concerns (criterion 1) | **131** |
| + journal in NC/CM/LDH/JAMA/NM/npjDM (criterion 2) | 131 (all current entries pass) |
| + ≥1 CRITICAL **or** HIGH (severity-mix per-paper rule) | **126** |

So the pre-stratification eligible pool is **126**, ≫ N = 30.
The severity-floor failure-mode threshold ("eliminates >50% of
candidates") is *not* triggered: only 4% drop (131 → 126).

### Category-floor feasibility (NCPR-5 dimensions)

Aggregating across all 764 concerns in the 126-paper eligible pool,
mapping the 13 raw categories into the 5 NCPR dimensions per spec:

| NCPR dim | Concerns | % of 764 | ≥10% floor? |
|---|---:|---:|:---:|
| design | 253 | 33.1% | OK |
| evaluation | 214 | 28.0% | OK |
| reporting | 159 | 20.8% | OK |
| leakage | 74 | 9.7% | **MISS (−0.3pp)** |
| external_validation | 64 | 8.4% | **MISS (−1.6pp)** |

Two dimensions sit *just* below the 10% aggregate floor at the eligible-pool level. Within any random 30-paper subsample the deficit is likely larger. The spec's escape hatch — *"Augment from communications_medicine"* — is **unusable**: CM contributes only 4 papers with concerns (Section 4).

---

## 7. Verdict — does data support N = 30 stratified holdout?

### **YELLOW** — N = 30 is mechanically feasible, but two stratification floors are at risk.

| Criterion | Status | Notes |
|---|:---:|---|
| Eligible-pool size ≥ 30 | GREEN | 126 papers pass criteria 1, 2, 5 + severity floor. 4.2× headroom. |
| Severity floor (≥1 CRIT/HIGH per paper) | GREEN | 126/131 = 96% of ≥3-concern papers qualify. |
| Journal proportionality (±2, no journal >40%) | RED | Pool is effectively single-journal (NC dominates 150/154). Spec's "±2" and "<40%" rules cannot bind meaningfully. Recommend logging this as a deterministic `stratification_deviation` rather than blocking. |
| NCPR-dim floor (each ≥10% aggregate) | YELLOW | At eligible-pool level: leakage 9.7%, external_validation 8.4%. **Builder will hit the "<10%" failure-mode** when sampling 30. |
| Concern diversity (no canonical pattern dominates) | GREEN | Top CP covers 88/817 = 10.8% — diverse enough to score recall. |

**Recommended actions for W22-V1 power analysis:**
1. Treat 126 as the eligible-pool denominator for any per-paper recall power calculation. Mean ≈ 6.1 concerns/paper on this pool (764/126), so a 30-paper holdout has ≈ 180–185 concerns to score against — sufficient for narrow 95% CIs on recall.
2. Pre-register a deviation policy for the leakage / external_validation 10% floor: either (a) lower the floor to 8% for v1 and document, or (b) relax journal-floor first per spec table.
3. Flag the single-journal concentration to W22-T1 as a follow-up: NM / npjDM extensions (the queued W22-T1 work) are the only realistic path to true journal stratification.

---

## 8. Reproducibility

Analysis script: `/tmp/W22_U2_analyze.py` (Python 3, stdlib only; reads
the committed `peer-review-kb.json`). Re-run with:

```bash
python3 /tmp/W22_U2_analyze.py
```

Raw JSON snapshots: `/tmp/W22_U2_snapshot.json`, `/tmp/W22_U2_canonical.json`.
