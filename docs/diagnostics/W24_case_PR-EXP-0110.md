# W24-14 Case Study: PR-EXP-0110

**Date:** 2026-05-17 **Mode:** READ-ONLY (in-process RAG, no subprocess, no embedder)
**Paper:** *Artificial intelligence-enabled prediction of chemotherapy-induced cardiotoxicity from baseline electrocardiograms*, Nature Communications 2024 (DOI `10.1038/s41467-024-45733-x`)
**Reviewer concerns:** 11 total — severity histogram **CRITICAL 1 / HIGH 4 / MEDIUM 6 / LOW 0**
**MLGG flags:** 20 (top-20 RAG retrieval against tag-proxy query)
**Matcher:** `ncpr_matcher.match_all` with `embed_fn=None` → semantic tier skipped; only `exact_code` + `code_prefix` + `category` tiers active. **No category-tier matches contributed to P/R per spec §3.4.**
**Code path:** post-commit `67f7492` (`synthesize_flags_from_rag` prefers `mlgg_gates[0]` over `concern_id` → lexical fast-path alive).
**KMI caveat:** `key_methodology_issues` is **null** in the KB entry; query seed was constructed from the top-8 unique reviewer-supplied `tags` instead. The cardiotoxicity paper is in-scope (retrospective EHR cohort, binary CTRCD outcome) — MLGG's nominal mandate applies.

## Paper meta

| Field | Value |
|---|---|
| Domain | cardio-oncology (anthracycline cardiotoxicity from baseline ECG) |
| Prediction task | Pre-chemotherapy prediction of CTRCD (cancer-therapy-related cardiac dysfunction) from 12-lead ECG via AI-EF model |
| Sample size (per reviewer) | 1,138 enrolled · 1,753 in ACU sub-cohort (KB `sample_size` null) |
| Outcome | accepted_after_major_revision (extracted_2026-05-13) |
| `is_cohort_retrospective_binary` | true |
| MLGG-coverage | **in scope** — retrospective binary classification on ECG-derived features |

## Query

Tag-proxy (KMI-empty fallback; tags pooled across all 11 concerns, dedup-preserve-order, first 8):

```
Artificial intelligence-enabled prediction of chemotherapy-induced cardiotoxicity
from baseline electrocardiograms.
Clinical outcome prediction (Nature Comm 2024).
Key issues: target_specificity baseline_susceptibility_vs_outcome
outcome_construct_validity transfer_learning_added timing_of_prediction
post_treatment_selection_bias surveillance_bias task_specific_training
```

## Match summary

| Metric | Value |
|---|---:|
| weighted_f1 | **0.460** |
| wPrecision | 0.392 |
| wRecall | 0.556 |
| wTP / wFN / wFP | 10.0 / 8.0 / 15.5 |
| category_coverage | **3 / 5** (`evaluation`, `design`, `leakage` covered; `reporting`, `external_val` empty on MLGG side / reviewer side respectively) |
| per-severity matched / missed | CRITICAL **1/0** · HIGH 2/2 · MEDIUM 2/4 · LOW 0/0 |
| over-flags (HIGH+CRITICAL severity) | 12 (10 HIGH + 2 CRITICAL) |

Headline jumps relative to W24-03 PR-013 (F1 = 0.192): two structural advantages — (a) the single CRITICAL concern (C07) is a textbook leakage flag with `split_protocol_gate` in `mlgg_gates`, so the post-67f7492 lexical fast-path catches it cleanly (wTP += 4.0), and (b) 4 of 11 concerns carry `cohort_definition_gate` as the first gate, which is *also* the dominant MLGG over-flag pattern, so several real concerns find an `exact_code` mate even without semantic help.

## Real concerns matched (5 of 11)

| # | Severity | Reviewer concern (truncated) | Matched MLGG flag (code → evidence) | Match type | Score |
|---|---|---|---|---|---:|
| C01 | HIGH | AI-EF predicts baseline LV pathology, not CTRCD-specifically; outcome construct validity. | `cohort_definition_gate` ← "functionally relevant CAD is a combination of two outcomes (SPECT + cath) without clear delineation; selective referral induces bias" | exact_code | 1.00 |
| C03 | HIGH | Need task-specific training on patients who have actually begun chemo; transfer-learning question. | `cohort_definition_gate` ← "target cohort comprised 1753 patients who received acute care within 30 days of initiation of chemotherapy" (lexically reviews same cohort as PR-EXP-0110 itself — possible self-hit from KB) | exact_code | 1.00 |
| C04 | MEDIUM | AUC 0.77 vs 0.75 is marginal; AI-EF alone unreported; incremental-value missing. | `evaluation_quality_gate` ← "sophisticated DL needs additional-benefit assessment relative to simple clinical scores" | exact_code | 1.00 |
| C05 | MEDIUM | "enrolled" vs EHR-extracted wording ambiguity. | `external_validation_gate` ← "lack of external validation with other arrhythmia detection models; broad statements premature" (cross-gate match on first gate `reporting_bias_gate` would have worked, but the matcher chose `external_validation_gate` via concern's secondary gate — see "Provenance" note) | exact_code | 1.00 |
| **C07** | **CRITICAL** | **Patient-level overlap between this cohort and the AI-EF model's original training cohort (BWH/MGH/UCSF/Keio).** | `split_protocol_gate` ← "did the authors make sure that the patients included in the cohort presented in this manuscript were not included in the original training and validation cohorts" — **MLGG retrieved the reviewer's own quote back; the KB self-hit is what powered the CRITICAL save** | exact_code | 1.00 |

The CRITICAL win is the headline story. The split-protocol concern is the single most damaging issue in the paper (pretraining-cohort leakage), and the matcher's `exact_code` tier latched onto it because (a) the reviewer pre-tagged `split_protocol_gate` as the first MLGG gate, (b) the KB entry for PR-EXP-0110 itself was retrieved at rank 5, so the flag's `code` and `evidence_text` both come from the same concern. **This is a self-hit** — RAG returned the paper's own KB row, which means the headline F1 is *upward-biased* for any paper that is already in the KB. The numerical lift is honest about precision/recall arithmetic but the *capability claim* ("MLGG independently detected the leakage") requires a leave-one-out test the matcher does not run today.

## Real concerns MISSED (6 false negatives)

| # | Severity | Reviewer concern | Tagged gates | Why missed |
|---|---|---|---|---|
| C02 | HIGH | Should the model also use *post*-chemo ECGs to detect already-present damage? (timing-of-prediction, surveillance bias) | `cohort_definition_gate`, `reporting_bias_gate` | RAG retrieved 8 `cohort_definition_gate` flags total; under the matcher's one-concern-per-flag dedup, the first three were consumed by C01 (best fit) and C03 (next best). Flags 1, 2, 3, 4, 7, 8 were *also* `cohort_definition_gate` but each lost the contest against an already-claimed concern, leaving C02 stranded with no surviving `cohort_definition_gate` or `reporting_bias_gate` candidate. |
| C06 | MEDIUM | "Excellent stratification" claim is overstated for AUC 0.77 / PPV 16.9 %. | `execution_attestation_gate`, `evaluation_quality_gate`, `reporting_bias_gate` | A second `evaluation_quality_gate` flag (idx 19, "DL sensitivity vs cardiologists — needs NRI") was in the top-20 but was claimed by no concern; the matcher's flag-side best-first pass picked C04 (also `evaluation_quality_gate`) at idx 9 before reaching idx 19, and idx 19 had no surviving second-best concern after C04 was taken (the matcher does not retry with the second-best flag). |
| C08 | MEDIUM | No sex-stratified subgroup analysis. | `fairness_equity_gate`, `reporting_bias_gate` | Zero `fairness_equity_gate` flags and zero `reporting_bias_gate` flags in the retrieved top-20. The KB is sparse for fairness-coded concerns (W22-U2 stats: only `fairness_subgroups` appears as a tag, not a gate code). This is a **KB-coverage gap**, not a matcher bug. |
| C09 | HIGH | Risk-stratification is weak — 41 of 99 cardiomyopathy cases fell in the low-risk bucket. | `evaluation_quality_gate`, `clinical_metrics_gate` | Same flag-exhaustion as C06. Two `clinical_metrics_gate` flags exist (idx 10 cardio-oncology DL, idx 16 *clinical course changed for 1 of 600 patients*) — idx 10 claimed by C04, idx 16 unclaimed. C09 had no surviving `evaluation_quality_gate` candidate. |
| C10 | MEDIUM | Outcome-ascertainment: how many patients had pre+post echo? | `cohort_definition_gate` | Same `cohort_definition_gate` exhaustion as C02. |
| C11 | MEDIUM | Anthracycline dose should be cumulative doxorubicin equivalents, not raw. | `feature_engineering_audit_gate`, `feature_lineage_gate` | Zero `feature_engineering_audit_gate` or `feature_lineage_gate` flags in the top-20. Tag-proxy query did not pull feature-engineering territory because the seed tags are all outcome- and timing-flavoured. |

**Pattern:** 4 of 6 misses are *flag-exhaustion* artefacts (the matcher had a same-gate flag available but spent it on a higher-priority concern); 2 of 6 are *KB-coverage* gaps (fairness + feature-engineering gates simply did not surface). Raising `top_k` from 20 → 40 or relaxing the one-flag-per-concern rule would close roughly half the gap.

## Over-flags (15 false positives — MLGG flagged, reviewer didn't)

15 of 20 retrieved flags went unmatched. The over-flag profile is heavily biased toward `cohort_definition_gate` (8 of 15 unmatched are this gate — *Tri AI-segment* lung paper, H. pylori AI-clinician, ARSI prostate response, idiosyncratic DILI, sepsis mimickers, etc.).

| Severity | MLGG flag (code) | Why irrelevant to PR-EXP-0110 |
|---|---|---|
| CRITICAL ×2 | `cohort_definition_gate` (HCC treatment-decision overclaim; H. pylori AI-clinician immaturity) | Pulled by token overlap on "predict", "treatment", "cohort"; unrelated oncology/GI papers. |
| HIGH ×6 | `cohort_definition_gate` (lung CT model claim ambiguity; CLL infection-vs-treatment confusion; ICI-mono vs ICI-chemo bias; emergency-medicine gold-standard absence; ARSI treatment-vs-prognosis; DILI 24h-hepatocyte training bias; sepsis mimicker controls) | All oncology / ID / hepatology cohort-definition concerns. None about cardio-oncology. |
| HIGH ×4 | `external_validation_gate`, `model_selection_audit_gate`, `evaluation_quality_gate` (CancerSEEK comparison absent), `clinical_metrics_gate` (1 of 600 intervention-arm patients) | KB-heavy gates that over-fire on any "validation" / "method" / "clinical" token. |
| MEDIUM ×3 | `evaluation_quality_gate` (DL-vs-cardiologist NRI), `cohort_definition_gate` (multimodal-survival novelty), one more `cohort_definition_gate` | Generic ML-vocabulary leakage; idx 19 NRI flag is actually domain-relevant to cardio-AI but didn't lexically line up with a reviewer-tagged gate. |

The wFP weight of 15.5 (2×CRITICAL×4×0.5 + 10×HIGH×2×0.5 + 3×MEDIUM×1×0.5 = 4.0 + 10.0 + 1.5) crushes precision to 0.39. The `cohort_definition_gate` over-fire pattern is exactly what W23-B3 lineage red-team flagged: it is the most common gate code in the KB and therefore the most common BM25 target.

## 1-paragraph narrative

For this cardio-oncology paper, MLGG correctly caught the single CRITICAL concern — the pretraining-cohort leakage in the AI-EF model — and 4 additional concerns (2 HIGH on outcome construct validity / task-specific training, 1 MEDIUM on marginal AUC improvement, 1 MEDIUM on prospective-vs-retrospective wording). The CRITICAL save is the headline (wTP += 4.0 of 10.0 total) but is a **KB self-hit**: the matcher retrieved PR-EXP-0110's own KB row at rank 5, so the flag's code and evidence text are literally the reviewer's own quote. This inflates the F1 reading and any cross-paper benchmark using PDF-less / KB-only retrieval must either leave-one-out filter or treat self-hits as a control, not a signal. The wF1 of 0.46 (vs PR-013's 0.19) reflects two real structural wins independent of the self-hit: (a) cardiology + chemotherapy is well-represented in the KB so multiple reviewer-tagged gates have lexical neighbours in the top-20, and (b) the post-67f7492 fix is paying off — every match used `exact_code` and the lexical fast-path was alive for all five hits. The remaining failure modes are *flag-exhaustion* (one-concern-per-flag dedup leaves identical-gate concerns stranded; would lift recall by ~0.2 if relaxed) and *KB-coverage gaps* on fairness and feature-engineering codes (would need a KB-side fix, not a matcher one). Over-flag profile is dominated by `cohort_definition_gate` (8 of 15 unmatched), confirming the W23-B3 lineage red-team finding that this gate is BM25-bait.

## Comparison to prior W24 case studies

| Paper | F1 | wTP | wFN | wFP | CRIT matched | KB self-hit? | Domain |
|---|---:|---:|---:|---:|---|---|---|
| PR-013 (ALS wearables) | 0.192 | 2.5 | 4.0 | 17.0 | 0/0 | not assessed | longitudinal accelerometer |
| PR-017 (W24-01) | n/a | — | — | — | — | — | — |
| PR-018 (W24-03 PRS tuning) | n/a | — | — | — | — | — | GWAS summary-stats (OOD) |
| PR-EXP-0109 | n/a | — | — | — | — | — | — |
| **PR-EXP-0110 (this run)** | **0.460** | **10.0** | **8.0** | **15.5** | **1/1** | **YES (rank 5)** | cardio-oncology ECG |

PR-EXP-0110 is the highest-F1 W24 case studied so far. The headline lift is real but caveated: the in-KB self-hit is doing structural work, and a leave-one-out re-run would likely halve the wTP (4.0 → ~6.0, F1 ≈ 0.32) — still ~2× PR-013 because of better KB neighbourhood density in cardio-oncology and an exact-coded CRITICAL outside the self-hit class.

## Unexpected behaviour

* **KB self-hit at rank 5 is structurally invisible to the matcher.** `synthesize_flags_from_rag` does not exclude the source paper from `rag_query`, so a paper that has been ingested into the KB scores against its own concerns. PR-EXP-0110 was clearly inserted (BGE retrieved its exact text). Recommend W25 sibling: add `exclude_paper_id` parameter to `rag_query` and re-baseline the NCPR macro-F1 with it on.
* **`key_methodology_issues` is null** for 4 of the 6 W24 candidate papers I screened (PR-RO-07, PR-EXP-0085, PR-EXP-0110, PR-EXP-0212). The KB schema permits it but the NCPR runner's documented query strategy assumes it is present. The tag-proxy fallback I used works but is *not* the protocol; this should be promoted from ad-hoc to spec or KMI back-fill prioritised in W25.
* **`cohort_definition_gate` BM25-bait is now a 2-of-2 finding** (PR-013 had 2 cohort over-flags; PR-EXP-0110 has 8). The gate name plus the word "cohort" appears in essentially every reviewer concern about study design, so BM25 retrieval over-recruits it. Worth a precision-targeted re-rank in W25.

## Provenance

- Raw run output (queries, all 20 flags, full match record, score breakdown, coverage): `/tmp/W24_PR-EXP-0110_run.json` (ephemeral; not committed).
- Runner script: `/tmp/W24_PR-EXP-0110_run.py` (ephemeral).
- Code paths exercised: `scripts.rag.query.rag_query` (top_k=20), `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag`, `scripts.rag.evals.ncpr_matcher.match_all` (embed_fn=None), `scripts.rag.evals.ncpr_severity_score.per_paper_score`, `scripts.rag.evals.ncpr_category_coverage.category_coverage`.
- C05's `external_validation_gate` win uses the concern's *second* gate hint; the matcher iterates `gates` in order and the first hint `reporting_bias_gate` matched zero flags, so the loop fell through to the second. This is spec-conformant (`match_flag_to_concern` checks all hints), not a bug.
- Hard rules honored: NEW file only (this doc); read-only on KB, code, and all other diagnostics; no sub-agents; no embedder injection (semantic tier honestly skipped).
