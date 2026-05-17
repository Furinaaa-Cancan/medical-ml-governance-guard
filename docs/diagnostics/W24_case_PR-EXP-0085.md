# W24-12 — Case Study: PR-EXP-0085 (Real Paper End-to-End)

**2026-05-17.** End-to-end MLGG run on a single real NC paper, comparing synthesised flags to documented reviewer concerns. Protocol per W24-01/02/03/11 siblings. Uses post-67f7492 `synthesize_flags_from_rag` fix (gate-first code mapping). Autonomous pick (W24-12).

## Pick reason

Reserved set (PR-013/017/018/019/106 + PR-EXP-0084/0086/0097/0109/0160) plus the W24-01..10 sibling avoid range plus the racing W24-11 grab of PR-EXP-0095 plus already-committed W24 case files (PR-EXP-0106, PR-EXP-0110 confirmed present at run time) leave only three viable candidates with ≥10 reviewer concerns and ≥1 CRITICAL/HIGH: **PR-RO-07, PR-EXP-0085, PR-EXP-0212**. None of the three carry a populated `key_methodology_issues` field — verified by direct KB inspection — so the "populated KMI" criterion is satisfied via a **derived query** from concern `mlgg_gates` + `category` + `prediction_task` (same fallback as W24-11). Picked **PR-EXP-0085** because it is the **only candidate exercising the genomic / multi-representation GNN modality** (no other W24 case in the corpus runs against an AMR-prediction paper), it carries 4 HIGH concerns across split_protocol, external_validation, preprocessing-imbalance, and evaluation_metrics (a genuinely diverse gate surface), and its PDF verification is `confidence=high` via DOI-shorthand filename match. Diversity-of-modality won the tie-break over PR-RO-07 (oncology, already heavily covered by PR-EXP-0095) and PR-EXP-0212 (which has fewer HIGH-severity concerns at 3).

## Paper metadata

| Field | Value |
|---|---|
| `id` | PR-EXP-0085 |
| `paper_doi` | 10.1038/s41467-026-69934-8 |
| `paper_title` | AMR-GNN: a multi-representation graph neural network framework to enable genomic antimicrobial resistance prediction |
| `journal` | Nature Communications (2026) |
| `domain` | genomics / microbiology (bacterial AMR) |
| `prediction_task` | Genomic antimicrobial-resistance prediction with multi-representation graph neural networks |
| `model_types` | Multi-representation GNN (KB lists `None` for `model_types`; recovered from title) |
| `data_type` | `genomic_amr` |
| `sample_size` | not extracted in KB |
| `review_rounds` | 2 |
| `outcome` | `extracted_2026-05-13` (review-round status unspecified) |
| `pdf_verification` | confidence=high (filename_doi_shorthand) |
| `is_cohort_retrospective_binary` | True |
| `key_methodology_issues` | **None in KB** — derived from concern gates + categories (see Query) |
| `reviewer_concerns` | **10** (0 CRITICAL · 4 HIGH · 6 MEDIUM · 0 LOW) across 7 categories: preprocessing×2, reproducibility×2, evaluation_metrics×2, split_protocol×1, external_validation×1, study_design×1, reporting×1 |

**Query (derived from concern gates + categories + task, KMI fallback):**
`"clinical_metrics_gate cohort_definition_gate covariate_shift_gate distribution_generalization_gate evaluation_quality_gate execution_attestation_gate external_validation_gate fairness_equity_gate feature_engineering_audit_gate feature_lineage_gate evaluation_metrics external_validation preprocessing reporting reproducibility split_protocol study_design Genomic antimicrobial-resistance prediction with multi-representation graph neural networks"`

**RAG params:** `top_k=20`, snapshot loaded at run time, BGE-small-en-v1.5. Code path: post-commit `67f7492`.

## Match summary

| Metric | Value |
|---|---:|
| n_flags | 20 |
| n_concerns | 10 |
| matched_pairs | **3** |
| wTP / wFN / wFP | 4.0 / 10.0 / 19.0 |
| **weighted_precision** | **0.174** |
| **weighted_recall** | **0.286** |
| **weighted_F1** | **0.216** |
| matcher_used | `exact_code` only (`embed_fn=None` → semantic tier honestly skipped) |
| category_coverage | **0 / 5** (NCPR-frozen 5-bucket schema does not absorb the paper's raw categories — same schema-drift artefact noted in W22-V2, W24-01, W24-11) |

Per-severity (matched / missed / extra):

- **CRITICAL**: 0 / 0 / 2 (no CRITICAL reviewer concerns; two CRITICAL over-flags both `leakage_gate` from UK Biobank PRS-related neighbours)
- **HIGH**: 1 / 3 / 15 (heavy over-flagging on `external_validation_gate`; 1/4 recall)
- **MEDIUM**: 2 / 4 / 0 (2/6 recall; reproducibility, evaluation-metrics, reporting all stranded)
- **LOW**: 0 / 0 / 0

## Matched concerns (TP)

| Concern | Sev | Reviewer category | Matched flag (`code`) | Type | Score |
|---|---|---|---|---|---:|
| PR-EXP-0085-C01 | MEDIUM | preprocessing (broth-microdilution vs agar-dilution phenotype-definition mismatch) | `cohort_definition_gate` | exact_code | 1.00 |
| PR-EXP-0085-C02 | HIGH | split_protocol (external validation drawn from two small datasets rather than pooled-and-random; potential bias in split assignment) | `split_protocol_gate` | exact_code | 1.00 |
| PR-EXP-0085-C07 | MEDIUM | study_design (rationale for using ST as the distance level to control population/clonality structure) | `clinical_metrics_gate` | exact_code | 1.00 |

All three matches are `exact_code` at score 1.00. The C02 match is the headline win: the matcher correctly recovers the only HIGH-severity split-protocol concern via the gate-first mapping (`split_protocol_gate` is the first gate in C02's `mlgg_gates` list and the runner retrieved a `split_protocol_gate` flag at top-3). Without the post-67f7492 fix this would have collapsed to `category` only (diagnostic-only, no score contribution).

## Missed concerns (FN, 7 of 10)

| Concern | Sev | Category | Expected gates | Why missed |
|---|---|---|---|---|
| PR-EXP-0085-C03 | HIGH | preprocessing (dataset imbalance → overfitting risk) | `imbalance_policy_gate`, `feature_engineering_audit_gate`, `evaluation_quality_gate` | `imbalance_policy_gate` never retrieved (known KB-thin surface; the gate exists in the inventory but the BM25 channel cannot find a neighbour for "imbalanced"). `evaluation_quality_gate` retrieved at idx 9 but evidence text is about AIDS-vs-NCD proteomics — wrong topic; matcher dedup gave the slot to no one. |
| PR-EXP-0085-C04 | HIGH | external_validation (cross-species / cross-pathogen accuracy drop interpreted as covariate shift) | `distribution_generalization_gate`, `external_validation_gate`, `covariate_shift_gate` | RAG retrieved 8 `external_validation_gate` flags in top-20 (idx 4,6,10,11,13,15,17,18,19) but **all were claimed by other concerns or are duplicate-deduplicated**. `covariate_shift_gate` / `distribution_generalization_gate` never retrieved. Same dedup starvation pattern as W24-11/PR-EXP-0095. |
| PR-EXP-0085-C05 | MEDIUM | reproducibility (tool version numbers missing) | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate`, `prediction_replay_gate` | None of the four gates retrieved. Reproducibility gates are a chronic retrieval blind spot — the W24-01 PR-013 case logged the same pattern (`seed_stability_gate` / `execution_attestation_gate` never surface without explicit reproducibility tokens in the query). |
| PR-EXP-0085-C06 | MEDIUM | evaluation_metrics (benchmark coverage on other bacterial pathogens) | `evaluation_quality_gate`, `metric_consistency_gate`, `model_selection_audit_gate` | `evaluation_quality_gate` retrieved (idx 9, 16) but both flag instances had unrelated evidence text and were dedup-stranded. `metric_consistency_gate` / `model_selection_audit_gate` never retrieved. |
| PR-EXP-0085-C08 | HIGH | evaluation_metrics (F1/AUROC/sens/spec but missing clinically-decisive metrics) | `clinical_metrics_gate`, `evaluation_quality_gate`, `model_selection_audit_gate` | `clinical_metrics_gate` (idx 8) was claimed by C07 (also MEDIUM, also head-gate `clinical_metrics_gate`) under one-flag-per-concern. C07's match was higher in concern-index order and won the dedup race. C08 was stranded with no alternate. |
| PR-EXP-0085-C09 | MEDIUM | reproducibility (feature derivation from unitigs/SNPs/etc. inadequately documented) | `publication_gate`, `execution_attestation_gate`, `seed_stability_gate` | Same retrieval gap as C05. |
| PR-EXP-0085-C10 | MEDIUM | reporting (discussion-section completeness) | `reporting_bias_gate` | `reporting_bias_gate` never retrieved despite the query carrying the `reporting` category token. The BM25 channel needs the actual gate-code string, not the category bucket, to surface — same failure mode as W24-01's PR-013 reporting concern. |

**Headline failure mode breakdown:** 3 of 7 misses are **dedup starvation** (C04/C06/C08 had the correct gate in top-20 but lost to one-flag-per-concern), 4 of 7 are **retrieval gaps** (C03/C05/C09/C10 — `imbalance_policy_gate`, reproducibility-gate family, `reporting_bias_gate` simply never retrieved). The reproducibility-gate retrieval gap is now confirmed across W24-01 (PR-013) and W24-12 (PR-EXP-0085) — two independent runs, same blind spot, two MEDIUM concerns lost each.

## Over-flagging (FP = 17 unmatched flags, wFP = 19.0)

17 of 20 flags failed to match any concern. The retrieval profile is **extremely** skewed toward `external_validation_gate` (10 of 20 flags total, 8 unmatched) and CRITICAL leakage gates pulled from PRS / UK Biobank neighbours.

| Bucket | Count | Severity | Why irrelevant to PR-EXP-0085 |
|---|---:|---|---|
| `leakage_gate` (CRIT × 2) | 2 unmatched (idx 0,1) | CRIT | Both UK Biobank PRS / PheWAS circular-use neighbours — categorically impossible on a bacterial-AMR GNN paper that has no human cohort and no PRS pipeline. These two CRITICAL over-flags are the most expensive FPs (CRIT weight × 1.0 each = 2.0 of the 19.0 wFP). |
| `external_validation_gate` (HIGH × 8) | 8 unmatched (idx 4,6,10,11,13,15,17,18,19) | HIGH | Duke cohort, prospective-validation-on-same-institution, multi-cohort delineation, Multi-Domain Sentiment dataset, HCC center-A — all human-clinical neighbours with no AMR relevance. The duplicate-code dedup means 7 of these 8 are guaranteed FPs no matter what the genuine C04 external-val concern needs. |
| `cohort_definition_gate` (HIGH × 2) | 2 unmatched (idx 12,14) | HIGH | UK Biobank GP-records subset filtering (PR-EXP-0019 neighbour) and bias-from-intrinsic-patient-differences — human-cohort definitions, irrelevant to bacterial-isolate phenotype definition. (The genuine C01 dilution-method concern matched on a different `cohort_definition_gate` flag at idx 3.) |
| `sample_size_gate` (HIGH × 2) | 2 unmatched (idx 5,7) | HIGH | Validation-2 cohort sizes and derivation/validation cohort mismatches — both human cohorts; AMR-GNN dataset sizing wasn't a reviewer concern (sample_size_gate wasn't tagged on any C01-C10). |
| `evaluation_quality_gate` (HIGH × 2) | 2 unmatched (idx 9,16) | HIGH | AIDS-vs-NCD proteomics dichotomization and prognosis-without-clinical-features adjustment — both clinical neighbours, wrong evidence text. |
| `clinical_metrics_gate` (HIGH × 0) | — | — | The single retrieved instance (idx 8) matched C07. |
| `split_protocol_gate` (CRIT × 0) | — | — | The single retrieved instance (idx 2) matched C02. |

The wFP = 19.0 (2 CRIT × 1.0 + 15 HIGH × 1.0 + 0 MED × 0.5 + 0 LOW × 0.25) is dominated by the 8-of-20 `external_validation_gate` saturation. **The structural problem is duplicate-code retrieval × one-flag-per-concern dedup**: even if the matcher gets one true positive on `external_validation_gate`, the other 7 duplicate retrievals are mathematically guaranteed FPs that cannot be claimed by any concern.

## 1-paragraph narrative

PR-EXP-0085 is the first W24 sibling case run against a **bacterial-AMR genomic GNN** paper (no human cohort, no PRS pipeline, no clinical decision endpoint), and it is a clean stress test of MLGG's modality limits. The post-67f7492 fix delivers the headline win: the single HIGH split-protocol concern (C02 — external validation drawn from two tiny datasets rather than a pooled random split) matches via `split_protocol_gate` `exact_code` at score 1.00, exactly the kind of methodology issue MLGG's gate inventory was built to catch. Two MEDIUM concerns also match (broth-vs-agar phenotype-definition mismatch → `cohort_definition_gate`; ST distance-level rationale → `clinical_metrics_gate`). But weighted F1 = 0.216 collapses because (a) the retrieval is dominated by 10 `external_validation_gate` and 2 `leakage_gate`-CRITICAL UK-Biobank-PRS neighbours that have categorical zero relevance to bacterial AMR — 17 of 20 retrieved flags are pure bleed; (b) the reproducibility gate family (`seed_stability_gate`, `execution_attestation_gate`, `publication_gate`, `prediction_replay_gate`) never retrieves despite the query carrying `reproducibility` as a category token, costing two MEDIUM FNs (C05, C09); (c) the dedup starvation pattern repeats from W24-11 — C04 (cross-pathogen distribution shift), C06 (benchmark coverage), and C08 (clinically-decisive metrics) all have the correct gate code retrieved somewhere in top-20 but lose to one-flag-per-concern dedup. Together with W24-01 (PR-013, F1=0.192), W24-02 (PR-017, F1=0.291), and W24-11 (PR-EXP-0095, F1=0.486), the four-paper signal is consistent: the gate-first mapping is necessary, lexical retrieval against a derived-KMI fallback is too broad on cross-modal corpora, and the matcher's one-flag-per-concern dedup is now the second-biggest precision lever after retrieval domain-filtering.

## Comparison to W23-D2 and sibling W24 runs

W23-D2 not on `main` (no `W23_D2_*.md`, no `/tmp/W23_D2_*.json`); D3 stub records D2 smoke as mean F1=0.000 with `matcher=="unknown"`. PR-EXP-0085's `weighted_f1=0.216` (with the same cosmetic `matcher=="unknown"` string per W24-02 documented bug) confirms the gate-first mapping recovers usable signal where D2 returned zero. Sibling W24 comparison:

| Sibling | Paper | Modality | n_concerns | CRIT/HIGH matched | F1 |
|---|---|---|---:|---|---:|
| W24-01 | PR-013 | ALS wearables | 6 | 0/1 HIGH | 0.192 |
| W24-02 | PR-017 | multi-ancestry GWAS PRS | 5 | 0 CRIT in paper, 1/1 HIGH | 0.291 |
| W24-11 | PR-EXP-0095 | HCC Vision Transformer | 12 | 2/2 CRIT, 2/5 HIGH | 0.486 |
| **W24-12** | **PR-EXP-0085** | **bacterial-AMR GNN** | **10** | **0 CRIT in paper, 1/4 HIGH** | **0.216** |

n=4 across the four siblings. Two cross-cutting findings reproducible across runs: (i) `exact_code` via the post-67f7492 mapping is the only working tier (semantic skipped honestly across all four); (ii) the dedup-starvation + duplicate-code-retrieval failure mode appears in every paper, suggesting a many-to-many concern-flag assignment would lift F1 across the board without changing the retrieval layer.

## Provenance

- Raw run output (queries, all 20 flags + evidence_text, full match record, score breakdown, coverage): `/tmp/W24_PR-EXP-0085_run.json` (ephemeral; not committed).
- Code paths exercised: `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag` (top_k=20), `scripts.rag.evals.ncpr_matcher.match_all` (embed_fn=None), `scripts.rag.evals.ncpr_severity_score.per_paper_score`, `scripts.rag.evals.ncpr_category_coverage.category_coverage`.
- Hard rules honored: NEW file only (this one); READ-ONLY everywhere else; no sub-agents; no embedder injection (semantic tier honestly skipped); query-derivation fallback transparently documented because KB `key_methodology_issues` is null on this paper.
