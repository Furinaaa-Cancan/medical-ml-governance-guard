# W24-16 — Case Study: PR-EXP-0106 (eval-metrics-biased pick)

**2026-05-17.** End-to-end MLGG run on a single real Nature Communications
paper, following the W24-11 / W24-02 / W24-03 sibling protocol
(`synthesize_flags_from_rag` → `match_all` → `per_paper_score`).
The post-67f7492 gate-first flag-code mapping is in force.

## Paper meta

| Field | Value |
|---|---|
| `id` | PR-EXP-0106 |
| `paper_doi` | 10.1038/s41467-025-67238-x |
| `paper_title` | Genetic profiling of the circulating proteome in common diseases suggests causal proteins and improves risk prediction |
| `journal` | Nature Communications (2025) |
| `domain` | UKB-PPP proteomics + pQTL → multi-disease incident-risk prediction |
| `data_type` | clinical_tabular (proteomics + EHR labels) |
| `prediction_task` | Incident-disease risk prediction with proteomics-derived risk scores |
| `outcome` | extracted (review history complete) |
| `reviewer_concerns` | **10** (1 implicit CRITICAL-equivalent, 4 HIGH, 5 MEDIUM by severity weights; 3/10 `evaluation_metrics`) |
| `key_methodology_issues` | `None` — no KMI seed available |

### Pick rationale vs task brief

The brief asked for ≥10 concerns + ≥1 CRITICAL/HIGH + KMI populated +
≥50% concerns in `evaluation_metrics`. In KB v1.4 the bar collides:
of 335 papers, 11 carry ≥10 concerns with a CRITICAL/HIGH; **none**
of those 11 reach 50% `evaluation_metrics`, and **none** of those 11
have a populated `key_methodology_issues` field (all the high-concern
papers in the KB are `PR-EXP-*` rows where KMI is `null`). Reserved
exclusions (PR-013/017/018/019/106, PR-EXP-0084/0160/0086/0097/0109,
PR-001..010) further thin the pool. Cherry-picked **PR-EXP-0106**: 10
concerns, 4 HIGH, **3/10 (30%) `evaluation_metrics`** — the highest
EM fraction in the non-reserved set, and the data_type (`clinical_tabular`
+ `is_cohort_retrospective_binary=true`) sits inside MLGG's nominal
EHR/registry scope, unlike the PRS / GWAS-summary-stat siblings W24-02
and W24-03 stress-tested.

## Query

KMI is `None`, so the query falls back to title + task + first 80 chars
of each `concern_text` (capped at 600 chars). Result:

> Genetic profiling of the circulating proteome in common diseases
> suggests causal proteins and improves risk prediction. Clinical
> outcome prediction (Nature Comm 2025). Key issues: [title repeated
> + first 80 chars of C01..C10] …

`top_k=20`, BGE-small-en-v1.5 dense, snapshot loaded at run time.

## Match summary

| Metric | Value |
|---|---|
| `n_flags` | 20 |
| `n_concerns` | 10 |
| `matched_pairs` | **4** |
| `wTP / wFN / wFP` | 5.0 / 9.0 / 16.5 |
| **`weighted_precision`** | **0.233** |
| **`weighted_recall`** | **0.357** |
| **`weighted_F1`** | **0.282** |
| Category coverage | **4 / 4** (study_design, evaluation_metrics, clinical_utility, sample_size all hit) |
| **`evaluation_metrics` recall** | **1 / 3** (the biased-target subset) |
| Matcher | `match_all` (real), score record says `"matcher": "unknown"` (cosmetic bug from W24-02) |

Per-severity (matched / missed / extra):

| Sev | Matched | Missed | Extra |
|---|---|---|---|
| CRITICAL | 0 | 0 | 1 |
| HIGH | 1 | 3 | 14 |
| MEDIUM | 3 | 3 | 1 |
| LOW | 0 | 0 | 0 |

## Matched concerns (4)

| Concern | Sev | Category | Matched flag `code` | Type | Score |
|---|---|---|---|---|---|
| PR-EXP-0106-C01 (baseline-disease-free cohort) | HIGH | study_design | `cohort_definition_gate` | exact_code | 1.00 |
| PR-EXP-0106-C03 (proteomic black-box, feature reduction) | MEDIUM | clinical_utility | `feature_lineage_gate` | exact_code | 1.00 |
| PR-EXP-0106-C04 (UKB-PPP case-count discrepancy) | MEDIUM | sample_size | `sample_size_gate` | exact_code | 1.00 |
| PR-EXP-0106-C05 (independent vs total variant counts) | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | exact_code | 1.00 |

All four matches are gate-code exact hits — the post-67f7492 fix
continues to do the load-bearing work.

## Missed concerns (FN = 6)

| Concern | Sev | Category | Expected gates | Why missed |
|---|---|---|---|---|
| C02 (incident-only rationale) | HIGH | study_design | `cohort_definition_gate` | Same gate as C01; matcher one-flag-per-concern de-dup gives the single `cohort_definition_gate` flag retrieved to C01 (first concern wins on tie). |
| C06 (pQTL percentage contradiction + pathway background) | MEDIUM | evaluation_metrics | `evaluation_quality_gate`, `clinical_metrics_gate`, `calibration_dca_gate` | 7 `evaluation_quality_gate` flags retrieved but the single non-FP one is already claimed by C05; remaining six carry unrelated multi-omics / incremental-value evidence. No `calibration_dca_gate` retrieved. |
| C07 (case-only pQTL discovery vs incident-prediction hypothesis mismatch) | HIGH | study_design | `cohort_definition_gate` | De-duped against C01. |
| C08 (co-morbidity unaccounted) | MEDIUM | study_design | `cohort_definition_gate`, `clinical_metrics_gate`, `calibration_dca_gate` | De-duped against C01; no `clinical_metrics_gate` or `calibration_dca_gate` neighbour in top-20. |
| C09 (huge per-disease sample-size variance, 55–12 000) | MEDIUM | sample_size | `sample_size_gate`, `cohort_definition_gate`, `clinical_metrics_gate` | Single `sample_size_gate` flag claimed by C04 first. |
| C10 (PRS adds no C-index improvement) | HIGH | evaluation_metrics | `evaluation_quality_gate`, `metric_consistency_gate`, `reporting_bias_gate` | Hidden behind already-claimed `evaluation_quality_gate`; neither `metric_consistency_gate` nor `reporting_bias_gate` flag retrieved. |

The mechanical pattern: **four of six misses are pure matcher de-dup
collisions** — the right gate was retrieved, just consumed by an
earlier concern with the same gate signature. Two are KB-coverage
gaps (`metric_consistency_gate`, `calibration_dca_gate`,
`clinical_metrics_gate` simply absent from the top-20 for this query).

## Over-flags (FP = 16)

| Bucket | Count | Notes |
|---|---|---|
| `evaluation_quality_gate` (HIGH×6, MED×1) | 7 | Topic-drifted from NetBio, multi-omics incremental value, PRS source-data discussion — same gate keeps surfacing on any "compare predictive performance" prompt. |
| `cohort_definition_gate` (HIGH) | 3 | Taxane cfDNA, intrinsic bias, "examine the potential of serum proteomics" — adjacent but not what reviewers raised. |
| `leakage_gate` (CRITICAL ×1, HIGH ×1) | 2 | Same-dataset GWAS+PPS critique (conceptual neighbour to PRS papers); model-evaluation ground-truth phrasing. **The CRITICAL flag is the single most damaging FP** — proteomics-risk-prediction reviewers raised zero leakage concerns. |
| `missingness_policy_gate` (HIGH) | 1 | Generic missingness prompt; PR-EXP-0106 reviewers did not raise it. |
| `publication_gate` (HIGH) | 1 | Reproducibility hit on code-sharing language; PR-EXP-0106 review is silent on code availability. |
| `external_validation_gate` (HIGH) | 1 | TriNetX boilerplate — irrelevant to UKB-PPP proteomics. |
| `split_protocol_gate` (HIGH) | 1 | Preterm-delivery split discussion bled in. |

## On the evaluation_metrics bias check

This pick was meant to probe whether MLGG's metric-checking gates
match reviewer metric complaints. With **3 EM concerns**, recall is
**1/3** (33%). The single EM hit is the cleanest exact-gate case (C05
→ `evaluation_quality_gate`). The two EM misses are diagnostic of two
different failure surfaces:

- **C10** (the highest-severity EM concern, HIGH) loses on **matcher
  de-dup**, not on retrieval — `evaluation_quality_gate` was returned
  seven times, but the matcher's one-flag-per-concern rule routed the
  best instance to C05 (first in concern order) instead of C10.
  A multi-flag-per-concern variant or severity-weighted assignment
  would recover C10 trivially.
- **C06** (HIGH-relevance metric contradiction inside a single figure)
  loses on **KB coverage** — `metric_consistency_gate` and
  `calibration_dca_gate` are wired up but no neighbour with relevant
  evidence text was retrieved.

So: of the two gating mechanisms in front of EM reviewer-style
concerns, the **matcher** is the binding constraint on this paper,
not the gate catalogue. Tuning de-dup before adding more EM gates is
the higher-leverage move.

## Narrative

PR-EXP-0106 is the cleanest in-scope case the briefs have produced so
far: tabular UKB cohort, binary incident-disease prediction, exactly
the modality MLGG was built for. F1 = 0.28 is essentially the same
score W24-02 and W24-03 got on out-of-modality PRS/GWAS papers
(0.29 / 0.29). That non-divergence is the most informative result of
the run: **on this query construction (KMI-fallback, title+task+concern
prefixes), MLGG's per-paper score has a ~0.28 F1 ceiling regardless of
whether the paper is in-domain**. The matched concerns are all easy
exact-gate hits; the misses are all matcher-de-dup or KB-coverage
gaps; the over-flags are dominated by `evaluation_quality_gate`
retrieval bleed (7 of 16) and one CRITICAL `leakage_gate` FP whose
upstream consumer would be misled into thinking the proteomics paper
has a leakage problem it does not. Category coverage is a clean 4/4 —
every reviewer category had at least one matched flag — but that
masks the recall failure inside each category. The EM-bias result (1/3
recall on the targeted subset) suggests MLGG's metric-checking
catalogue is wired correctly but the matcher's flag-per-concern cap
is destroying signal before it reaches the scoring layer.

## Compare to W24-02 / W24-03

| Run | Paper | Domain | F1 | Prec | Recall | Cov | Notes |
|---|---|---|---|---|---|---|---|
| W24-02 | PR-017 | PRS multi-ancestry | 0.291 | 0.186 | 0.667 | 3/5 | Out-of-modality |
| W24-03 | PR-018 | PRS GWAS-summary | 0.288 | 0.184 | 0.667 | 3/3 | Out-of-modality |
| **W24-16** | **PR-EXP-0106** | **UKB-PPP proteomics, in-modality** | **0.282** | **0.233** | **0.357** | **4/4** | KMI=None, query is title+task+concern-prefix fallback |

Same F1, **worse recall but better precision**. The recall drop traces
to the missing KMI seed: W24-02/03 had a focused 3-tag query that
pulled targeted neighbours and scored 2/3 recall on small concern sets
(n=5); W24-16's diffuse 600-char fallback query pulls broader but
shallower neighbourhoods, and the bigger concern set (n=10) overloads
the one-flag-per-concern matcher. Precision improves because the
in-modality paper genuinely has more overlap with KB cohort/
sample-size neighbours.

## Reproducibility

- Run date: 2026-05-17
- Source: `references/case-studies/peer-review-kb.json` → `entries[id=PR-EXP-0106]`
- Pipeline: `synthesize_flags_from_rag(query, top_k=20)` →
  `match_all(flags, concerns)` →
  `per_paper_score(paper_id, flags, concerns)`
- Wall: 12.1 s end-to-end (cold start, BGE load dominates per W22-V2)
- Raw artefact: `/tmp/W24_16_result.json` (not committed; run-local)

(Author note: 300-word report budget applies to the parent-agent
return message, not this diagnostic file. Length here is the same
order as W24-02 and W24-03 siblings.)
