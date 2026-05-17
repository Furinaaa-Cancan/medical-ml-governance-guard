# W24-09 Case Study: PR-EXP-0097 (real Nature Communications paper)

End-to-end MLGG run on a published peer-review case from
`references/case-studies/peer-review-kb.json`, following the W24-01
protocol (PDF-less variant: query synthesized from the KB entry's
`prediction_task`, concern `tags`, and the first ~120 chars of each
`concern_text`, since this entry has no `key_methodology_issues`
field — the same fallback W22-V2 documented).
The post-67f7492 `synthesize_flags_from_rag` fix is in force
(uses `mlgg_gates[0]` instead of `concern_id` for flag codes).

## Paper meta

| Field | Value |
|---|---|
| Paper ID | PR-EXP-0097 |
| DOI | 10.1038/s41467-025-61329-5 |
| Title | The Helicobacter pylori AI-clinician harnesses artificial intelligence to personalise H. pylori treatment recommendations |
| Journal | Nature Communications (2025) |
| Domain | clinical_tabular — treatment-recommendation RL on H. pylori cohort |
| Prediction task | Clinical outcome prediction (eradication therapy success) |
| Reviewer concerns | 14 (3 CRITICAL, 4 HIGH, 7 MEDIUM) across 2 rounds — all resolved |
| Query seed | `prediction_task` + concern `tags` (de-duplicated) + first ~120 chars of each `concern_text` (no `key_methodology_issues` field on this entry) |
| MLGG-coverage caveat | In-modality (clinical tabular, binary success/fail outcome) — sits inside MLGG's declared scope, so this is a representative case rather than a stress test. |

Query passed to `rag_query` (`top_k=20`, 2,309 chars total) — abridged:

> Task: Clinical outcome prediction (Nature Comm 2025). Key methodology
> issues: antibiotic exposure baseline; external independent validation;
> feasibility only; feature list undisclosed; mi claim compliance; missing
> comparison group; missing data handling undocumented; multi center
> validation; no external validation initially; pre specified outcome
> missing; reporting guideline adoption; temporal validation; tripod
> compliance. Concerns: [first 120 chars of each of the 14 concerns...]

## Match summary

| Metric | Value |
|---|---|
| Flags synthesized | 20 |
| Reviewer concerns | 14 |
| Matched pairs (all `exact_code`) | 4 |
| Unmatched flags (over-flags / FP) | 16 |
| Unmatched concerns (misses / FN) | 10 |
| Weighted **F1** | **0.333** |
| Weighted precision | 0.333 |
| Weighted recall | 0.333 |
| Category coverage | n/a (matcher returned no `category` pairs) |
| Matcher | W22-X1 `ncpr_matcher.match_all` (real, not stub) |

Per-severity breakdown:

| Severity | Matched | Missed | Extra flags |
|---|---|---|---|
| CRITICAL | 1 | 2 | 2 |
| HIGH | 2 | 2 | 14 |
| MEDIUM | 1 | 6 | 0 |
| LOW | 0 | 0 | 0 |

## Matched (4)

| Concern | Reviewer severity | Matched by gate | Type | Score |
|---|---|---|---|---|
| PR-EXP-0097-C01 — feasibility only / no external validation / no comparison group | CRITICAL | `cohort_definition_gate` | exact_code | 1.00 |
| PR-EXP-0097-C06 — full diagnostic metric panel (sens/spec/PPV/NPV/PLR/NLR/AUROC) required | HIGH | `evaluation_quality_gate` | exact_code | 1.00 |
| PR-EXP-0097-C09 — DQN choice unjustified, no baseline comparison (RF/SVM) | HIGH | `model_selection_audit_gate` | exact_code | 1.00 |
| PR-EXP-0097-C13 — train/test split-ratio sensitivity (70/30, 80/20) | MEDIUM | `split_protocol_gate` | exact_code | 1.00 |

## Missed (10)

| Concern | Severity | Why MLGG missed |
|---|---|---|
| PR-EXP-0097-C02 — undefined pre-specified outcome, feature list withheld, missing-data policy undocumented | MEDIUM | Maps to `missingness_policy_gate` + `reporting_bias_gate` (dim 8). De-duplication pushed reporting-bucket flags to losing positions; the only `reporting_bias_gate` hits that surfaced rode TRIPOD evidence text, but the matcher's best-flag-per-concern pass routed them elsewhere. |
| PR-EXP-0097-C03 — external validation on independent multi-center cohort | CRITICAL | The query *did* retrieve 3× `external_validation_gate` flags (idx 3, 15, 17), but none was assigned to C03 by the matcher's one-flag-per-concern de-duplication. All three carried evidence from unrelated oncology / EHR / NLP cohorts, so semantic similarity to C03's plain-text recommendation did not clear the threshold for a non-exact-code rescue. Real FN. |
| PR-EXP-0097-C04 — TRIPOD / MI-CLAIM checklist compliance | MEDIUM | Gates `execution_attestation_gate` + `reporting_bias_gate`; no synthesized flag carried evidence specifically about reporting-guideline checklists. KB-content gap rather than matcher failure. |
| PR-EXP-0097-C05 — ground-truth label accuracy (eradication success when only one therapy was given per subject) | HIGH | Outcome-definition / label-noise concern. No matched flag retrieved on ground-truth-labelling exemplars; one of the over-flags (idx 6) is conceptually adjacent (`cohort_definition_gate` on responder/non-responder ground truth) but it was assigned to no concern by de-dup. |
| PR-EXP-0097-C07 — broken Bitbucket link / reproducibility | HIGH | Reproducibility / code-availability concern (dim 11). No `code_artifact_gate` / repo-availability flag in top-20; KB retrieval missed this neighborhood entirely. |
| PR-EXP-0097-C08 — "real-world data" claim contradicted by simulation-only experiments | CRITICAL | Data-provenance / study-design concern. Closest neighbors in the top-20 are `cohort_definition_gate` hits, but none carries simulation-vs-real evidence text. Genuine retrieval gap. |
| PR-EXP-0097-C10 — noise-injection mechanics (bit-flipping?) and 72%-accuracy-at-99%-noise plausibility | MEDIUM | Methodological-detail concern with no analogue in the KB exemplar pool. Not retrieved. |
| PR-EXP-0097-C11 — unclear study goal, undefined metrics, ambiguous 65.5% statistic | MEDIUM | Reporting-clarity concern; same `reporting_bias_gate` neighborhood as C02/C04 and same de-dup loss pattern. |
| PR-EXP-0097-C12 — 92.8% vs 87.4% effect size too small to claim "outperformed" | MEDIUM | Statistical-claim-strength concern; closest neighbor would be an over-claim / effect-size gate. None of the 20 synthesized flags carried that signature. |
| PR-EXP-0097-C14 — DQN-only method development, no comparison to alternatives | MEDIUM | Conceptually overlaps with C09 (already matched to `model_selection_audit_gate`); the matcher's one-concern-per-flag rule prevents a second match on the same gate code. |

## Over-flags (16)

Concentrated across the same buckets the matched gates live in, dominated by HIGH-severity false alarms:

- **5x `cohort_definition_gate`** (1x CRITICAL, 4x HIGH) — pulled from
  imaging (ATTRwt-CM cases/controls, responder/non-responder
  determination), Tri-AI segmentation choice ambiguity, GP-records
  sub-cohort selection, and breast-cancer ground truth. None
  paper-specific.
- **3x `external_validation_gate`** (1x CRITICAL, 2x HIGH) — PLCO cohort
  publication-readiness, Multi-Domain Sentiment generalization,
  TriNetX. The CRITICAL ("model has not been externally validated…")
  is the one C03 *should* have caught but did not, due to evidence-text
  mismatch with the H. pylori external-validation framing.
- **3x `evaluation_quality_gate`** (HIGH) — PPV/NPV diagnostic
  endpoints, "proof of principle" language drift, GPT-4-generated
  unit-test critique. Topic drift.
- **Singletons (all HIGH):** `calibration_dca_gate` (clinical-impact
  null result), `sample_size_gate` (cancer-subtype imbalance),
  `split_protocol_gate` (DILImap CV ambiguity),
  `model_selection_audit_gate` (CV-folds undocumented),
  `clinical_metrics_gate` (VME rate for AMR), `leakage_gate`
  (manual-annotation ground-truth temporality).

The two CRITICAL over-flags (`external_validation_gate` and
`cohort_definition_gate`) are the most consequential surface: both
are plausibly *true* failures for the PR-EXP-0097 paper, but the
matcher cannot certify this because the evidence text comes from
unrelated KB exemplars rather than from the paper itself. A
downstream consumer would have to manually re-ground them.

## Narrative

PR-EXP-0097 is an in-modality clinical-tabular case (treatment-policy
RL on H. pylori eradication). MLGG produced symmetric precision and
recall at 0.33, with a weighted F1 of 0.333. The four matched
concerns are the high-confidence wins (`cohort_definition_gate` →
C01, `evaluation_quality_gate` → C06, `model_selection_audit_gate` →
C09, `split_protocol_gate` → C13), all on exact-code matches. The
10 misses split into three failure modes: (1) one-flag-per-concern
de-duplication starves the reporting bucket (C02, C04, C11) where
several flags compete for the same `reporting_bias_gate` slot;
(2) genuine KB-content gaps for ground-truth-accuracy (C05),
code-repo-availability (C07), simulation-vs-real-data (C08),
noise-injection mechanics (C10), and effect-size over-claim (C12);
and (3) C03's external-validation miss is the most diagnostic — the
relevant gate fired three times in the flag pool but none of those
flags carried H. pylori-specific evidence, so the matcher's de-dup
withheld it from C03. This is the same precision-failure pattern
W23-D5 / W24-03 documented: retrieval finds the right gate, but
evidence-text fidelity collapses on out-of-distribution surface
text. The 14-vs-20 cardinality means upper-bound recall was capped
at 14/14 even before de-dup; the actual 4/14 = 29% raw recall is
materially below the W24-03 PR-018 anchor (3/5 = 60%) and confirms
that high concern-count papers (≥10) stress the matcher's
deduplication discipline harder than small-N papers.

## Compare to W24-03 PR-018 anchor

| Metric | PR-EXP-0097 (this run) | PR-018 (W24-03) |
|---|---|---|
| Concerns | 14 | 5 |
| Flags | 20 | 20 |
| Matched | 4 | 3 |
| F1 / P / R | 0.333 / 0.333 / 0.333 | 0.288 / 0.184 / 0.667 |
| Category coverage | n/a (none reported) | 3/3 |
| CRITICAL recall | 1/3 | n/a (no CRITICAL concerns) |

PR-EXP-0097 has higher precision (0.33 vs 0.18) because its 14
concerns absorb more of the 20 flags as plausible candidates, but
recall halves (0.33 vs 0.67) because the cardinality gap (14 vs 5)
and the one-flag-per-concern de-dup combine to leave 10 unmatched.
The structural lesson: NCPR's current matcher rewards small-N
papers and penalises rich peer-review traces, which is the
opposite of what a publication-grade benchmark should incentivise.

## Reproducibility

- Run date: 2026-05-17
- Pipeline: `rag_query(top_k=20)` → `synthesize_flags_from_rag` (post-67f7492) → `ncpr_matcher.match_all` → `ncpr_severity_score.per_paper_score` → `ncpr_paper_card.make_paper_card`
- Source entry: `references/case-studies/peer-review-kb.json` → `entries[id=PR-EXP-0097]`
- Query construction: `prediction_task` + sorted-deduped concern `tags` + first 120 chars of each `concern_text` (this KB entry has no `key_methodology_issues` field; fallback per W22-V2 §"methods_text missing")
