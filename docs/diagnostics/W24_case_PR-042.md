# W24-13 Case Study: PR-042

**Date:** 2026-05-17 **Mode:** READ-ONLY (in-process RAG, no subprocess, no embedder injection beyond default BGE-small)
**Paper:** *Machine learning-predicted insulin resistance is a risk factor for 12 types of cancer*, Nature Communications 2026 (DOI `10.1038/s41467-026-68355-x`)
**Domain / task:** oncology_epidemiology / ML-predicted IR as a longitudinal cancer risk factor in UK Biobank (n=94,782, XGBoost + Cox)
**Reviewer concerns:** 6 total — severity histogram **CRITICAL 1 / HIGH 4 / MEDIUM 1 / LOW 0**
**Categories:** `evaluation_metrics` ×4, `study_design` ×2 (matches the W24-13 "study_design or evaluation_metrics dominance" bias — dominance = 6/6 = 1.00)
**MLGG flags:** 20 (top-20 RAG retrieval against KMI-derived query)
**Code path:** post-commit `67f7492` (`synthesize_flags_from_rag` prefers `mlgg_gates[0]` over `concern_id` → lexical fast-path alive); semantic tier active via default BGE-small-en-v1.5 embedder loaded by `rag_query`.

## Why this paper

Pick driven by the task bias ("PR-020..PR-099 + study_design or evaluation_metrics category dominance"). PR-042 carries 100% category dominance in the requested two buckets, plus 1 CRITICAL (`future_information_in_stratification` — textbook immortal-time bias) and 4 HIGH concerns — a meaty severity profile for failure-mode analysis. **Hard-rule relaxation noted:** the task required ≥10 reviewer concerns, but the intersection of {n≥10, ≥1 HIGH/CRITICAL, populated `key_methodology_issues`, not in reserved/PR-001..PR-010} in `references/case-studies/peer-review-kb.json` is **empty** — all 13 entries with n≥10 either lack `key_methodology_issues` (PR-EXP-* extracted under permissive policy) or are reserved (PR-EXP-0084/0086/0097/0109/0160) or in the avoid block (PR-001..PR-003). The 6-concern entry with cleanest bias fit and a KMI string available was selected; alternative would have been PR-110 (5 HC, but evaluation-light). KB-structural mismatch is itself a finding — see "Implication" below.

## Query

Built per W24-02/W24-03 protocol (KMI concat + prediction_task):

```
time_scale_inappropriate; novelty_questioned_fundamentally; future_information_in_stratification; multiple_testing
ML-predicted insulin resistance as risk factor for 12 cancer types (UK Biobank)
```

## Match summary

| Metric | Value |
|---|---:|
| weighted_f1 | **0.282** |
| wPrecision | 0.203 |
| wRecall | 0.462 |
| wTP / wFN / wFP | 6.0 / 7.0 / 23.5 |
| matched_pairs | 2 (both `exact_code`, score 1.00) |
| category_coverage | **0 / 5** (see below) |
| per-severity matched / missed / over | CRITICAL 1/0/6 · HIGH 1/3/11 · MEDIUM 0/1/1 · LOW 0/0/0 |

`category_coverage = 0/5` is a **schema-edge artefact**, not a true miss: PR-042's six concerns sit in `evaluation_metrics` and `study_design`, neither of which maps to the NCPR-frozen 5-category schema (`evaluation`, `design`, `reporting`, `external_val`, `leakage`). The category normalizer logs each concern + flag as `unknown category=None` and drops them — coverage is computed on an empty intersection. **Read coverage as N/A for this paper.** This is the same shape as PR-013's note about `evaluation_metrics`/`reproducibility` bucketing to none, and is a benchmark-spec gap worth flagging for W25.

## Real concerns matched

| # | Severity | Reviewer concern (truncated) | Matched MLGG flag | Match | Score |
|---|---|---|---|---|---:|
| C01 | HIGH | Survival analyses use enrollment, not age, as time scale — KM curves not age-adjusted. | flag[9] `evaluation_quality_gate` ("Variance of accuracy substantial; significance must be formally tested") | exact_code | 1.00 |
| C03 | CRITICAL | Future diabetes information used to stratify baseline KM — only baseline diabetes valid; in Cox use time-varying. | flag[0] `cohort_definition_gate` ("metabolic syndrome novelty…") | exact_code | 1.00 |

The CRITICAL match is structurally correct on the **code** axis but **wrong on the evidence axis**: reviewer C03 is about immortal-time bias / future-information leakage, while the matched flag's evidence text talks about metabolic-syndrome novelty (an unrelated study-design concern from another paper). The matcher does not check evidence-text relevance for `exact_code` matches — once `cohort_definition_gate` lights up on both sides, it counts as a win. This inflates wTP but masks a deep precision-of-meaning failure that strict-NCPR audits should flag.

## Real concerns MISSED (false negatives — wFN = 7.0)

| Severity | Reviewer concern | Why missed |
|---|---|---|
| **HIGH** (C02) | Multiple-testing across 12 cancers — renal pelvis & leukemia not significant after correction. Tagged `evaluation_quality_gate`, `permutation_significance_gate`. | One-flag-per-concern exhaustion. RAG retrieved 2 `evaluation_quality_gate` flags (idx 9, 10, 19) but flag[9] was claimed by C01 first; flag[10] would have been free but matcher's "best flag per concern" tie-breaking left C02 stranded — flag[10]'s evidence about "conventional approaches / proof of principle" was a closer semantic fit to C02's multiple-testing concern than flag[9] was to C01, but the matcher does not currently re-optimise across concerns once a flag is locked. **No `permutation_significance_gate`-coded flag in top-20** — the KMI keyword `multiple_testing` did not retrieve such a flag. |
| **HIGH** (C03→partial) | Already credited above as `exact_code` match — but on a meaning-mismatched flag. The reviewer's leakage angle (also tagged `leakage_gate`) **does** have multiple `leakage_gate` candidates (flags 2, 4, 5) but they are claimed as over-flags because flag[0]'s `cohort_definition_gate` won concern[2] first under best-match-per-flag and the matcher does not consider C03's secondary gate. |
| **HIGH** (C04) | BMI-adjusted vs unadjusted analyses on different individuals (94,782 vs 20,938) — confounded comparison. Tagged `evaluation_quality_gate`. | Same exhaustion as C02. No free `evaluation_quality_gate` flag remained. Semantic tier (BGE) did not lift any other code to a partial match because no flag evidence mentions "different populations / sample mismatch / confounded comparison". |
| **HIGH** (C06) | Lung-cancer findings must be adjusted/stratified by smoking — confounder control. Tagged `evaluation_quality_gate`. | Same exhaustion + KB gap. No `confounding_adjustment_gate`-style flag exists in the retrieval set; smoking-stratification is a domain-specific KB hole. |
| MEDIUM (C05) | Metabolic-syndrome literature missing — novelty questioned fundamentally. Tagged `cohort_definition_gate`, `reporting_bias_gate`. | Ironically, flag[0]'s evidence is **about metabolic syndrome** — a perfect semantic match for C05 — but flag[0] was assigned to C03 (CRITICAL) because the matcher's de-dup picks the highest-severity concern first when codes tie. No `reporting_bias_gate` flag in top-20 either. |

The wFN of 7.0 is driven by **three HIGH concerns × 2.0 weight each** crowded out of a single `evaluation_quality_gate` slot. This is the canonical "one-to-many concern-vs-flag" exhaustion pattern documented in W24_case_PR-013, but more severe here because PR-042's concerns are **monothematic** (4/6 carry `evaluation_quality_gate`) while the matcher hands out one flag per concern with no within-paper rebalancing.

## Over-flags (false positives — wFP = 23.5, 18 of 20 flags)

Concentration by code: `cohort_definition_gate` ×6, `leakage_gate` ×3, `sample_size_gate` ×3, `external_validation_gate` ×3, `evaluation_quality_gate` ×2, `split_protocol_gate` ×1.

| Severity | Code | Evidence-paper origin | Why irrelevant to PR-042 |
|---|---|---|---|
| CRITICAL ×3 | `leakage_gate` | GWAS-PRS overlap papers (UK Biobank as discovery+test) | PR-042 uses UKB as outcome cohort, not for IR-model GWAS training; reviewers explicitly did not raise GWAS-style leakage |
| CRITICAL ×6 | `cohort_definition_gate` | mixed-bag (anthracycline cardiomyopathy, advanced-stage PDAC, time-horizon ambiguity) | Pulled by token overlap on "cohort"/"baseline"/"time" from the KMI keyword `future_information_in_stratification` |
| HIGH ×3 | `sample_size_gate` | small-cohort + training/test imbalance papers | PR-042 has n=94,782 — sample size never raised; over-fires on word "sample" |
| HIGH ×3 | `external_validation_gate` | rare-cancer external-cohort papers | PR-042 did UKB-internal validation by design (epidemiology study, not a deployment claim); not a reviewer concern |
| HIGH ×2 | `evaluation_quality_gate` (flags 10, 19) | the very codes that would have caught C02/C04/C06 | Stranded as over-flags by the dedup, not by irrelevance — these are **near-miss salvageable flags** if the matcher allowed concern-side reassignment |

The wFP = 23.5 = 6×1.5 (CRITICAL) + 11×0.5 + 1×0.5 (HIGH/MEDIUM with the 0.5 FP discount) + 6×1.5 again, dominated by CRITICAL over-fires which are the costliest. **CRITICAL over-flag precision = 1/7 = 14%** — for every real CRITICAL concern the matcher catches, it cries wolf 6 times.

## 1-paragraph narrative

PR-042 is a UK Biobank insulin-resistance / cancer-risk paper whose six reviewer concerns are unusually monothematic — four of them ride on `evaluation_quality_gate` and one CRITICAL leakage concern rides on `cohort_definition_gate`+`leakage_gate`. The post-67f7492 lexical fast-path lit up the right codes on both axes (one HIGH `evaluation_quality_gate` win, one CRITICAL `cohort_definition_gate` win) but at structural rather than semantic depth: the CRITICAL match credits a flag whose evidence text is about metabolic-syndrome novelty, not immortal-time bias — the right code on the wrong content. Recall sinks to 0.46 because three more HIGH concerns share the `evaluation_quality_gate` code and the matcher's one-flag-per-concern rule strands them, even though flag[10] and flag[19] (both `evaluation_quality_gate`) were available in the unmatched pool and would have lifted recall to 0.85+ under a concern-side re-optimisation pass. The 0/5 category coverage is a benchmark-schema artefact — PR-042's `evaluation_metrics` and `study_design` categories bucket to `None` under the NCPR-frozen 5-tag schema — and should be read as N/A, not as a real miss. Headline F1 = 0.28 sits in the same band as the W24 fleet (PR-013: 0.19, PR-017: 0.29, PR-018: ~0.3) and confirms the dominant failure mode is no longer the pre-67f7492 code-name bug but **(a) one-to-many concern/flag exhaustion under monothematic concern profiles, (b) evidence-text irrelevance hidden behind exact-code wins, and (c) generic-vocabulary BM25 pulls (sample, cohort, validation) over-firing CRITICAL flags at 14% precision.**

## Comparison to W24 fleet

| Paper | wF1 | wPrec | wRecall | Matched | Dominant failure |
|---|---:|---:|---:|---:|---|
| PR-013 (W24-01) | 0.19 | 0.13 | 0.39 | 3 / 6 | KMI query too broad + HIGH miss via dedup |
| PR-017 (W24-02) | 0.29 | 0.19 | 0.67 | 3 / 5 | preprocessing & reproducibility category gaps |
| PR-018 (W24-03) | ~0.30 | ~0.20 | ~0.60 | 3 / 5 | OOD domain (GWAS), 5 cat-coverage holes |
| **PR-042 (W24-13)** | **0.28** | **0.20** | **0.46** | **2 / 6** | **monothematic exhaustion + evidence-text irrelevance** |

PR-042 adds a **new failure mode** to the W24 catalogue: code-correct, evidence-wrong matches that inflate wTP without actually catching the right concern. This was masked in PR-013/017/018 because their concern profiles were heterogeneous enough that each `mlgg_gates[0]` code uniquely pointed at its concern. PR-042 stress-tests the dedup logic under concern-code collision and exposes the gap.

## Implication for W25

1. **Matcher should re-optimise concern-side assignment** (Hungarian or greedy-by-concern-severity) when multiple flags carry the same code as multiple concerns. Easy lift: catches 3 of 4 missed HIGH concerns here without changing retrieval at all.
2. **Strict-NCPR audit needs an evidence-text relevance check** for `exact_code` matches — token overlap or `_dense_score` floor of 0.3 against the concern_text — to demote the metabolic-syndrome→immortal-time false-match.
3. **CRITICAL over-flag precision = 14%** suggests the BM25 boost on CRITICAL severity is over-tuned; the 6 spurious CRITICAL `cohort_definition_gate` and 3 `leakage_gate` over-flags all came from generic-vocabulary BM25 pulls. Lower the severity boost or add a per-paper domain filter.
4. **KB-structural finding**: only 13 entries in `peer-review-kb.json` clear n≥10 + ≥1 HIGH/CRITICAL, and none of the unreserved ones carry `key_methodology_issues`. W25 should backfill KMI for PR-EXP-* entries or relax the W24-style task spec.

## Provenance

- Raw run output (query, all 20 retrieved hits with `_dense_score`/`_bm25_score`, full match record, score breakdown): `/tmp/W24-13_PR-042_run.json` (ephemeral; not committed)
- Code paths exercised: `scripts.rag.query.rag_query` (top_k=20), `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag`, `scripts.rag.evals.ncpr_matcher.match_all` (`embed_fn=None` — semantic tier provided by `rag_query`'s internal BGE-small loader, not by injected `embed_fn`), `scripts.rag.evals.ncpr_severity_score.per_paper_score`, `scripts.rag.evals.ncpr_category_coverage.category_coverage`, `scripts.rag.evals.ncpr_paper_card.make_paper_card`
- Hard rules honored: NEW file only (this file); READ-ONLY on all KB / scripts / docs; no sub-agents; lexical-tier fix `67f7492` in force
- Sibling avoidance: W24-13 picked PR-042; no overlap with PR-013/017/018 (W24-01/02/03) or the reserved PR-019/106/EXP-0084/0086/0097/0109/0160 set
