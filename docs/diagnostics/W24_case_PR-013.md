# W24 Case Study: PR-013

**Date:** 2026-05-17 **Mode:** READ-ONLY (in-process RAG, no subprocess, no embedder)
**Paper:** *At-home wearables and machine learning sensitively capture disease progression in amyotrophic lateral sclerosis*, Nature Communications 2023 (DOI `10.1038/s41467-023-40917-3`)
**Reviewer concerns:** 6 total — severity histogram **CRITICAL 0 / HIGH 1 / MEDIUM 4 / LOW 1**
**MLGG flags:** 20 (top-20 RAG retrieval against KMI-derived query)
**Matcher:** `ncpr_matcher.match_all` with `embed_fn=None` → semantic tier skipped; only `exact_code` + `code_prefix` + `category` tiers active. **No category-tier matches contributed to P/R per spec §3.4.**
**Code path:** post-commit `67f7492` (`synthesize_flags_from_rag` prefers `mlgg_gates[0]` over `concern_id` → lexical fast-path alive).

## Query

Built from `key_methodology_issues` + `prediction_task` (preferred, paper-side material):

```
methods_irreproducible adherence_unreported post_hoc_outcome_selection
ALS disease progression tracking and severity prediction from wearable accelerometers
```

## Match summary

| Metric | Value |
|---|---:|
| weighted_f1 | **0.192** |
| wPrecision | 0.128 |
| wRecall | 0.385 |
| wTP / wFN / wFP | 2.5 / 4.0 / 17.0 |
| category_coverage | **1 / 5** (`reporting` covered; `evaluation` / `design` / `external_val` / `leakage` empty on reviewer side) |
| per-severity matched / missed | HIGH 0/1 · MEDIUM 2/2 · LOW 1/0 |
| over-flags (HIGH severity) | 17 |

`category_coverage = 1/5` is not a recall miss: the reviewer concerns for PR-013 only span two NCPR-frozen categories (`reporting`, plus `evaluation_metrics`/`reproducibility` which fall outside the frozen 5-category schema and bucket to none). Only `reporting` had simultaneous reviewer + MLGG presence.

## Real concerns matched

| Severity | Reviewer concern (truncated) | Matched MLGG flag | Match type | Score |
|---|---|---|---|---:|
| MEDIUM | The authors focus on rate of change, but variability in rates between patients plays a significant role... signal to noise... | `clinical_metrics_gate` | exact_code | 1.00 |
| MEDIUM | Monitoring protocol with 4 accelerometers per patient — provide insight into adherence, 7-day wear-time completion, patient burden/retention. | `reporting_bias_gate` | exact_code | 1.00 |
| LOW | The pairwise comparison model description is lacking clarity. The formula and outcome encoding need clearer explanation. | `model_selection_audit_gate` | exact_code | 1.00 |

All matches are `exact_code` (zero `code_prefix`, zero `category`). The 67f7492 fix is doing exactly what it advertised: flag `code` now equals the first reviewer-tagged gate name, so the lexical fast-path lights up wherever the reviewer thought to tag a gate at all.

## Real concerns MISSED (false negatives)

| Severity | Reviewer concern | Why missed (hypothesis) |
|---|---|---|
| **HIGH** | Methods are unclear on how rate of decline was calculated; no longitudinal models reported; per-patient regression slopes likely extracted but not stated — statistical analysis cannot be replicated. | Reviewer tagged `seed_stability_gate`, `execution_attestation_gate`, `reporting_bias_gate`. KB query returned a `reporting_bias_gate` flag (idx 1) — but it was claimed by concern #2 (adherence) first under the matcher's one-flag-per-concern rule. No retrieved flag carried `seed_stability_gate` or `execution_attestation_gate` codes, so this HIGH-severity reproducibility concern fell through. |
| MEDIUM | ICC computed on first-half vs second-half of days — likely systematic difference due to fatigue; Day 1 vs Day 2 would be more accurate. | Reviewer tagged `evaluation_quality_gate`. RAG retrieved an `evaluation_quality_gate` flag (idx 12) but its evidence text was about CT-scan claims, unrelated to ICC bias — and it was not assigned to this concern because the matcher does not check evidence-text relevance (only `code` lexical match). The matcher claims one flag per concern, and idx 12 was never picked because concern #1 (also `evaluation_quality_gate`-eligible via `clinical_metrics_gate`) had a better-fitting code. The deeper miss: RAG had no `evaluation_quality_gate` flag among its top hits in the slot that would have been free. |
| MEDIUM | Using "the limb with the fastest progression rate" — outcome must be prespecified for clinical trials; risk of inflated type-1 error. | Reviewer tagged `evaluation_quality_gate`. Same root cause as above: no available `evaluation_quality_gate`-coded flag in the unclaimed retrieval slots; post-hoc outcome selection is a known KB gap that the KMI keyword `post_hoc_outcome_selection` did not surface a concrete flag for. |

The HIGH miss is the costly one (weight 2.0 → 50% of total wFN = 4.0). It is a *one-to-many concern-vs-flag* exhaustion artefact: RAG did retrieve a `reporting_bias_gate` flag, but the matcher's flag-to-one-concern dedup (`ncpr_matcher.py` §`match_all`) assigned it to the adherence concern, leaving the reproducibility concern stranded with no alternate `reporting_bias_gate` or `seed_stability_gate` candidate in the top-20.

## Over-flags (false positives — MLGG flagged, reviewer didn't)

17 of 20 retrieved flags went unmatched. They concentrate on `external_validation_gate` (5), `model_selection_audit_gate` (3), `cohort_definition_gate` (2), and singletons for `calibration_dca_gate`, `clinical_metrics_gate`, `evaluation_quality_gate`, `robustness_gate`, `feature_engineering_audit_gate` (×2), `missingness_policy_gate`, `sample_size_gate`.

| Severity | MLGG flag (code) | Why irrelevant to PR-013 |
|---|---|---|
| HIGH | `sample_size_gate` | Evidence about "11–17 hard deterioration events" — a different cohort entirely (PR-013 has n=376 ALS patients tracked longitudinally; sample-size concern was never raised by reviewers). |
| HIGH | `external_validation_gate` (×5) | KB-heavy gate; over-fires on any "validation" phrasing. PR-013 reviewers explicitly praised the methodology as "beyond gold standard" (strength PR-013-S01); external validation was not their concern. |
| HIGH | `cohort_definition_gate` (×2) | Evidence quotes about chemotherapy ACU events and ARSI treatment-response — unrelated oncology cohorts pulled by the BM25 channel on the word "cohort". |
| HIGH | `calibration_dca_gate` | Decision-curve / clinical-impact framing irrelevant to a longitudinal-marker characterisation paper. |
| HIGH | `model_selection_audit_gate` (×3, of which 1 matched concern #6) | Two over-flag instances quote PRSice/LDPred and DL-vs-conventional debates — different domains entirely. |
| HIGH | `missingness_policy_gate`, `feature_engineering_audit_gate` (×2), `evaluation_quality_gate`, `robustness_gate`, `clinical_metrics_gate` | Each pulled by token overlap with the query's generic ML vocabulary; none addresses ALS-specific accelerometer methodology. |

The wFP weight of 17.0 (17 × HIGH × 0.5 FP-discount) dominates the denominator and crushes precision to 0.13.

## 1-paragraph narrative

For this paper, MLGG correctly latched onto the two MEDIUM concerns the reviewers tagged with `clinical_metrics_gate` and `reporting_bias_gate`, plus the LOW concern about pairwise-model clarity (`model_selection_audit_gate`). All three matches went through the `exact_code` tier — the 67f7492 fix is structurally doing its job. The MEDIUM and LOW recall is 3 of 5 (60%); the headline F1 sinks to 0.19 because (a) the single HIGH concern about irreproducible longitudinal modelling was crowded out by a one-flag-per-concern dedup conflict on `reporting_bias_gate`, and (b) the top-20 retrieval is dominated by 17 HIGH-severity external-validation / sample-size / cohort-definition flags pulled from generic-ML-vocabulary token overlap, each weighted 1.0 under the FP-discount. The qualitative reading: lexical retrieval against a 4-word KMI query is too broad — it surfaces every "validation" and "cohort" mention in the KB rather than ALS-specific concerns. PR-013's reviewers actually praised methodology (4 strengths logged) and raised mostly statistical-reporting issues that a longer methods excerpt or a domain-aware re-rank could have caught.

## Comparison to W23-D2 number

**W23-D2 per-paper F1 not committed to `main` as of this run** — `docs/diagnostics/W23_D3_real_power.md` flags D2 as "not yet on `main` (no `W23_D2_*` commit, no `/tmp/W23_D2_*.json`)" and is operating on a seeded stub of 5 random F1 values rather than real data. There is therefore no pre-fix PR-013 F1 in the diagnostics tree to compare against. What we can say:

- **W24 post-fix F1 (this run): 0.192** with 3 exact_code matches out of 6 concerns.
- **Without the 67f7492 fix**, every match in this paper would have collapsed to either `category` (diagnostic-only, doesn't count) or `none`, because pre-fix `_concern_to_flag` emitted `concern.get("concern_id")` (e.g. `PR-019-C02`) as `code`, and no reviewer `mlgg_gates` list contains that. Expected pre-fix F1 ≈ 0.0 (0 matches × MEDIUM/LOW = 0 wTP; the 6 concerns yield wFN = 1+2+2+1+1+0.5 ≈ 7.5; same 17.0 wFP).
- **Delta interpretation:** the lexical-path fix is necessary but not sufficient. It moves PR-013 from ~0 → 0.19, which is the entire signal magnitude the matcher's exact_code+code_prefix tiers can produce without an embedder. Closing the rest of the gap requires either (i) injecting an embedder so semantic-tier matches catch the HIGH reproducibility miss, (ii) tightening the RAG retrieval with paper-domain context so external-validation/cohort over-flags drop, or (iii) raising `top_k` beyond 20 with a precision filter so a `seed_stability_gate`-coded flag has a chance to surface.

## Provenance

- Raw run output (queries, all 20 flags, full match record, score breakdown, coverage): `/tmp/W24_PR-013_run.json` (ephemeral; not committed).
- Code paths exercised: `scripts.rag.query.rag_query` (top_k=20), `scripts.rag.evals.ncpr_paper_runner.synthesize_flags_from_rag`, `scripts.rag.evals.ncpr_matcher.match_all` (embed_fn=None), `scripts.rag.evals.ncpr_severity_score.per_paper_score`, `scripts.rag.evals.ncpr_category_coverage.category_coverage`, `scripts.rag.evals.ncpr_paper_card.make_paper_card`.
- Hard rules honored: read-only on everything except this file; no sub-agents; no embedder injection (semantic tier honestly skipped).
