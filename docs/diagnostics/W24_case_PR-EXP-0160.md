# W24-07 — Case Study: PR-EXP-0160 (Real Paper End-to-End)

**2026-05-17.** End-to-end MLGG run on a single real Nature Communications paper, comparing synthesised flags to documented reviewer concerns. Protocol per W24-01/02 siblings. Uses post-67f7492 `synthesize_flags_from_rag` fix (gate-first code mapping).

## Paper metadata

| Field | Value |
|---|---|
| `id` | PR-EXP-0160 |
| `paper_doi` | 10.1038/s41467-020-20816-7 |
| `paper_title` | Real-time prediction of COVID-19 related mortality using electronic health records |
| `journal` | Nature Communications (2021) |
| `prediction_task` | Real-time COVID-19 mortality prediction from electronic health records |
| `data_type` | ehr_time_series |
| `model_types` | (not extracted; CovEWS = recurrent neural network per concerns) |
| `sample_size` | (not extracted; Optum dev ≈ 47,393; TriNetX external ≈ 5,005) |
| `review_rounds` | 3 |
| `outcome` | extracted_2026-05-13 (accepted) |
| `key_methodology_issues` | (not populated in KB; query falls back to `prediction_task` + concern-text prefixes per W22-V2) |
| `reviewer_concerns` | **15** (0 CRITICAL, 9 HIGH, 6 MEDIUM) — top quality |

**Query (fallback policy, B1 unavailable):** `prediction_task` + first ~140 chars of each of 15 concern texts → 2,215 chars total. The KB entry has `key_methodology_issues=None` (extraction-wave `2026-05-13` predates the issue-tag pass); fallback matches W22-V2 §"unexpected behaviour" caveat — expect upward-biased precision because query terms overlap concern terms.
**RAG params:** `top_k=20`, BGE-small-en-v1.5, snapshot loaded at run time.

## Match summary

| Metric | Value |
|---|---|
| n_flags | 20 |
| n_concerns | 15 |
| matched_pairs | 7 |
| wTP / wFN / wFP | 11.0 / 13.0 / 14.0 |
| **weighted_precision** | **0.440** |
| **weighted_recall** | **0.458** |
| **weighted_F1** | **0.449** |
| category_coverage | 4 / 8 (study_design, evaluation_metrics, clinical_utility, external_validation covered; preprocessing, model_selection, feature_selection, interpretability missed) |

Per-severity (matched / missed / extra):
- CRITICAL: 0 / 0 / 1 (paper has zero CRITICAL concerns; one CRIT `cohort_definition_gate` flag is pure noise)
- HIGH: 4 / 5 / 12
- MEDIUM: 3 / 3 / 0
- LOW: 0 / 0 / 0

## Matched concerns

| Concern | Sev | Category | Matched flag (`code`) | Type | Score |
|---|---|---|---|---|---|
| PR-EXP-0160-C01 | HIGH | study_design | `cohort_definition_gate` | exact_code | 1.00 |
| PR-EXP-0160-C02 | HIGH | external_validation | `external_validation_gate` | exact_code | 1.00 |
| PR-EXP-0160-C03 | MEDIUM | clinical_utility | `clinical_metrics_gate` | exact_code | 1.00 |
| PR-EXP-0160-C04 | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | exact_code | 1.00 |
| PR-EXP-0160-C07 | HIGH | external_validation | `reporting_bias_gate` | exact_code | 1.00 |
| PR-EXP-0160-C09 | MEDIUM | study_design | `split_protocol_gate` | exact_code | 1.00 |
| PR-EXP-0160-C11 | HIGH | feature_selection | `leakage_gate` | exact_code | 1.00 |

All seven matches are gate-code exact hits (post-67f7492 gate-first mapping working); no semantic-only matches were needed.

## Missed concerns (FN = 8)

| Concern | Sev | Category | Expected gates (first listed) | Why missed |
|---|---|---|---|---|
| PR-EXP-0160-C05 | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | Gate retrieved (flag idx 5) but already best-matched to C04. Matcher's one-flag-per-concern de-dup orphans C05; no second `evaluation_quality_gate` neighbour available. |
| PR-EXP-0160-C06 | HIGH | preprocessing | `fairness_equity_gate`, `missingness_policy_gate` | Neither `missingness_policy_gate` nor `feature_engineering_audit_gate` appears in the top-20 hits. The missingness/MICE thread (Reviewer #2's persistent concern across 3 rounds) has no retrieval anchor. |
| PR-EXP-0160-C08 | HIGH | model_selection | `model_selection_audit_gate`, `generalization_gap_gate` | No `model_selection_audit_gate` retrieved despite being a HIGH-severity gate in the KB. Query term "baseline" did not surface the comparator-retraining concern. |
| PR-EXP-0160-C10 | MEDIUM | interpretability | `shap_interpretability_gate` | No `shap_interpretability_gate` hit. KB-gap commit c6e755a added 4 entries, but Integrated-Gradients / threshold-extraction phrasing did not match. |
| PR-EXP-0160-C12 | HIGH | study_design | `cohort_definition_gate`, `feature_lineage_gate` | `cohort_definition_gate` flags exist (idx 0,3,6,11) but C01 won the de-dup at score 1.00; no `feature_lineage_gate` retrieved for the outcome-ascertainment angle. |
| PR-EXP-0160-C13 | HIGH | external_validation | `external_validation_gate`, `generalization_gap_gate` | `external_validation_gate` exists (idx 4,8,12) but C02 won de-dup; `generalization_gap_gate` not in top-20 — prospective-evaluation framing isn't lexically close to retrieved snippets. |
| PR-EXP-0160-C14 | HIGH | preprocessing | `missingness_policy_gate` | Same `missingness_policy_gate` gap as C06 — round-2 reiteration of the same thread, equally invisible to retrieval. |
| PR-EXP-0160-C15 | MEDIUM | evaluation_metrics | `evaluation_quality_gate`, `metric_consistency_gate` | `evaluation_quality_gate` consumed by C04; no `metric_consistency_gate` retrieved. The chi-squared p-value disagreement is reasoning the matcher can't reach from gate codes. |

Three distinct failure modes: (i) gate present but de-dup orphan (C05, C12, C13, C15), (ii) gate absent from top-20 (C06, C08, C10, C14, C13/C12 secondary gates), (iii) compound: both (C13).

## Over-flagging (FP = 13)

13 of 20 flags failed to match any concern. Dominant pattern: HIGH/CRITICAL gates retrieved from tabular-cohort neighbours bleed in because the EHR query overlaps lexically with sepsis/ICU/deterioration concerns the KB is dense in.

| Bucket | Count | Notes |
|---|---|---|
| `cohort_definition_gate` (HIGH) | 6 | redundant duplicates of the C01-winning gate (acute-care window, gold-standard absence, ICI cohorts, eradication ground truth, treatment-recommended survival) |
| `external_validation_gate` (HIGH) | 4 | redundant duplicates of C02-winning gate (generalizability, SepsisFormer prospective, plus two others) |
| `cohort_definition_gate` (CRITICAL) | 1 | "real-world vs simulated data" — categorically inapplicable to CovEWS (uses actual EHR); pure noise, single CRITICAL FP |
| `sample_size_gate` (HIGH) | 1 | "11–17 hard deterioration events" — wrong paper; CovEWS Optum cohort is 47k |
| `evaluation_quality_gate` (HIGH) | 1 | AUC-only critique — redundant with C04-winning gate |

The matcher's one-flag-per-concern rule means duplicates of *already-matched* gates (10 of the 13 FPs) inflate FP without any chance of contributing to TP. This is a structural pen tax on a paper whose 15 concerns concentrate in the same 4 gate codes that retrieval saturates on.

## Narrative

PR-EXP-0160 is the upper-end of NCPR difficulty: 15 reviewer concerns across 3 rounds, dominated by Reviewer #2's persistent missingness/MICE thread that the paper never formally resolves. Against this, post-67f7492 RAG produces a respectably balanced result (`weighted_f1=0.449`, precision 0.44, recall 0.46) — meaningfully above the W23-D2 smoke baseline (`0.000`, `matcher==unknown`) and competitive with W24-02 PR-017's `0.291`. All seven matches resolve via `exact_code` at score 1.00, confirming the gate-first mapping carries the run. The failure modes are diagnostic, not pathological. **First**, retrieval saturation: 10 of 13 FPs are redundant `cohort_definition_gate` / `external_validation_gate` / `evaluation_quality_gate` flags duplicating gates that already won their concern — the top-20 budget is spent on near-duplicates instead of the 4 gates the paper actually needs (`missingness_policy_gate`, `model_selection_audit_gate`, `shap_interpretability_gate`, `generalization_gap_gate`). **Second**, the matcher's one-flag-per-concern de-dup correctly avoids inflating recall but turns four concerns into structural FNs (C05/C12/C13/C15) the moment their gate was first claimed elsewhere — a per-concern threshold + per-gate cap would recover them. **Third**, the missingness thread (C06/C14, two HIGH concerns the reviewer fought for 3 rounds) is invisible to BGE because the `missingness_policy_gate` KB anchor is lexically distant from "99% missing hs-CRP" / "MICE not valid here" surface tokens — a category-coverage gap, not a matcher gap. Category coverage 4/8 (50%) confirms: the failure is breadth on the preprocessing / model-selection / interpretability axes, not depth on the gates retrieval *does* reach. Modality-agnostic but concern-aware query expansion (anchor on each `mlgg_gates[0]` per concern, not just the joined concern text) would likely lift recall past 0.7 without precision regression on this paper.
