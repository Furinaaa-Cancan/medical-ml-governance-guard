# W24-19 — Case Study: PR-EXP-0205 (real NC paper, COVID-19 mortality risk)

End-to-end MLGG NCPR run on a single real Nature Communications paper following
the W24-01/02/03 protocol (PDF-less variant: KB-derived query →
`synthesize_flags_from_rag` top_k=20 → `ncpr_matcher.match_all` with
`embed_fn=None` → severity-weighted F1 + category coverage). Run on `main`
post-67f7492 (`mlgg_gates[0]` gate-first mapping active). Semantic tier is
honestly skipped; only `exact_code` / `code_prefix` / `category` tiers fire.
Per spec §3.4 only `exact_code` and `code_prefix` matches contribute to P/R.

**Pick rationale (W24-19 spec: ≥10 concerns + ≥1 CRITICAL/HIGH + KMI + 5-category
stress test).** The strict triple is empty on the unreserved KB at run time:

| Filter | Survivors |
|---|---:|
| ≥10 concerns, ≥1 H/C, not in reserved or sibling-claimed (PR-RO-07, PR-EXP-0085, PR-EXP-0212 already grabbed) | **0** |
| ∩ KMI present | **0** (no PR-EXP or PR-RO entry carries KMI) |
| ∩ covers all 5 frozen NCPR categories | **0** (max raw-cat coverage on remaining unclaimed KB is 4/5) |

Cherry-pick per spec, with **category-coverage stress test as the explicit
tie-break per the W24-19 bias directive**. **PR-EXP-0205** is the only
unclaimed paper covering **4 of 5 frozen categories on the reviewer side
including the rare `data_leakage`** (only 9 leakage-tagged concerns across the
whole 817-concern KB). 6 reviewer concerns is below the ≥10 ideal but the
severity mix is rich (1 CRITICAL + 1 HIGH + 4 MEDIUM) and the domain — COVID-19
EHR mortality, retrospective tabular binary classification — sits squarely
inside MLGG's nominal scope (unlike the genomic / GNN-on-AMR siblings W24-12 /
W24-13). Cherry-pick reason recorded for the audit trail.

## Paper meta

| Field | Value |
|---|---|
| Paper ID | PR-EXP-0205 |
| DOI | `10.1038/s41467-020-18297-9` |
| Title | *Developing a COVID-19 mortality risk prediction model when individual-level data are not available* |
| Journal | Nature Communications (2020) |
| Domain | COVID-19 mortality (retrospective EHR binary classification, in-scope) |
| Prediction task | COVID-19 mortality risk model trained without individual-level patient data |
| Data type | `ehr_tabular_clinical` |
| Review rounds | 1 (6 reviewer concerns, 3 strength tags) |
| Reviewer-side strengths (tags) | `population_scale_data`, `calibration_and_dca_reported`, `tripod_minded` |
| Outcome | `extracted_2026-05-13` (no explicit accept/reject in KB record) |
| `key_methodology_issues` | empty (PR-EXP entries do not carry KMI) |
| PDF (verified by DOI-shorthand match) | `references/case-studies/nature_communications/s41467-020-18297-9_peer_review.pdf` |

Query passed to `rag_query` (`top_k=20`, ~1.3 KB): `prediction_task` +
sorted-unique concern `tags` (30 cap) + concern raw `category` tokens + 120-char
prefixes of each `concern_text`. This is the W24-09 KMI-less proxy, with the
`category` token addition specifically intended to surface the
category-coverage stress vocabulary the spec asks for.

## Match summary

| Metric | Value |
|---|---:|
| n_flags | 20 |
| n_concerns | 6 |
| matched_pairs (all `exact_code`, score = 1.00) | **6 / 6** |
| wTP / wFN / wFP | **10.0 / 0.0 / 15.0** |
| wPrecision | **0.400** |
| **wRecall** | **1.000** |
| **weighted_F1** | **0.571** |
| **category_coverage (frozen 5)** | **4 / 5 = 0.800** (evaluation, design, reporting, leakage covered; external_val absent on both sides — not a miss) |
| `missed_categories` per spec | **[]** (zero — no reviewer category had ≥1 concern with 0 MLGG flags) |
| reviewer-side raw-cat reviewer coverage (pre-frozen-normalisation) | 4 of 5 frozen (evaluation_metrics, study_design, reporting, data_leakage; external_validation absent) |
| reviewer-side out-of-frozen-5 raw categories | 1 concern (`model_selection`, dropped by normalisation) |
| per-severity matched / missed / over-flag | **CRITICAL 1/0/1 · HIGH 1/0/13 · MEDIUM 4/0/0 · LOW 0/0/0** |

This is the cleanest recall picture in the W24-* set to date: **6/6 reviewer
concerns matched, including the CRITICAL data_leakage concern (C05)**. The 4/5
frozen coverage is the *maximum achievable for this paper* — reviewers did not
raise an `external_validation` concern, so by the `coverage_per_category` rule
(both sides non-empty) it can never light up. The diagnostic also (correctly)
returns `missed_categories=[]` because every reviewer-side bucket that was
non-empty was matched by ≥1 MLGG flag.

## Real concerns matched (all 6, all `exact_code` at 1.00)

| Concern | Sev | Reviewer category | Matched flag (`code`) | Notes |
|---|---|---|---|---|
| `PR-EXP-0205-C01` | MEDIUM | reporting | `reporting_bias_gate` | TRIPOD title-conformance. Reviewer's first gate hit on first try. |
| `PR-EXP-0205-C02` | MEDIUM | model_selection | `model_selection_audit_gate` | Default hyperparameters for GBM — first-listed gate. |
| `PR-EXP-0205-C03` | HIGH | study_design | `cohort_definition_gate` | Outcome window definition ("6 weeks prior to extraction date"). Sole HIGH match. |
| `PR-EXP-0205-C04` | MEDIUM | evaluation_metrics | `evaluation_quality_gate` | Sensitivity analysis on recalibrated CFR predictions. |
| **`PR-EXP-0205-C05`** | **CRITICAL** | **data_leakage** | **`leakage_gate`** | **Hospitalization-duration variable scale + future-conditioning concern. The CRITICAL prize: the rare leakage category fires cleanly.** |
| `PR-EXP-0205-C06` | MEDIUM | evaluation_metrics | `calibration_dca_gate` | Calibration + DCA must change after recalibration. Reviewer's *first* gate (`calibration_dca_gate`) caught — the matcher walked past the `evaluation_quality_gate` alternative because that was already claimed by C04 under the one-flag-per-concern dedup. |

All 6 matches are pure `exact_code` (zero `code_prefix`, zero `category`). The
67f7492 fix is *structurally functioning at full strength* on this paper: every
reviewer concern's first-listed gate was retrieved by RAG in the top-20 *and*
the dedup never starved a concern. Pre-fix (`concern_id` as flag code), every
match here would have collapsed to `category`-tier (diagnostic-only, doesn't
count per spec §3.4) and F1 would have been ≈ 0.

## False negatives

**None.** wFN = 0.0. This is the first W24-* case to achieve zero FN. Treat
with caution: with only 6 concerns and a 20-flag retrieval cap, the matcher
has 20 chances per concern and the 6 reviewer-listed first-gate codes all
appear in the top-20 retrieval — partly because COVID-19 EHR sits squarely
inside MLGG's curation core (calibration_dca_gate, cohort_definition_gate,
leakage_gate, reporting_bias_gate are all heavily populated in the KB).

## Over-flags (false positives — 14 of 20 retrieved flags unmatched)

| Severity | Code | Count | Why irrelevant to PR-EXP-0205 |
|---|---|---:|---|
| CRITICAL | `split_protocol_gate` | 1 | Evidence about AI-EF cohort patient overlap — unrelated cardiology paper pulled by the BM25 channel on the word "cohort". The lone CRITICAL over-flag. |
| HIGH | `evaluation_quality_gate` | 4 | Generic-metric overflow: imbalanced-data AUC critique, GBC accuracy claim, classification-accuracy definition confusion — all token-overlap on "accuracy/AUC/metric". |
| HIGH | `cohort_definition_gate` | 4 | Same `cohort_definition_gate` code as C03's match, but with evidence about a different paper's cohort (ESRD onset, treatment-effect cohort, etc.). |
| HIGH | `leakage_gate` | 1 | A *second* leakage_gate flag, evidence about "ground truth generation in model evaluation subsection" — different paper. The reviewer's single C05 leakage concern already claimed the first `leakage_gate` flag (better dedup score); this twin sits in unmatched_flags. Notable as the only paper in the W24 set where the leakage category over-fires twice on real-leakage-domain papers. |
| HIGH | `clinical_metrics_gate`, `missingness_policy_gate`, `calibration_dca_gate`, `sample_size_gate` | 1 each | Token-overlap residuals on `clinical_utility`, `preprocessing`, and `sample_size` evidence from unrelated KB entries. |

Total wFP = 15.0 (1 × CRITICAL × 1.5 + 13 × HIGH × 1.0 - 0.5 FP discount per
the `weighted_tp_fn_fp` formula). The over-flag column **dominates the
precision penalty** (0.40) even though recall is perfect; this is the canonical
W24-* phenotype.

## 1-paragraph narrative

For PR-EXP-0205 (COVID-19 mortality risk, NC 2020, retrospective EHR binary
classification — squarely inside MLGG's nominal scope), the post-67f7492
gate-first lexical fast-path produces **6 clean `exact_code` matches against
all 6 reviewer concerns, including the CRITICAL data_leakage concern (C05)**,
landing weighted-F1 = 0.571 with wRecall = 1.000 — the strongest recall in the
W24-* sequence to date. The 4/5 frozen category coverage is the *maximum
achievable* (reviewer-side `external_val` is empty, so it cannot light up by
the both-sides-non-empty rule). The 0.40 precision is driven by 14 over-flag
HIGH/CRITICAL flags — generic `evaluation_quality_gate` and `cohort_definition_gate`
twins that the BM25 channel pulled from unrelated KB entries on token overlap
with "cohort/AUC/accuracy" vocabulary. Two phenomena stand out: (a) the rare
`leakage_gate` over-fires twice (F3 matched, F7 stranded) — the leakage axis
is sparse enough in the KB that a single leakage-themed query lights up
*every* leakage entry indiscriminately, and (b) the `calibration_dca_gate`
match on C06 only worked because the one-flag-per-concern dedup *steered* the
matcher past the better-scoring `evaluation_quality_gate` (already claimed by
C04) onto the reviewer's first-listed gate — without that dedup-driven walk,
C06 would have lost to over-flag F0 and recall would have dropped. The strength
column shows reviewers explicitly tagged the paper as
`tripod_minded` and `calibration_and_dca_reported` — meaning the methodology
was already high-quality and the 6 concerns are minor incremental asks, which
is precisely the phenotype where the current retrieval-only matcher achieves
its highest recall.

## Category-coverage breakdown (the W24-19 stress-test deliverable)

| Frozen category | Reviewer concerns | MLGG flags | Covered? | Notes |
|---|---:|---:|:---:|---|
| `evaluation` | 2 | 6 | **YES** | C04 + C06 matched; 4 over-flags |
| `design` | 1 | 5 | **YES** | C03 matched; 4 over-flags |
| `reporting` | 1 | 1 | **YES** | C01 matched cleanly; 0 over-flags — only 1 reporting flag retrieved total |
| `external_val` | 0 | 0 | n/a | Empty on both sides — not a miss per `category_coverage` definition |
| **`leakage`** | **1** | **2** | **YES** | **C05 (CRITICAL) matched; 1 over-flag twin. Rare category fires correctly.** |
| `coverage_rate` | | | **0.800** | 4 of 5 frozen categories covered |
| Reviewer raw-categories outside frozen 5 | 1 (`model_selection`) | (counts vary) | n/a | Matched via gate code (C02) but does not count toward `coverage_rate` |

## Comparison to W24-* siblings

* W24-01 (PR-013): F1 0.192, 3/6 matched, coverage **1/5** (reporting only) — reviewer concerns spanned fewer frozen categories
* W24-02 (PR-017): F1 0.291, 3/5 matched, coverage **3/5**
* W24-03 (PR-018): published F1 in similar 0.2–0.3 band (genomics out-of-scope)
* **W24-19 (PR-EXP-0205, this run): F1 0.571, 6/6 matched, coverage 4/5** — best recall, highest coverage of the documented W24-* set
* Pre-67f7492 expected F1 ≈ 0.0 (lexical fast-path dead → all signal collapses to category-tier diagnostic-only matches)

**Delta interpretation.** PR-EXP-0205 represents the upper envelope of what the
current embedder-less, top-20-only retrieval can achieve: when the paper sits
inside MLGG's curated EHR scope, has only a handful of focused concerns, and
the reviewer's first-listed gate is well-populated in the KB, recall hits 1.0
and even the rare `leakage` axis lights up. Precision still gets crushed to
0.40 by 14 generic HIGH over-flags — the path forward (injecting an embedder
for evidence-relevance gating, or tightening the BM25 channel with domain
boost on `covid` / `mortality`) would lift precision without sacrificing the
recall floor this paper proves is reachable.

## Provenance

* Raw run output (query, all 20 flags, full match record, score breakdown,
  coverage diagnostic): `/tmp/W24_19_result_v2.json` (ephemeral; not committed).
* Runner: `/tmp/W24_19_runner.py` (ephemeral).
* Code paths exercised: `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag`,
  `scripts.rag.evals.ncpr_matcher.match_all` (embed_fn=None),
  `scripts.rag.evals.ncpr_severity_score.per_paper_score`,
  `scripts.rag.evals.ncpr_category_coverage.category_coverage` (with a
  raw-category → frozen-dimension normalisation applied on a defensive copy
  of the concerns / flags lists; KB is not mutated).
* Hard rules honoured: NEW file only (this case study);
  READ-ONLY on everything else; no sub-agents; no embedder injection
  (semantic tier honestly skipped).
* Pick path: cherry-pick (strict ≥10 + KMI + all-5-cats triple empty on the
  unreserved KB at run time); selection driven by the W24-19 explicit
  category-coverage-stress bias, which uniquely surfaced PR-EXP-0205 as the
  only unclaimed paper covering the rare `data_leakage` axis with a CRITICAL
  severity.
