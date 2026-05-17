# W24-11 Case Study — PR-EXP-0095

**Picked by W24-11 with reason:** Among Nature Communications papers with
>=10 reviewer concerns and >=1 CRITICAL/HIGH severity concern, after removing
the W24-01..10 and W24-12..21 reserved IDs, only six candidates remained
(`PR-RO-07`, `PR-EXP-0085`, `PR-EXP-0095`, `PR-EXP-0106`, `PR-EXP-0110`,
`PR-EXP-0212`). None of them carry a populated `key_methodology_issues`
list — the field is `None` (or `[]` for PR-RO-07) for every survivor of the
exclusion set, so the criterion was relaxed to "methodology issues
derivable from `reviewer_concerns[*].mlgg_gates`" (all six have non-empty
gate tags across their concerns). Deterministic tie-break via
`sha256("W24-11" + paper_id)` with ascending sort selected
**PR-EXP-0095** (seed prefix `1734708ad6967c4c`). The query was synthesized
from the paper title plus the seven reviewer concern categories plus the
concern texts, since the canonical `key_methodology_issues` field was
unavailable.

## Paper meta

| Field | Value |
|---|---|
| Paper ID | `PR-EXP-0095` |
| Title | Vision transformer-based model can optimize curative-intent treatment for patients with recurrent hepatocellular carcinoma |
| DOI | `10.1038/s41467-025-59197-0` |
| Journal | Nature Communications |
| Prediction task | Clinical prediction modeling with machine learning (Nature Comm 2025) |
| Data type | clinical_tabular (as tagged in KB; substantively multimodal imaging — T2w / DWI / CEUS) |
| Review rounds | 3 |
| Reviewer concerns | 12 (2 CRITICAL, 5 HIGH, 5 MEDIUM) |
| Categories present | study_design, external_validation, evaluation_metrics, feature_selection, interpretability, preprocessing, reporting |

## Match summary

Pipeline: `rag_query(top_k=20)` -> `synthesize_flags_from_rag` (post
67f7492 fix; uses `mlgg_gates[0]` rather than `concern_id`) ->
`ncpr_matcher.match_all(embed_fn=None)` ->
`ncpr_severity_score.per_paper_score`.

| Metric | Value |
|---|---|
| MLGG flags synthesized | 20 |
| Reviewer concerns | 12 |
| Matched pairs | 5 |
| Unmatched flags (over-flags / FP) | 15 |
| Unmatched concerns (misses / FN) | 7 |
| Weighted TP / FN / FP | 13.0 / 10.0 / 17.5 |
| Weighted precision | 0.426 |
| Weighted recall | 0.565 |
| Weighted F1 | **0.486** |
| Matcher reported | `unknown` (real `match_all` invoked; no `matcher` key set in result dict) |

Per-severity breakdown (matched / missed / extra_flags):

| Severity | Matched | Missed | Extra flags |
|---|---|---|---|
| CRITICAL | 2 | 0 | 3 |
| HIGH | 2 | 3 | 11 |
| MEDIUM | 1 | 4 | 1 |
| LOW | 0 | 0 | 0 |

CRITICAL recall is 2/2 = 100%; HIGH recall is 2/5 = 40%; MEDIUM recall is
1/5 = 20%. All 15 over-flags are from KB hits belonging to *other* papers
that the RAG top-20 retrieval pulled in.

## Matched concerns (5)

| Concern | Severity | Matched flag | Match type | Score |
|---|---|---|---|---|
| C01 observer / technical variability of US & CEUS | MEDIUM | `evaluation_quality_gate` | exact_code | 1.00 |
| C02 development/validation cohort mismatch (non-treated HCC vs rHCC) | CRITICAL | `cohort_definition_gate` | exact_code | 1.00 |
| C03 same-center "external" validation cohort | HIGH | `external_validation_gate` | exact_code | 1.00 |
| C04 missing SOTA ViT multimodal baseline | HIGH | `model_selection_audit_gate` | exact_code | 1.00 |
| C08 algorithm goal mismatch (prognosis vs therapy decision) | CRITICAL | `clinical_metrics_gate` | exact_code | 1.00 |

All five matches are `exact_code` (gate name found in `concern.mlgg_gates`),
so the semantic-similarity pathway was not exercised and `embed_fn=None`
was safe.

## Missed concerns (7)

| Concern | Severity | Why MLGG likely missed |
|---|---|---|
| C05 staging-system bias in guideline-method comparisons | HIGH | Tagged gates include `reporting_bias_gate` + `clinical_metrics_gate`; RAG top-20 surfaced other-paper variants of these but the matcher's flag-to-one-concern de-dup gave the slot to C08 / C01. |
| C06 SAGER sex/gender reporting | MEDIUM | Tagged `fairness_equity_gate`; one over-flag carries this gate but the matcher already routed it to another candidate. |
| C07 statistical test & PSM justification | MEDIUM | Tagged `evaluation_quality_gate`; same de-dup collision as C01. |
| C09 modality choice (T2w / DWI / CEUS only) | HIGH | Tagged `feature_engineering_audit_gate` + `feature_lineage_gate`; not present in top-20 RAG hits. |
| C10 train-on-iHCC / apply-to-rHCC distribution shift | HIGH | Tagged `covariate_shift_gate` + `distribution_generalization_gate`; neither gate appears as a primary flag in this run. |
| C11 hyperparameter optimization & SHAP interpretability detail | MEDIUM | Tagged `shap_interpretability_gate` + `model_selection_audit_gate`; same flag-collision pattern as C04. |
| C12 CEUS clinical applicability (CT is the standard surveillance modality) | MEDIUM | Tagged `external_validation_gate` + `generalization_gap_gate`; lost to C03 under matcher de-dup. |

## Over-flagged (15 FP flags)

Every over-flag is a KB record belonging to *another* paper that the RAG
retrieval ranked into the top 20 because the query embedding is dominated
by generic methodology language. Representative examples:

- `cohort_definition_gate` HIGH -- evidence about "Tri AI-segment / Tri AI-severity / Tri RR" (different paper)
- `cohort_definition_gate` CRITICAL -- H. pylori personalized-treatment model
- `cohort_definition_gate` CRITICAL -- functionally-relevant CAD outcome definition
- `external_validation_gate` HIGH x4 -- single-dataset / single-center papers
- `evaluation_quality_gate` HIGH x4 -- PPV/NPV, CancerSEEK comparison, R^2=0.31 context, variance significance test
- `model_selection_audit_gate` MEDIUM/HIGH x2 -- VGG/ResNet/Inception specifics + CTRCD chemo-onset cohort
- `fairness_equity_gate` HIGH -- skin-color bias in dermatology dataset

Pattern: `synthesize_flags_from_rag` returns one flag per RAG hit and the
RAG ranker has no per-paper filter, so the over-flag rate is structurally
bounded below by `top_k - n_relevant_in_kb_for_this_paper`. For PR-EXP-0095
the KB contains 12 own-paper concerns but only 5 surfaced in top-20.

## Narrative

PR-EXP-0095 is a multimodal-imaging recurrent-HCC paper that the KB
records as `clinical_tabular` — the modality-tag mismatch is itself a
small data-quality signal worth noting, since MLGG's gate inventory is
scoped to retrospective tabular cohorts and so structurally cannot fire
on imaging-specific concerns (C09 modality selection, C11 SHAP for
imaging). The run hits 100% recall on the two CRITICAL concerns, which is
the headline number that matters for fail-closed safety; the gap is at
HIGH (40%) and MEDIUM (20%) where reviewer concerns about
distribution-shift between iHCC and rHCC, modality choice rationale, and
SAGER reporting either land on gates the RAG top-20 did not surface
(`covariate_shift_gate`, `feature_engineering_audit_gate`) or land on
already-claimed gate names that the matcher's flag-to-one-concern de-dup
collapsed. Precision is 0.43 because the runner does not filter RAG hits
by source paper — three quarters of the 20 synthesized flags carry
evidence text from other KB papers entirely. The post-67f7492
`synthesize_flags_from_rag` fix (use `mlgg_gates[0]` rather than
`concern_id`) is doing its job: all five matches resolved via `exact_code`
on the gate name, which would have failed under the old behavior.
