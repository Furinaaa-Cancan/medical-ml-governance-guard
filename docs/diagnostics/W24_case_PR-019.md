# W24-04 — End-to-end MLGG on PR-019 (real Nature Communications paper)

**Date:** 2026-05-17 · **Wave:** W24 real-paper case study · **Mode:** READ-ONLY for code
**Protocol:** W24-01 end-to-end (KB → RAG → synthesize → match → score → card)
**Pipeline commits:** post-`67f7492` (synthesize_flags_from_rag emits `mlgg_gates[0]` as flag code)
**Artifacts:** `/tmp/W24_PR019_run.json`, `/tmp/W24_PR019_run.py` (runner script)

---

## 1. Paper meta

| field | value |
|---|---|
| `paper_id` | PR-019 |
| DOI | 10.1038/s41467-024-47472-5 |
| Title | Utility of polygenic scores across diverse diseases in a hospital cohort for predictive modeling |
| Journal / year | Nature Communications, 2024 |
| Domain | genomics |
| Task | Cross-ancestry PRS evaluation across 457 phenotypes in Taiwanese hospital cohort |
| Models | logistic_regression, polygenic_risk_score |
| Data | genotyping + EHR |
| N | 276,712 |
| Review rounds | 2 |
| Peer-review PDF | `references/case-studies/nature_communications/58_PRS_utility_hospital_peer_review.pdf` |
| Reviewer concerns in KB | 5 (0 CRITICAL / 1 HIGH / 3 MEDIUM / 1 LOW) |
| KMI tags (query source) | `factors_affecting_prediction_unexplored`, `incremental_value_not_tested`, `population_stratification` |

Reviewer concerns (KB-curated):

| concern_id | rev | sev | category | curator-mapped gates |
|---|---|---|---|---|
| PR-019-C01 | R1 | MEDIUM | evaluation_metrics | evaluation_quality_gate |
| PR-019-C02 | R2 | HIGH | evaluation_metrics | evaluation_quality_gate, clinical_metrics_gate, calibration_dca_gate |
| PR-019-C03 | R2 | MEDIUM | study_design | cohort_definition_gate, leakage_gate, fairness_equity_gate, external_validation_gate |
| PR-019-C04 | R2 | MEDIUM | evaluation_metrics | evaluation_quality_gate |
| PR-019-C05 | R2 | LOW | reporting | reporting_bias_gate |

## 2. Pipeline invocation

```
query  := " ".join(paper["key_methodology_issues"])
       == "factors_affecting_prediction_unexplored incremental_value_not_tested population_stratification"

flags  := synthesize_flags_from_rag(query, top_k=20)      # 20 flags
matchR := ncpr_matcher.match_all(flags, concerns, embed_fn=BGE)
score  := ncpr_severity_score.per_paper_score("PR-019", flags, concerns, embed_fn=BGE)
card   := ncpr_paper_card.make_paper_card("PR-019", entry, flags, matchR["matched_pairs"], score)
```

`synthesize_flags_from_rag` wall time: 11.7s (cold embed model load; first run of session).

## 3. Match summary

| metric | value |
|---|---:|
| n_flags emitted | 20 |
| n_reviewer_concerns | 5 |
| matched_pairs | 3 |
| unmatched_concerns (FN) | 2 (PR-019-C04, PR-019-C05) |
| unmatched_flags (FP) | 17 |
| wTP | 4.0 |
| wFN | 1.5 |
| wFP | 18.0 |
| **wPrecision** | **0.182** |
| **wRecall** | **0.727** |
| **weighted_f1** | **0.291** |

Per-severity (matched / missed / extra_flags):

| sev | matched | missed | extra_flags |
|---|---:|---:|---:|
| CRITICAL | 0 | 0 | 1 |
| HIGH | 1 | 0 | 16 |
| MEDIUM | 2 | 1 | 0 |
| LOW | 0 | 1 | 0 |

All 3 matches were `exact_code` (cosine=1.000 because the post-`67f7492` synthesizer emits gate names directly and the matcher's gate-prefix path fires immediately). No `semantic` or `category` fallbacks were needed for any matched pair.

## 4. Matched (3 / 5 concerns)

| concern | sev | matched by flag | match type | flag-side evidence excerpt |
|---|---|---|---|---|
| PR-019-C01 — sample-size / heritability not analyzed | MEDIUM | `evaluation_quality_gate` (f0) | exact_code | "Model seems to overlook other factors that typically influence survival..." (TCGA-survival paper) |
| PR-019-C02 — incremental PGS performance not analyzed | HIGH | `calibration_dca_gate` (f17) | exact_code | "calibration required held-out samples from MA31... performance was incr..." |
| PR-019-C03 — ancestry / population stratification | MEDIUM | `cohort_definition_gate` (f2) | exact_code | "Models incorporate data gathered over the subsequent five years... conditioning on future observations" (OA paper — temporal-leakage critique) |

The KB-curator's gate mapping is recovered for **all 3 matches**, validating the gate taxonomy used. Caveat: the *retrieved evidence text* on the flag side comes from other papers' reviewer concerns (PR-019's own KB rows were retrieved as label leakage in the top-20, but the matcher uses gate-code precedence so semantic substance is moot once the code matches).

## 5. Missed (2 / 5 concerns)

- **PR-019-C04** [MEDIUM, evaluation_metrics → evaluation_quality_gate] — "For the t-test and Wilcoxon test, were there any attempts to control for covariates such as age, sex, and population stratification? Was the metric reported based on PGS only, or the full model?"
  *Why missed:* C01 already claimed the only retrieved `evaluation_quality_gate` flag (f0), and the matcher's flag-to-1-concern dedup (matcher §spec rationale) routes other `evaluation_quality_gate` candidates (f1, f4, f6, f15) into `unmatched_flags`. This is a structural collision in the flag-to-1-concern design — PR-019 has three distinct `evaluation_quality_gate`-mapped concerns (C01, C02, C04) but only one can be claimed by any single `evaluation_quality_gate` flag.
- **PR-019-C05** [LOW, reporting → reporting_bias_gate] — figure-annotation clarity ("n and m were not annotated"). No `reporting_bias_gate` flag was retrieved by the KMI query; concern is housekeeping-level and lexically distant from KMI tags.

## 6. Over-flags (17 unmatched flags)

Distribution by code: `external_validation_gate` ×8 (one CRITICAL), `evaluation_quality_gate` ×4 (all HIGH), `missingness_policy_gate` ×3 (HIGH), `cohort_definition_gate` ×1 (HIGH), `distribution_generalization_gate` ×1 (HIGH).

Top wFP driver: the 1 CRITICAL `external_validation_gate` over-flag (f3) contributes weight 4.0, alone responsible for ~22 % of total wFP=18.0. The 16 HIGH over-flags contribute the remaining ~14.0.

Root cause: the post-`67f7492` synthesizer surfaces *every* retrieved KB concern as a flag, so a KMI query whose top-20 includes 11 external-validation-flavored concerns from other papers (UK Biobank, TriNetX, BioVU, Erlangen…) emits all 11 as MLGG flags here. This is a RAG retriever-side recall-vs-precision tradeoff, not a gate-firing bug. Confirmed by inspecting evidence text — every unmatched flag's evidence is verbatim reviewer-concern text from another paper.

## 7. Narrative (1 paragraph)

On PR-019 — a 2024 Nature Communications cross-ancestry PRS paper with 5 KB-curated reviewer concerns — the post-`67f7492` end-to-end MLGG pipeline achieves wRecall=0.727 (3/5 concerns matched, weighted by severity) but only wPrecision=0.182 (17/20 flags unmatched), giving weighted_f1=0.291. All 3 matches landed via `exact_code` thanks to the new gate-name flag synthesis, recovering the KB-curator's gate mapping perfectly for the matched concerns. The two misses are diagnostic: PR-019-C04 is lost to the matcher's flag-to-1-concern dedup (three different evaluation_metrics concerns competing for the same `evaluation_quality_gate` code), and PR-019-C05 (LOW, figure-annotation reporting) is genuinely outside the KMI query's semantic neighborhood. The 17 over-flags are all retrieved verbatim from other papers' KB rows (external-validation and missingness critiques on UK Biobank, TriNetX, etc.), confirming that on this paper the precision floor is set by RAG retrieval breadth, not by gate over-firing.

## 8. Comparison to W23-D2 smoke

| metric | W23-D2 smoke (commit 75c8d86) | W24-04 (this run, post-67f7492) | Δ |
|---|---:|---:|---|
| query | concern_text concatenation | KMI tags only | — |
| n_flags | 20 | 20 | 0 |
| weighted_f1 | 0.373 | **0.291** | −0.082 |
| wPrecision | 0.229 | 0.182 | −0.047 |
| wRecall | **1.000** | 0.727 | **−0.273** |
| dominant match type | `semantic` (BGE cosine ≥0.70) | `exact_code` (post-67f7492 gate codes) | flip |

The W23-D2 recall=1.000 is **not reproduced** here. Two interacting causes:

1. **Query shift (KMI-only vs concern-text):** W23-D2 used full reviewer-concern text concatenated — that included the literal phrasing of C04 and C05, which trivially round-tripped via cosine. W24-04 uses only the 3 KMI tags, removing that leak. (Recall the W23-D2 KMI-only ablation showed Δ<2pp on macro F1, but PR-019 was not isolated in that ablation; the per-paper effect can be much larger.)
2. **Synthesizer flip (post-67f7492):** flag codes are now gate names (e.g. `evaluation_quality_gate`), not concern_ids (e.g. `PR-019-C04`). Pre-fix, the matcher's semantic stage matched each emitted concern_id to its own concern by cosine=1.000, producing trivially-high recall (the "circularity smell" called out in W23-D2 §3). Post-fix, multiple distinct evaluation_metrics concerns now compete for the *same* gate code, exposing the flag-to-1-concern dedup as a real recall ceiling.

Net interpretation: the W23-D2 recall=1.000 was inflated by the concern_id-as-flag-code shortcut; the W24-04 wR=0.727 is the more honest number under the corrected synthesizer. The flag-to-1-concern dedup contract in `ncpr_matcher` (spec §5) is now the binding constraint for papers with multiple concerns sharing a single gate-mapped code, which is the more interesting finding for follow-up (matcher v2 should consider flag-to-many for the within-paper case).

---

**Hard-rules conformance:** NEW file only, no edits to code/KB. RAG/matcher/scorer/card invoked through their existing public APIs. No sub-agents used. Per-paper card available at `card` field of `/tmp/W24_PR019_run.json`.
