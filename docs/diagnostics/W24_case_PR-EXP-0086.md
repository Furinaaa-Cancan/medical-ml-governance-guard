# W24-08 Case: PR-EXP-0086 — Real-paper Run

Run of the post-67f7492 NCPR pipeline against a single real paper from
`references/case-studies/peer-review-kb.json`. RAG-only path
(`synthesize_flags_from_rag`, top_k=20) → `ncpr_matcher.match_all`
(lexical only, no embed) → `ncpr_severity_score.per_paper_score` →
`ncpr_paper_card.make_paper_card`.

## Paper meta

| Field | Value |
|---|---|
| paper_id | `PR-EXP-0086` |
| DOI | `10.1038/s41467-026-72347-2` |
| Title | Graph augmented transformers improve chemotherapy toxicity symptom extraction from clinical notes |
| Journal / year | Nature Communications, 2026 |
| Data type | `clinical_notes_nlp` (NLP on clinical notes; somewhat outside the EHR-tabular MLGG core scope, see `_extraction_notes`) |
| Prediction task | Chemotherapy-toxicity symptom extraction via graph-augmented transformers |
| Sample size | 1,753 patients |
| Review rounds | 2 (5 reviewers) |
| Reviewer concerns | 14 (extracted 2026-05-13, `strict_in_scope`) |
| Query source | `prediction_task` + all 14 `concern_text` fields (the entry has no `key_methodology_issues` field; concerns are the closest in-KB proxy for the methods narrative). Query length ≈ 4.96 KB. |

## Match summary

Two metric families are reported. The weighted scores come straight
from `per_paper_score` (severity-weighted). The count-based row is the
unweighted pair-level view (matched concerns ÷ total, etc.) and is
shown alongside because the weighted view conflates severity weights
with pure retrieval performance.

| Metric | Weighted (per_paper_score) | Count-based |
|---|---|---|
| F1 | **0.386** | 0.353 |
| Precision | 0.333 | 0.300 |
| Recall | 0.457 | 0.429 |
| Matched concerns | — | **6 / 14** |
| Matched flags | — | **6 / 20** |
| `paper_excluded` | false | — |
| Matcher tier used | `exact_code` for all 6 pairs (embed_fn=None, so `semantic` was skipped by design) |

Severity breakdown (from `per_paper_score.per_severity`):

| Severity | matched | missed | extra flags |
|---|---|---|---|
| CRITICAL | 0 | 0 | 2 |
| HIGH | 2 | 2 | 12 |
| MEDIUM | 4 | 5 | 0 |
| LOW | 0 | 1 | 0 |

Category coverage: **4 / 8 = 50%**.
- Hit: `evaluation_metrics`, `external_validation`, `model_selection`, `study_design`.
- Missed entirely: `data_leakage`, `interpretability`, `reporting`, `reproducibility`.

## Matched (6)

All matches landed on the matcher's `exact_code` tier (the reviewer
pre-tagged `mlgg_gates[0]` lined up with the flag's `code` field after
the W23 finding #1 fix in 67f7492). Concern severity vs. flag severity
sometimes diverges because the KB stores reviewer-judged severity
while the RAG records carry the pre-curated gate severity.

| Concern | Concern cat / sev | Matched flag code | Flag sev | Tier |
|---|---|---|---|---|
| C01 | study_design / MEDIUM | `cohort_definition_gate` | CRITICAL | exact_code |
| C02 | external_validation / MEDIUM | `external_validation_gate` | CRITICAL | exact_code |
| C04 | evaluation_metrics / HIGH | `evaluation_quality_gate` | HIGH | exact_code |
| C05 | model_selection / MEDIUM | `model_selection_audit_gate` | HIGH | exact_code |
| C06 | external_validation / HIGH | `generalization_gap_gate` | HIGH | exact_code |
| C07 | evaluation_metrics / MEDIUM | `clinical_metrics_gate` | HIGH | exact_code |

## Missed (8)

| Concern | Cat / Sev | Pre-tagged gates | Why missed |
|---|---|---|---|
| C03 | study_design / MEDIUM | `cohort_definition_gate` | RAG returned only one `cohort_definition_gate` record (matched to C01); de-duped against C03. |
| C08 | model_selection / LOW | `model_selection_audit_gate` | Same gate already paired with C05; matcher is 1-to-1 on concern side. |
| C09 | reproducibility / MEDIUM | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate`, `model_selection_audit_gate` | No flag emitted for any reproducibility-family gate. Category dropped entirely. |
| C10 | interpretability / MEDIUM | `fairness_equity_gate`, `shap_interpretability_gate`, `robustness_gate` | None of these three gates appeared in the top-20 RAG hits. Category dropped entirely. |
| C11 | study_design / HIGH | `cohort_definition_gate` | Same gate-name collision as C03. |
| **C12** | **data_leakage / HIGH** | `leakage_gate`, `feature_lineage_gate` | **No leakage-family flag retrieved**, despite this being the most methodologically important concern in the paper (Reviewer #6: training labels derived before t_1 but the claimed objective is prospective ACU prediction after t_1 — classic target leakage). Category dropped entirely. |
| C13 | reporting / MEDIUM | `reporting_bias_gate`, `cohort_definition_gate`, `feature_lineage_gate` | `reporting_bias_gate` / `feature_lineage_gate` absent from RAG output; `cohort_definition_gate` consumed by C01. |
| C14 | model_selection / MEDIUM | `model_selection_audit_gate`, `tuning_leakage_gate`, `feature_engineering_audit_gate` | Same `model_selection_audit_gate` collision as C05/C08; tuning_leakage_gate and feature_engineering_audit_gate not retrieved. |

## Over-flags (14)

All 14 unmatched flags carry evidence text from *other* papers in the
KB — the side-effect of querying with raw concern text against the
shared per-concern RAG index. They cluster into four gate families:

- `cohort_definition_gate` × 7 (2 CRITICAL, 5 HIGH) — most over-flagged gate; the one match was already claimed by C01, so the remaining 7 hits land as over-flags.
- `sample_size_gate` × 3 (HIGH) — no concern carries this gate.
- `external_validation_gate` × 2 (HIGH) — extras after C02 absorbed the first hit.
- `evaluation_quality_gate` × 2 (HIGH).

## Narrative

PR-EXP-0086 lands at weighted F1 ≈ 0.39 / count F1 ≈ 0.35, with the
matcher recovering 6 of 14 concerns and 6 of 20 emitted flags. Every
match fired on the lexical `exact_code` tier, confirming that the W23
finding #1 fix in 67f7492 (prefer `mlgg_gates[0]` over `concern_id`) is
doing structural work for the real-paper case rather than collapsing
all signal to semantic. The two failure modes are clear and
complementary: (a) **gate-family blind spots** — the RAG output does
not surface any `leakage_gate`, `feature_lineage_gate`,
`shap_interpretability_gate`, `fairness_equity_gate`,
`seed_stability_gate`, or reproducibility-family flag for this paper,
which drops four whole concern categories including the
methodologically pivotal data-leakage concern C12 (training labels
derived before t_1 used for a prospective post-t_1 prediction
objective); and (b) **1-to-1 matcher collisions** — 4 of the 8 misses
(C03/C08/C11/C14) share a pre-tagged gate name with an already-paired
concern, so even a perfectly retrieved gate cannot rescue them under
the current bipartite matching. The 14 over-flags are all leakage from
the cross-paper RAG index (other papers' concerns under the same gate
name), which inflates the FP count without indicating real false
positives on the paper's methods text. Two concrete follow-ups suggest
themselves: route the matcher to allow many-to-one concern-side
pairings when gates collide, and audit why leakage/lineage gates
returned zero hits for a paper whose senior reviewer flagged textbook
target leakage.
