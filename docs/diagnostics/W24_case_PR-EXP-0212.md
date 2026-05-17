# W24-17 Case Study — PR-EXP-0212

**Picked by W24-17 with reason:** Filtered the 335-entry peer-review KB to
papers with >=10 reviewer concerns and >=1 CRITICAL/HIGH severity, then
removed the W24 reserved IDs (`PR-013/017/018/019/106`,
`PR-EXP-0084/0086/0095/0097/0106/0109/0160`) plus the PR-001..PR-010
band and the W24 siblings already claimed at run-time
(`PR-024`, `PR-EXP-0110`, `PR-RO-07`). Two free survivors remained:
`PR-EXP-0085` and `PR-EXP-0212`. The W24-17 brief asks to bias toward
**calibration** or **fairness** concerns to stress the calibration_dca_gate
(W15-A3) and fairness_equity_gate (W16-B5) gates. PR-EXP-0212 carries an
explicit `calibration_dca_gate` ground-truth concern (C11) and is a
binary AKI prediction task on retrospective EHR — squarely inside MLGG's
scope envelope (CLAUDE.md modality boundary). PR-EXP-0085 was passed
over because it is a graph-neural-network on genomic AMR — out of
MLGG's stated modality scope, so a low F1 would conflate KB-coverage
with structural-scope mismatch. KMI field is null (same provenance gap
the sibling W24 picks reported); KMI was derived from the populated
`mlgg_gates` on every concern.

## Paper meta

| Field | Value |
|---|---|
| Paper ID | `PR-EXP-0212` |
| Title | Cross-site transportability of an explainable artificial intelligence model for acute kidney injury prediction |
| DOI | `10.1038/s41467-020-19551-w` |
| Journal | Nature Communications |
| Year | 2020 |
| Prediction task | Acute kidney injury within 7 days of admission, with cross-site transportability (XGBoost + SHAP) |
| Data type | clinical_tabular (EHR) |
| Review rounds | 2 |
| Reviewer concerns | 11 (0 CRITICAL, 3 HIGH, 6 MEDIUM, 2 LOW) |
| Categories present | study_design, external_validation, evaluation_metrics, model_selection, feature_selection, preprocessing, interpretability, reporting, clinical_utility |
| Calibration / Fairness gates fired by reviewers? | calibration_dca_gate (C11, LOW) yes; fairness_equity_gate not in concerns |

## Match summary

Pipeline: PDF Methods extraction (W23-A2) -> 5-chunk slice ->
`rag_query(top_k=20)` per chunk -> `synthesize_flags_from_rag` (post
67f7492 fix, `mlgg_gates[0]` keying) -> dedupe by code -> 13 unique
flags -> `ncpr_matcher.match_all(embed_fn=None)` ->
`ncpr_severity_score.per_paper_score`. Wall time: **11.19 s** warm
cache, single process; no errors; W23-A2 extractor live (no stub
fallback).

| Metric | Value |
|---|---|
| MLGG flags synthesized | 13 (deduped from 5 chunks x top_k=20) |
| Reviewer concerns | 11 |
| Matched pairs (1:1) | 6 |
| Unmatched flags (FP) | 7 |
| Unmatched concerns (FN) | 5 |
| Weighted TP / FN / FP | 8.0 / 5.0 / 9.0 |
| Weighted precision | 0.471 |
| Weighted recall | 0.615 |
| Weighted F1 | **0.533** |
| Matcher reported | `unknown` (real `match_all` used; result dict has no `matcher` key) |

Per-severity breakdown (matched / missed / extra_flags):

| Severity | Matched | Missed | Extra flags |
|---|---|---|---|
| CRITICAL | 0 | 0 | 1 |
| HIGH | 3 | 0 | 7 |
| MEDIUM | 2 | 4 | 0 |
| LOW | 0 | 2 | 0 |

**HIGH recall is 3/3 = 100%** — every reviewer-flagged HIGH concern was
caught at exact-code level. There are no CRITICAL concerns in this
paper, so CRITICAL recall is vacuous; one CRITICAL extra-flag from KB
cross-leak (see "Over-flagged" below). MEDIUM recall is 2/6 = 33%.
Both LOW concerns missed — including the headline **calibration_dca_gate**
hit (C11).

## Matched concerns (6)

| Concern | Severity | Matched flag | Match type | Score |
|---|---|---|---|---|
| C01 selection-pressure on transportable cohort (kidney-disease subset) | HIGH | `cohort_definition_gate` | exact_code | 1.00 |
| C02 incremental clinical utility over creatinine alone | MEDIUM | `clinical_metrics_gate` | exact_code | 1.00 |
| C03 missingness handling not described | LOW | `missingness_policy_gate` | **category** | 0.50 |
| C04 model-selection: why XGBoost vs simpler alternatives | HIGH | `model_selection_audit_gate` | exact_code | 1.00 |
| C05 distribution shift between BIDMC and MIMIC | MEDIUM | `distribution_generalization_gate` | exact_code | 1.00 |
| C06 external-validation depth (single re-test site) | HIGH | `external_validation_gate` | exact_code | 1.00 |

Five of six are `exact_code` matches. C03's `missingness_policy_gate`
match is the only **category** hit; per spec it counts toward
`category_coverage` but only contributes wTP if the matcher's loop
picks it, which it did because no exact-code flag claimed the slot.
`embed_fn=None` was safe — semantic tier not exercised.

## Missed concerns (5)

| Concern | Severity | Tagged gates | Why MLGG missed |
|---|---|---|---|
| C07 ICD/CPT timing (pre- vs current admission) | MEDIUM | `feature_engineering_audit_gate` + `feature_lineage_gate` + `cohort_definition_gate` | `feature_engineering_audit_gate` flag exists (F03) but the matcher's 1:1 de-dup spent it on no concern (C03 took missingness instead); `cohort_definition_gate` slot went to C01. Classic flag-exhaustion. |
| C08 censoring at 7 days for long-stay patients | MEDIUM | `cohort_definition_gate` | `cohort_definition_gate` slot taken by C01. |
| C09 split protocol details missing from Methods | MEDIUM | `reporting_bias_gate` | **`reporting_bias_gate` is absent from all 13 synthesized flags** — RAG did not surface it in this run. |
| C10 SHAP interpretability for individual patients | MEDIUM | `shap_interpretability_gate` | `shap_interpretability_gate` is absent from the flag set — KB-coverage gap. W22-U2 noted this gate is sparse. |
| **C11 transportability vs simple refit + calibration / DCA missing** | **LOW** | **`calibration_dca_gate`** + `distribution_generalization_gate` + `clinical_metrics_gate` | All three tagged gates have lexical neighbours: `distribution_generalization_gate` (F10) went to C05, `clinical_metrics_gate` (F12) went to C02. **`calibration_dca_gate` itself is missing from the entire flag set** — the gate that the W24-17 brief explicitly asked us to probe did not surface for the one paper whose reviewer pre-tagged it. |

## Over-flagged (7 FP flags)

Six of seven over-flags carry evidence text from *other* KB papers
(the same cross-paper RAG-leak pattern documented in PR-EXP-0095 and
PR-EXP-0110 sibling case studies). The CRITICAL over-flag is the one
to watch.

| FP flag | Severity | Evidence belongs to (paraphrase) |
|---|---|---|
| `split_protocol_gate` | **CRITICAL** | Cardiotoxicity (PR-EXP-0110) pretraining-cohort overlap quote — leaks into top-20 because "patients included in cohort presented in this manuscript" is high BM25 weight on split / cohort tokens. Wrong paper, wrong gate-evidence pairing. |
| `feature_engineering_audit_gate` | HIGH | ICD-9/10 codes as predictor critique — coincidentally adjacent to C07 (also ICD) but de-dup routed C07 elsewhere. |
| `seed_stability_gate` | HIGH | Model coefficient disclosure remark from another paper. |
| `leakage_gate` | HIGH | Clinical-notes annotation timing from a COVID ACU paper. |
| `evaluation_quality_gate` | HIGH | Diuretics / ICU / albumin feature shift from another paper. |
| `sample_size_gate` | HIGH | "Only 11-17 hard deterioration events" — different study. |
| `generalization_gap_gate` | HIGH | Guideline-method comparison bias from another paper. |

The CRITICAL over-flag is a precision-killing failure mode: a flag
labelled CRITICAL with split_protocol_gate evidence text appears in
the run output, but the evidence text is from a different paper
entirely. A downstream reader scanning only severity labels would
mis-attribute a CRITICAL split-leak to PR-EXP-0212, which has no such
issue. This is the same pattern W23-B3 lineage red-team flagged.

## Narrative

PR-EXP-0212 is a clean test of the W24-17 calibration / fairness
hypothesis and the result is a **structural finding**: MLGG hits
**100% recall on HIGH-severity concerns** (3/3 — selection-pressure,
model-selection, external-validation) via exact-code routing, and the
post-67f7492 fix is paying off everywhere it can. The headline
disappointment is **calibration_dca_gate did not surface at all** in
the 5-chunk x top_k=20 retrieval, despite being the one gate the
W24-17 brief explicitly asked to probe and being on the ground-truth
concern list (C11). Two diagnoses are plausible: (a) the AKI paper's
Methods section is heavy on transportability-recalibration arithmetic
but light on the "calibration plot / DCA / Brier score" surface
vocabulary that the calibration_dca_gate flag entries use as their
canonical evidence, and the BGE retriever did not bridge that
semantic gap; or (b) the KB-side population of `calibration_dca_gate`
flags is sparse enough that no top-20 slot was carried across any of
the 5 chunks. Either way, the gate-surface coverage is the bottleneck,
not the matcher arithmetic. Weighted F1 of **0.533** is competitive
with the sibling W24 picks (PR-EXP-0110 W24-14 = 0.460, PR-EXP-0095
W24-11 = 0.486) and the headline structural wins are the 100% HIGH
recall and zero LOW-severity recall. Precision is 0.47 — the
now-familiar artefact of `synthesize_flags_from_rag` not filtering
top-20 hits by source paper, with the additional twist this run that
**a CRITICAL-severity over-flag (split_protocol_gate, evidence from
PR-EXP-0110) leaked through** and would mislead any reader scanning
on severity label alone. The actionable W24-17-specific finding is
that the W15-A3 calibration_dca_gate gate is detector-blind on at
least one ground-truth-tagged paper: the gate fires elsewhere (FP-side
in PR-EXP-0110's own run) but not on the AKI paper whose reviewer
explicitly flagged it. That is exactly the "gate that doesn't fire
when it should" failure mode the gate was designed to prevent.
