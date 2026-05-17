# v1.1 Draft Meta-Methodology KB Entries — Reviewer Document

**Provenance:** every entry is marked `_provenance: "LLM-DRAFT-v1.1-pending-clinical-review"`. Per project disease-KB provenance rule (memory: `project_disease_kb_provenance`), nothing here may be promoted to `references/case-studies/peer-review-kb.json` without clinical-methodologist sign-off.

**Output files:**
- `/tmp/mlgg_benchmark/v1.1_draft_meta_entries.json` — 30 meta-entries + 1 proposal sidecar (CP / tag / category proposals)
- `/tmp/mlgg_benchmark/v1.1_draft_meta_entries.md` — this document

**Counts:**
- 30 real meta-entries, 31 reviewer_concerns total
- Source breakdown: TRIPOD+AI 11, PROBAST+AI 8, STRATOS/Van Calster 4, systematic-reviews 4, landmark-anchor 3
- 1 proposal sidecar (`META-PROPOSED-CP`) holds the proposed CP-050/051/052, 14 new tags, and 1 new category

---

## 1. Why each entry is needed (ood_03 retrieval coverage map)

The 10 ood_03 queries (`/tmp/mlgg_ood/agent_03.json`) failed at `cp_hit@5 = 0.20`. The diagnosis (`DIAGNOSIS.md` Failure 2) says: KB has only paper-specific concerns, so the meta-checklist queries cannot match. Each draft entry below targets at least one ood_03 query.

| ood_03 scenario | Primary new entry that should match | Backup matches |
|---|---|---|
| `ood03_tripod_ai_calibration_omitted_main_text` | META-TRIPOD-001 (item 19a/19b calibration) | META-STRATOS-002 (Van Calster calibration), META-PROBAST-006 |
| `ood03_probast_ai_proxy_outcome_no_gold_standard` | META-PROBAST-003 (Outcome domain) | META-SR-001 (Wynants 2020 COVID proxy outcomes) |
| `ood03_roberts_frankenstein_dataset_pediatric_controls` | META-SR-002 (Roberts 2021 systematic review) | META-PROBAST-001 (Participants), META-PROBAST-008 (AI shortcut) |
| `ood03_degrave_shortcut_learning_laterality_markers` | META-ANCHOR-001 (DeGrave shortcut) | META-PROBAST-008 (AI-specific shortcut SQs) |
| `ood03_zech_hospital_system_as_confounder` | META-ANCHOR-002 (Zech 2018) | META-PROBAST-007 (applicability), META-TRIPOD-010 (external validation) |
| `ood03_wong_epic_sepsis_internal_only_validation` | META-ANCHOR-003 (Wong 2021 Epic) | META-TRIPOD-010, META-PROBAST-007 |
| `ood03_riley_sample_size_epv_violation_ml` | META-SR-004 (Riley 2020 minimum sample size) | META-TRIPOD-002 (item 8), META-PROBAST-004 (Analysis domain SS) |
| `ood03_chexnet_radiologist_comparison_no_priors` | META-TRIPOD-003 (intended use / reader study) | META-TRIPOD-009 (clinical utility) |
| `ood03_christodoulou_ml_vs_lr_no_real_gain` | META-STRATOS-004 (Christodoulou 2019) | META-TRIPOD-008 (model development) |
| `ood03_van_calster_2025_auroc_only_classification_improper` | META-STRATOS-001 (TG6 improper scoring) | META-STRATOS-003 (DCA), META-PROBAST-006 |

Coverage check: every ood_03 scenario gets at least one primary + one backup meta-entry whose `concern_text` and `tags` lexically overlap the scenario's `query_text` and `expected_tags`. This should lift cp_hit@5 substantially once the entries enter the BM25/BGE index.

Additional entries that don't map 1-to-1 to a current ood_03 query (added to round out the TRIPOD+AI / PROBAST+AI surface for future OOD slices):
- META-TRIPOD-004 (fairness item 21)
- META-TRIPOD-005 (item 24 code/data/model availability)
- META-TRIPOD-006 (uncertainty quantification item 17/18)
- META-TRIPOD-007 (participants / data source items 5a-5d)
- META-TRIPOD-011 (missing-data handling items 7a-7c)
- META-PROBAST-002 (Predictors domain — target leakage / temporal leakage)
- META-PROBAST-005 (Analysis domain — tuning leakage)
- META-SR-003 (Andaur Navarro PROBAST living review)

---

## 2. Proposed new canonical patterns (CP-050 … CP-052)

Existing 49 CPs are paper-level. The meta tier needs at least one CP that *names* the meta-level concept, otherwise the relabel pass will keep collapsing meta-entries onto whichever paper-level CP looks closest.

| Proposed CP | Name | Why it's distinct from existing 49 | Best-fit gates |
|---|---|---|---|
| **CP-050** | `meta_checklist_underreporting` | None of the existing 49 CPs is about "the paper fails a named TRIPOD+AI / PROBAST+AI checklist item". CP-004 (reporting) and CP-018 (evaluation metrics) overlap but are paper-level. CP-050 lets meta-entries cluster at retrieval. | `reporting_bias_gate`, `evaluation_quality_gate` |
| **CP-051** | `systematic_review_base_rate` | Captures the Wynants / Roberts / Andaur / Christodoulou kind of evidence: "this is the rule, not the exception" — a base-rate prior, not a paper-specific concern. No existing CP carries this semantics. | `reporting_bias_gate`, `external_validation_gate` |
| **CP-052** | `shortcut_learning_audit_missing` | DeGrave 2021 / Roberts 2021: imaging papers without a saliency / counterfactual perturbation audit. Currently meta-entries point to CP-022 (interpretability) and CP-037 (leakage), which are both reasonable but neither names the absent-audit failure mode. | `shap_interpretability_gate`, `leakage_gate` |

**Why I did NOT assign CP-050/051/052 to the 30 entries above:** until a clinical reviewer confirms the proposed CPs, I mapped every entry to the best-fitting existing CP (mostly CP-004, CP-007, CP-008, CP-010, CP-018, CP-021, CP-022, CP-024, CP-026, CP-029, CP-045, CP-046, CP-047). If CP-050/051/052 are accepted, a one-shot relabel pass should move:
- META-TRIPOD-001/002/003/004/005/006/007/008/009/010/011 → CP-050 (or keep dual mapping)
- META-PROBAST-001…008 → CP-050
- META-SR-001/002/003/004, META-STRATOS-004 → CP-051
- META-ANCHOR-001 (DeGrave) → CP-052

---

## 3. Proposed new tags (14)

These do not exist in the current KB tag vocabulary; flag for taxonomy review before promotion.

| Tag | Used by | Rationale |
|---|---|---|
| `probast_ai_alignment` | all 8 META-PROBAST entries | Parallel to existing `tripod_ai_alignment`; needed to make the PROBAST+AI checklist queryable as a unit. |
| `stratos_tg6_alignment` | META-STRATOS-001/002/003 | STRATOS Topic Group 6 (Van Calster) is the de-facto standard for metric reporting; tag enables filtering. |
| `uncertainty_quantification_missing` | META-TRIPOD-006, META-SR-001 | Named TRIPOD+AI item 17/18 concept; not covered by `no_confidence_intervals` (which is narrower). |
| `intended_use_case_unclear` | META-TRIPOD-003 | TRIPOD+AI item 13 concept; not covered by `clinical_workflow_unclear` (narrower). |
| `model_availability_unclear` | META-TRIPOD-005 | TRIPOD+AI item 24 concept; complements existing `code_unavailable`. |
| `fairness_reporting_missing` | META-TRIPOD-004 | TRIPOD+AI item 21 concept; complements existing `no_subgroup_analysis`. |
| `meta_checklist_item` | all 30 entries | Single marker so meta-entries are filterable as a stratum. **High priority.** |
| `systematic_review_finding` | META-SR-001/002/003/004, META-STRATOS-004, META-ANCHOR-001 | Marks base-rate evidence from systematic reviews vs single-paper concerns. |
| `high_risk_of_bias_prevalence` | META-SR-001/002/003 | Captures the "n% of audited papers were high-RoB" wording. |
| `improper_scoring_rule` | META-STRATOS-001, META-PROBAST-006 | Van Calster 2025 vocabulary; complements existing `auc_alone_insufficient`. |
| `pmsampsize_missing` | META-TRIPOD-002, META-PROBAST-004, META-SR-004 | Named tool / methodology Riley 2020 endorses; needed for ood_03 sample-size query. |
| `riley_minimum_violated` | META-TRIPOD-002, META-PROBAST-004, META-SR-004 | Direct lexical anchor for the Riley sample-size query. |
| `shrinkage_missing` | META-SR-004 | Riley / Christodoulou concept; not covered by existing tags. |
| `test_set_tuning` | META-PROBAST-005 | Christodoulou 2019 vocabulary; ML-specific leakage. |

---

## 4. Proposed new category and domain

| Proposal | Rationale |
|---|---|
| **category: `meta_methodology`** | None of the existing 13 categories fits "this entry is about a checklist item or a systematic-review finding rather than a single paper's bug". I retained existing categories (`evaluation_metrics`, `sample_size`, etc.) in each `concern.category` field for backward compatibility, but a top-level `meta_methodology` category would help the relabel pass and the benchmark stratification. |
| **domain: `methodology`** | None of the existing 46 domains fits a TRIPOD+AI guideline document or a systematic review. I used `domain: "methodology"` consistently; clinical reviewer should confirm. |
| `is_cohort_retrospective_binary: null` | Standards documents and systematic reviews are not cohort papers; null is the only honest value. (Confirm null is acceptable in the schema — current KB shows the field for paper-level entries; should clarify whether downstream gates tolerate null here.) |

---

## 5. Open questions for clinical reviewer

1. **CP scope:** are CP-050 / CP-051 / CP-052 the right granularity, or should each TRIPOD+AI domain (Participants / Predictors / Outcome / Analysis / Other-information) get its own CP? My instinct is no — that would mirror PROBAST+AI's structure and might be more useful but pushes the CP count from 49 → 60+, which the bench_06 IRR work already flagged as overweight.

2. **Source-document DOIs:** PROBAST+AI 2025 (Moons/Collins) is cited as `BMJ 2025;388:e082505`; if the actual DOI when published differs, every META-PROBAST entry needs updating. **Action: clinical reviewer to verify final DOI on publication.**

3. **Are landmark papers (META-ANCHOR-001/002/003 — DeGrave, Zech, Wong) really meta-entries?** They are paper-level, but TRIPOD+AI and PROBAST+AI explicitly cite them as canonical exemplars. The Failure-2 diagnosis recommends adding them as "anchors" (fix (c) in the diagnosis table). I kept them in this batch because ood_03 queries `_03_zech_*`, `_03_wong_*`, `_03_degrave_*` need them. **Alternative:** move them to a separate "anchor" batch with full paper-level metadata (sample size, methodology, etc.) instead of methodology-pseudo-domain stubs.

4. **Andaur Navarro 2021 DOI** (META-SR-003): I cited `10.1136/bmjopen-2020-048008` (study-protocol DOI for the living review). The most-cited Andaur Navarro audit is actually the 2023 J Clin Epidemiol paper — please confirm the correct primary citation.

5. **`mlgg_dimension` values:** I assigned `mlgg_dimension` 1-9 by analogy with existing entries (1=study_design, 2=sample_size, 3=preprocessing, 4=model_selection, 5=evaluation_metrics, 6=interpretability, 7=external_validation, 8=fairness, 9=reporting/utility). Existing KB has mixed conventions — please confirm.

6. **Are the proposed tags overlapping existing ones too much?** Particularly `fairness_reporting_missing` vs existing `no_subgroup_analysis`, and `uncertainty_quantification_missing` vs `no_confidence_intervals`. I leaned toward adding the more general tag because TRIPOD+AI vocabulary is broader, but a tag-merge pass might collapse them.

7. **Promotion path:** once approved, who runs the patch and where? The `_provenance` marker should be preserved on promoted entries so that any future audit can identify LLM-drafted material. Suggest a `change_log` entry like `"v1.1 — added 30 LLM-drafted meta-methodology entries, clinical-reviewed YYYY-MM-DD by <name>"`.

---

## 6. What was NOT done (explicitly out-of-scope)

- Did not modify `references/case-studies/peer-review-kb.json` (project NEVER rule #1).
- Did not test these entries against the actual RAG to measure expected cp_hit@5 lift; that requires the index rebuild and benchmark rerun, which is a separate work item.
- Did not draft the `meta_critique_gate` proposed as fix (b) in the diagnosis — that's a code/routing change, not a KB change, and is its own v1.1 work item.
- Did not enumerate every TRIPOD+AI / PROBAST+AI checklist item. The 19 covered items are the ones most-relevant to ood_03 and most-frequently flagged in TRIPOD audits. A complete checklist-item coverage pass would push the entry count to ~50-60.
