# W24-18 — Case Study: PR-RO-07 (real Nature Communications paper, oncology)

End-to-end MLGG NCPR run on a single real NC paper, following the W24-01/02/03
protocol (PDF-less variant: KB-derived query → `synthesize_flags_from_rag`
top_k=20 → `ncpr_matcher.match_all` → severity-weighted F1 + category coverage).
Run date 2026-05-17 on `main` post-67f7492 (`mlgg_gates[0]` gate-first mapping
active).

**Domain choice rationale.** Oncology — specifically ICI / personalized-treatment-effect
modelling — was picked because MLGG is **less well-curated** here than for diabetes
or cardiology cohort-prediction (the modal KB neighbourhoods). The paper centres on
causal-inference assumptions (no residual confounding, SUTVA), ITE validation, and
post-hoc method addition — three concern axes the reserved W24-11..17 picks
(genomics PRS, EHR cohort) underweight. Stress-tests retrieval generalisation
outside MLGG's tabular-EHR-leakage sweet spot.

## Paper meta

| Field | Value |
|---|---|
| Paper ID | **PR-RO-07** |
| DOI | `10.1038/s41467-025-61823-w` |
| Title | ML-driven strategies for adapting immunotherapy in metastatic NSCLC |
| Journal | Nature Communications (2025) |
| Domain | oncology (NSCLC immunotherapy, ITE) |
| Prediction task | Individual benefit prediction for adding chemotherapy to ICI in metastatic NSCLC |
| Data type | genetic_plus_clinical_tabular |
| Sample size | not recorded in KB |
| Review rounds | 3 |
| Outcome | `reporting_summary_only` |
| `key_methodology_issues` | **empty list in KB** — query seed synthesized from concern `tags` instead |
| `reviewer_concerns` | **10** (1 CRITICAL, 5 HIGH, 4 MEDIUM) |
| MLGG-coverage caveat | Causal-ITE oncology with ICI/chemo treatment-rule learning sits **outside** MLGG's nominal scope (retrospective binary EHR classification). Findings are out-of-distribution stress, not a pass/fail on the SUT mandate. |

**Query passed to `rag_query` (`top_k=20`):**

> ML-driven strategies for adapting immunotherapy in metastatic NSCLC. Individual benefit prediction for adding chemotherapy to ICI in metastatic NSCLC. Key issues: binary_vs_time_to_event, biomarker_validation_standard, causal_inference_assumptions, code_unavailable_at_review, confounder_completeness, deferred_release, endpoint_choice, endpoint_information_loss, external_validation_cohort, fdr_vs_bonferroni, genomic_feature_definition_opaque, ite_assumption_unchecked, language_inflation, loss_function_search, method_application_vs_invention, missing_clinical_variables, multiple_testing_correction, no_residual_confounding

(KMI list was empty; the alphabetised first-18 union of concern `tags` substitutes
for the canonical KMI seed used in PR-017/PR-018.)

## Match summary

| Metric | Value |
|---|---|
| Flags synthesized | 20 |
| Reviewer concerns | 10 |
| Matched pairs (all `exact_code`) | **3** |
| Unmatched flags (FP / over-flags) | 17 |
| Unmatched concerns (FN / misses) | 7 |
| Weighted **F1** | **0.356** |
| Weighted precision | 0.296 |
| Weighted recall | 0.444 |
| wTP / wFN / wFP | 8.0 / 10.0 / 19.0 |
| Category coverage (5-bucket diagnostic) | **0/5 — diagnostic blind** |
| Matcher | real `ncpr_matcher.match_all` (no stub; record `matcher` field is `None`, the known cosmetic bug from W24-02) |
| Wall time | 13.6 s (cold; BGE load dominant) |

Per-severity:

| Severity | Matched | Missed | Extra flags |
|---|---|---|---|
| CRITICAL | 1 | 0 | 3 |
| HIGH | 2 | 3 | 12 |
| MEDIUM | 0 | 4 | 2 |
| LOW | 0 | 0 | 0 |

## Matched (3)

| Concern | Sev | Gate matched | Type | Score |
|---|---|---|---|---|
| PR-RO-07-C02 (causal assumptions: no residual confounding, SUTVA) | HIGH | `cohort_definition_gate` | exact_code | 1.00 |
| PR-RO-07-C03 ("validation" misuse for ITE; biomarker-validation standard) | CRITICAL | `external_validation_gate` | exact_code | 1.00 |
| PR-RO-07-C04 (no significance test on subgroup ITE; loss-function search) | HIGH | `model_selection_audit_gate` | exact_code | 1.00 |

The single CRITICAL concern (C03) was hit cleanly. The two HIGH matches both
land on the **first** of the concern's listed `mlgg_gates` — the gate-first
mapping behaves as the post-67f7492 fix intended.

## Missed (7)

| Concern | Sev | Cat | Expected gates | Why missed |
|---|---|---|---|---|
| PR-RO-07-C01 | MEDIUM | reporting | `reporting_bias_gate` | Query carries `language_inflation` / `method_application_vs_invention` / `overclaimed_novelty` — semantically a reporting concern, but no `reporting_bias_gate` exemplar surfaced in top-20. KB content gap for "novelty overclaim". |
| PR-RO-07-C05 | HIGH | model_selection | `tuning_leakage_gate`, `model_selection_audit_gate`, `evaluation_quality_gate`, `permutation_significance_gate` | `model_selection_audit_gate` is already best-matched to C04 (score 1.00); matcher's one-flag-per-concern dedup drops the second candidate. No `tuning_leakage_gate` or `permutation_significance_gate` retrieved at all despite explicit `p_hacking`, `test_set_used_in_method_development`, `post_hoc_method_addition` tags in the query. |
| PR-RO-07-C06 | HIGH | study_design | `cohort_definition_gate`, `fairness_equity_gate` | Same dedup story: 8x `cohort_definition_gate` flags retrieved but C02 claimed the best one; no `fairness_equity_gate` retrieved. |
| PR-RO-07-C07 | HIGH | study_design | `cohort_definition_gate`, `feature_lineage_gate`, `reporting_bias_gate` | Dedup on `cohort_definition_gate`; `feature_lineage_gate` and `reporting_bias_gate` absent from top-20. |
| PR-RO-07-C08 | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | 4x `evaluation_quality_gate` retrieved but evidence-text drift (CancerSEEK, Galleri, ERBB2 breast cancer) — none mention `binary_vs_time_to_event` endpoint choice. Semantic threshold dropped below 0.70. |
| PR-RO-07-C09 | MEDIUM | reproducibility | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate`, `reporting_bias_gate` | Reproducibility neighbours absent from top-20 — identical failure mode to PR-017-C04. Query carries `code_unavailable_at_review` / `deferred_release` but neither pulled a repro-gate exemplar. |
| PR-RO-07-C10 | MEDIUM | reporting | `fairness_equity_gate`, `reporting_bias_gate` | Same as C01/C09 — reporting-and-fairness exemplars under-represented in KB neighbours for this query. |

Five of seven misses are **starved by retrieval breadth, not matcher logic** —
the right gates are wired but no top-20 neighbour carries paper-relevant
evidence text. Two (C05, C06) are matcher-dedup victims that would resolve if
`match_all` allowed one flag to satisfy multiple concerns sharing a gate.

## Over-flags (17 — concentrated in cohort / evaluation)

| Bucket | Count | Severity profile |
|---|---|---|
| `cohort_definition_gate` | 7 | 2 CRITICAL, 5 HIGH |
| `evaluation_quality_gate` | 4 | 4 HIGH |
| `calibration_dca_gate` | 2 | 2 MEDIUM |
| `split_protocol_gate` | 1 | 1 CRITICAL |
| `model_selection_audit_gate` | 1 | 1 HIGH |
| `sample_size_gate` | 1 | 1 HIGH |
| `external_validation_gate` | 1 | 1 HIGH |

**3 CRITICAL over-flags — the most damaging surface:**

1. `cohort_definition_gate` (CRIT) — local-therapy decision evidence from a
   prostate/urology paper. Not what PR-RO-07's reviewers raised.
2. `split_protocol_gate` (CRIT) — MIMIC-III/IV pooled-SMOTE leakage. PR-RO-07
   has no MIMIC, no SMOTE; pure topic bleed.
3. `cohort_definition_gate` (CRIT) — H. pylori AI-clinician recommendation
   model. Wrong disease, wrong cohort.

These 3 CRITICAL over-flags carry wFP = 4.5 (severity-weighted), accounting
for ~24% of the precision penalty. A downstream consumer treating them as
paper-specific findings would inflate severity inappropriately.

## Narrative

PR-RO-07 is an oncology / causal-ITE paper that lands precisely where MLGG's
KB is thin: ICI personalized-treatment-effect modelling, SUTVA / no-residual-
confounding assumptions, and post-hoc method addition across validation
cohorts. The pipeline produced recall 0.44 and precision 0.30 (wF1 0.36) —
the **CRITICAL concern was caught cleanly** (validation misuse for ITE →
`external_validation_gate`, exact_code 1.00) and 2/5 HIGH concerns matched on
their first listed gate. But 7 of 10 concerns missed: 5 are KB-content gaps
(no reproducibility, fairness, feature-lineage, or reporting-bias neighbours
retrieved despite explicit tag signals in the query), and 2 are matcher-dedup
collisions where 7x `cohort_definition_gate` and 4x `evaluation_quality_gate`
flags were collapsed to one match each. The 5-bucket category-coverage metric
returned **0/5** because the KB stores categories as natural-language strings
(`study_design`, `external_validation`, `reporting`, `evaluation_metrics`,
`reproducibility`, `model_selection`) that the coverage taxonomy
(`evaluation`/`design`/`reporting`/`external_val`/`leakage`) does not normalise
— a real schema gap, not a paper-specific failure (logged repeatedly to stderr
as "dropping reviewer item with unknown category"). The 3 CRITICAL over-flags
(prostate local therapy, MIMIC-SMOTE leakage, H.-pylori AI clinician) are pure
out-of-modality bleed and the most worrying surface.

## Compare to W24-01..03 siblings

| Run | Paper | Domain | n_concern | wF1 | wP | wR | matched / miss |
|---|---|---|---:|---:|---:|---:|---|
| W24-02 | PR-017 | genomics PRS | 5 | 0.291 | 0.186 | 0.667 | 3 / 2 |
| W24-03 | PR-018 | genomics PRS | 5 | 0.288 | 0.184 | 0.667 | 3 / 2 |
| **W24-18 (this)** | **PR-RO-07** | **oncology ITE** | **10** | **0.356** | **0.296** | **0.444** | **3 / 7** |

The oncology run has the **highest precision** of the three (0.30 vs 0.19) —
the larger concern set (10 vs 5) puts more matchable gates in play, so a
larger share of retrieved flags hit *something*. But **recall drops** from
0.67 to 0.44 because 7 of 10 oncology concerns are KB-blind (reporting,
fairness, reproducibility, feature-lineage, permutation-significance
neighbours absent). Pattern is consistent with the W23-D5 macro picture
(retrieval finds neighbourhoods, evidence-text fidelity limits precision)
but exposes a new failure mode the genomics siblings didn't surface:
**matcher dedup penalty scales with concern count** when concerns share
gates (5/7 cohort-design concerns competed for the same 7 retrieved
`cohort_definition_gate` flags).

## Reproducibility

- Runner: `/tmp/W24_18_run.py` (in-process; calls `synthesize_flags_from_rag`
  + `match_all` + `per_paper_score` + `category_coverage`).
- Result sidecar: `/tmp/W24_18_result.json`.
- KB source: `references/case-studies/peer-review-kb.json` → `entries[id=PR-RO-07]`.
- Wall time 13.6 s cold (BGE model + index load dominant; warm reuse would be ~1.3 s per W22-V2).
