# W24-03 Case Study: PR-018 (real Nature Communications paper)

End-to-end MLGG run on a published peer-review case from
`references/case-studies/peer-review-kb.json`, following the W24-01
protocol (PDF-less variant: query synthesized from the KB entry's
`paper_title`, `prediction_task`, and `key_methodology_issues`).
The post-67f7492 `synthesize_flags_from_rag` fix is in force
(uses `mlgg_gates[0]` instead of `concern_id` for flag codes).

## Paper meta

| Field | Value |
|---|---|
| Paper ID | PR-018 |
| DOI | 10.1038/s41467-023-44009-0 |
| Title | Tuning parameters for polygenic risk score methods using GWAS summary statistics from training data |
| Journal | Nature Communications (2023) |
| Domain | genomics (PRS / GWAS summary stats) |
| Prediction task | PRS parameter tuning without external validation data (PRStuning method) |
| Sample size | 400,000 (UKB-scale) |
| Reviewer concerns | 5 (1 HIGH, 4 MEDIUM) — all resolved across 2 rounds |
| `key_methodology_issues` (query seed) | `overfitting_concern`, `european_only`, `traditional_method_comparison` |
| MLGG-coverage caveat | Domain (GWAS summary stats / PRS) is **outside** MLGG's declared scope (retrospective EHR/registry cohort, binary classification). Findings below should be read as out-of-distribution stress-test, not pass/fail on the SUT's nominal mandate. |

Query passed to `rag_query` (`top_k=20`):

> Tuning parameters for polygenic risk score methods using GWAS summary statistics from training data. PRS parameter tuning without external validation data (PRStuning method). Key issues: overfitting_concern, european_only, traditional_method_comparison

## Match summary

| Metric | Value |
|---|---|
| Flags synthesized | 20 |
| Reviewer concerns | 5 |
| Matched pairs (all `exact_code`) | 3 |
| Unmatched flags (over-flags / FP) | 17 |
| Unmatched concerns (misses / FN) | 2 |
| Weighted **F1** | **0.288** |
| Weighted precision | 0.184 |
| Weighted recall | 0.667 |
| Category coverage | **3/3** (evaluation_metrics, external_validation, study_design) |
| Matcher | W22-X1 `ncpr_matcher.match_all` (real, not stub) |

Per-severity breakdown:

| Severity | Matched | Missed | Extra flags |
|---|---|---|---|
| CRITICAL | 0 | 0 | 2 |
| HIGH | 1 | 0 | 13 |
| MEDIUM | 2 | 2 | 1 |
| LOW | 0 | 0 | 1 |

## Matched (3)

| Concern | Severity | Matched by gate | Type | Score |
|---|---|---|---|---|
| PR-018-C01 — "AUC pattern across thresholds, overfitting / convergence?" | HIGH | `evaluation_quality_gate` | exact_code | 1.00 |
| PR-018-C03 — HLA region / LD radius definition | MEDIUM | `cohort_definition_gate` | exact_code | 1.00 |
| PR-018-C04 — traditional LDpred2 comparison + compute time | MEDIUM | `external_validation_gate` | exact_code | 1.00 |

## Missed (2)

| Concern | Severity | Why MLGG missed |
|---|---|---|
| PR-018-C02 — covariate-adjusted AUC (age, sex) | MEDIUM | The KB-as-source query retrieved `evaluation_quality_gate` flags pinned to overfitting / metric-panel evidence; no synthesized flag carried evidence about covariate adjustment in AUC computation. Gate signature exists but evidence-text relevance was preempted by stronger overfitting hits. |
| PR-018-C05 — European-only training cohort | MEDIUM | Concern is tagged to `external_validation_gate` + `fairness_equity_gate`; the 5 `external_validation_gate` flags returned all carried tumor-imaging / TriNetX evidence, none referenced ancestry diversity. No `fairness_equity_gate` entry surfaced in top-20 despite `european_only` in the query — KB lacks ancestry-fairness exemplars retrievable from this query text. |

## Over-flags (17)

Concentrated in three buckets:

- **5x `external_validation_gate`** — all from unrelated imaging/oncology
  papers (ADNI clustering, Erlangen breast cancer, TriNetX, "external
  validation in another dataset is strongly encouraged"). None
  specific to PRS or ancestry.
- **4x `evaluation_quality_gate`** + 1 duplicate-of-matched — PPV/NPV,
  C-index parity, diagnostic-system endpoints. Topic drift from PRS
  parameter tuning.
- **2x CRITICAL `leakage_gate`** — one is a true conceptual neighbor
  ("same dataset for both GWAS and PPS parameterisation"); the other
  is UKB phenotype-overlap noise. Neither maps to a concern PR-018's
  reviewers raised (PRStuning's premise is parameter-tuning *without*
  held-out validation, which the reviewers accepted on its merits).
- Singletons: `reporting_bias_gate` (x2), `split_protocol_gate`,
  `generalization_gap_gate`, `sample_size_gate` (x2),
  `model_selection_audit_gate` (x2).

## Narrative

PR-018 is an out-of-modality stress test: MLGG's declared scope is
retrospective binary EHR/registry classification, while this paper
is a PRS-methods contribution on GWAS summary stats. The pipeline
produced a recall of 0.67 with 3/3 category coverage — every
concern category the reviewers raised had at least one matched
flag — but precision collapsed to 0.18 because the RAG retrieval
pulled 17 topic-drifted exemplars from oncology / imaging / EHR
neighbors in the KB. The two misses are both diagnostic of KB
content gaps rather than matcher failure: covariate-adjusted AUC
evidence and ancestry-fairness evidence simply do not appear in
the top-20 hits for this query, even though the gates that would
have caught them (`evaluation_quality_gate`, `fairness_equity_gate`)
are wired up. The 2 CRITICAL `leakage_gate` over-flags are the most
worrying surface: one is a defensible neighbor, but neither is what
the reviewers actually challenged — a downstream consumer treating
these as paper-specific findings would inflate severity inappropriately.

## Compare to W23-D2

W23-D2 (referenced by the protocol) has no diagnostic file in
`docs/diagnostics/` at the time of this run, so no head-to-head
metric comparison is possible. The closest published anchor is the
W23-D5 NCPR v2 report (`docs/diagnostics/W23_D5_ncpr_v2_report.md`)
which framed the macro-level retrieval-vs-pipeline gap audited in
W23-D4. PR-018's profile — high recall, low precision, full
category coverage, severity-misweighted over-flags — is consistent
with the v2 macro picture: the retriever finds the right
neighborhoods, but evidence-text fidelity and out-of-modality
filtering remain the precision-limiting steps. If a true W23-D2
artifact is produced later, this card should be re-cross-referenced.

## Reproducibility

- Run date: 2026-05-17
- Pipeline: `rag_query(top_k=20)` → `synthesize_flags_from_rag`
  (post-67f7492) → `ncpr_matcher.match_all` →
  `ncpr_severity_score.per_paper_score` →
  `ncpr_paper_card.make_paper_card`
- Source entry: `references/case-studies/peer-review-kb.json` →
  `entries[id=PR-018]`
