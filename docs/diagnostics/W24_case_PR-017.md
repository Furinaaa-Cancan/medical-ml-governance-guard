# W24-02 — Case Study: PR-017 (Real Paper End-to-End)

**2026-05-17.** End-to-end MLGG run on a single real NC paper, comparing synthesised flags to documented reviewer concerns. Protocol per W24-01 sibling. Uses post-67f7492 `synthesize_flags_from_rag` fix (gate-first code mapping).

## Paper metadata

| Field | Value |
|---|---|
| `id` | PR-017 |
| `paper_doi` | 10.1038/s41467-024-47357-7 |
| `paper_title` | An ensemble penalized regression method for multi-ancestry polygenic risk prediction |
| `journal` | Nature Communications (2024) |
| `domain` | genomics |
| `prediction_task` | Multi-ancestry polygenic risk prediction (PROSPER) |
| `model_types` | penalized_regression, lasso, ridge, super_learner |
| `data_type` | gwas_summary_statistics |
| `sample_size` | 500,000 |
| `outcome` | accepted_after_major_revision |
| `key_methodology_issues` | ablation_needed; cross_ancestry_assumption; competitor_suboptimal_settings |
| `reviewer_concerns` | 5 (1 HIGH, 4 MEDIUM) |

**Query (B1 preference):** `key_methodology_issues` concat → `"ablation_needed; cross_ancestry_assumption; competitor_suboptimal_settings"`.
**RAG params:** `top_k=20`, snapshot loaded at run time, BGE-small-en-v1.5.

## Match summary

| Metric | Value |
|---|---|
| n_flags | 20 |
| n_concerns | 5 |
| matched_pairs | 3 |
| wTP / wFN / wFP | 4.0 / 2.0 / 17.5 |
| **weighted_precision** | **0.186** |
| **weighted_recall** | **0.667** |
| **weighted_F1** | **0.291** |
| category_coverage | 3 / 5 (model_selection, study_design, evaluation_metrics covered; preprocessing, reproducibility missed) |

Per-severity (matched / missed / extra):
- CRITICAL: 0 / 0 / 2 (pure noise — paper has zero CRITICAL concerns)
- HIGH: 1 / 0 / 12
- MEDIUM: 2 / 2 / 3
- LOW: 0 / 0 / 0

## Matched concerns

| Concern | Sev | Category | Matched flag (`code`) | Type | Score |
|---|---|---|---|---|---|
| PR-017-C01 | HIGH | model_selection | `model_selection_audit_gate` | exact_code | 1.00 |
| PR-017-C02 | MEDIUM | study_design | `cohort_definition_gate` | exact_code | 1.00 |
| PR-017-C05 | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | exact_code | 1.00 |

All three matches are gate-code exact hits — the post-67f7492 mapping is working as intended. No semantic-only matches were needed.

## Missed concerns (FN)

| Concern | Sev | Category | Expected gates | Why missed |
|---|---|---|---|---|
| PR-017-C03 | MEDIUM | preprocessing | `feature_engineering_audit_gate`, `fairness_equity_gate`, `external_validation_gate` | RAG returned `fairness_equity_gate` and `external_validation_gate` flags (idx 8,9,10,11,18) but each was already best-matched to other concerns or other flags out-ranked them on C03 — matcher's one-flag-per-concern de-dup drops them. No `feature_engineering_audit_gate` retrieved at all. |
| PR-017-C04 | MEDIUM | reproducibility | `seed_stability_gate`, `execution_attestation_gate` | Neither gate appears in the top-20 RAG hits. Query carries no reproducibility signal (`ablation_needed` / `cross_ancestry_assumption` / `competitor_suboptimal_settings` are all non-repro categories), so retrieval can't surface it. |

## Over-flagging (FP = 17)

17 of 20 flags failed to match any concern. Dominant noise pattern: HIGH-severity gates from off-topic neighbours bleed in via the methodology-issue query.

| Bucket | Count | Examples |
|---|---|---|
| `external_validation_gate` (HIGH) | 4 | UKB kinship inflation; AFR transferability; same-cohort training; PCa multi-center |
| `cohort_definition_gate` (CRIT/HIGH) | 4 | local-therapy decision (CRIT); skin-cancer age (HIGH); ICI-mono vs ICI-chemo (HIGH); eradication ground truth (HIGH) |
| `split_protocol_gate` (CRIT/HIGH) | 3 | AI-EF leak (CRIT); CV/holdout clarity; DILImap CV scope |
| `fairness_equity_gate` (HIGH) | 2 | demographics gap; missing hs-CRP |
| `evaluation_quality_gate` (MED/HIGH) | 2 | 10-fold averaging; Orpheus cutoff |
| `model_selection_audit_gate` (MED) | 1 | graph-model ablation |
| `ci_matrix_gate` (MED) | 1 | overlapping CIs |

The two CRITICAL over-flags (`split_protocol_gate`, `cohort_definition_gate`) are the most damaging — both are leakage gates that wouldn't fire on a GWAS summary-statistics PRS paper (no patient-level splits, no cohort to define). They are pure retrieval bleed.

## Narrative

PR-017 is a stress test for the post-67f7492 gate-first mapping on a paper whose review revolves around method comparison and cross-ancestry assumptions, not the tabular-cohort leakage modes MLGG was built for. The fix earns its keep: all three matched concerns resolved via `exact_code` at score 1.00, including the headline HIGH (ablation/super-learner attribution → `model_selection_audit_gate`). Recall (0.67) is healthier than the W23-D2 smoke baseline (0.000 with `matcher==unknown`). But precision collapses to 0.19: 17 of 20 retrieved KB neighbours are tabular-cohort concerns (CAD, ICI, PCa, DILImap, skin-cancer age) whose gates fire on a GWAS PRS paper they have no business touching, including two CRITICAL leakage flags that the paper's design (GWAS summary stats, no patient splits) categorically excludes. Two MEDIUM concerns are missed: the reproducibility one (PR-017-C04, code availability for LDpred2) has no signal in the query and no `seed_stability_gate` / `execution_attestation_gate` neighbour was retrieved; the preprocessing one (PR-017-C03, LD reference panel choice) is starved by matcher de-dup after stronger flags claim adjacent gates first. Category coverage 3/5 confirms the failure mode is breadth, not depth — modality-aware query rewriting or a genomics retrieval filter would buy more than tuning the matcher threshold.

## Compare to W23-D2

No `W23_D2_*.md` file exists in `docs/diagnostics/`; W23-D5 records D2 smoke (n=5) as **mean=median=0.000, `matcher=="unknown"`** — matcher unwired. PR-017's `weighted_f1=0.291` with `matcher` field still `"unknown"` (the runtime-resolved matcher is the real `match_all`; the score record's `matcher` string is a known cosmetic bug) demonstrates that the post-67f7492 gate-first mapping recovers usable recall on a real paper where D2 returned zero. n=1 — not a benchmark, an existence proof.
