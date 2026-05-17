# MLGG-Bench v1.0.2 — OOD CP-Relabel PATCH

| Field | Value |
|---|---|
| Version | 1.0.2 |
| Release date | 2026-05-17 |
| Change type | PATCH (gold-label refinement on OOD slices) |
| Builds on | v1.0.1 (`../MLGG-Bench-v1.0.1/`) |
| Files changed | `all_scenarios.json` — 32/40 OOD CP labels updated; 2 set to empty per `no_good_fit` finding |

## What changed

v1.0.1 only re-audited indist_155. v1.0.2 applies the same full-pass CP-relabel methodology to all 4 OOD slices (40 scenarios). The agent honoured an honest "no_good_fit" verdict for cases where no existing CP in the 49-CP set matches the scenario, rather than forcing a bad gold.

**Per-slice change distribution:**

| Slice | n | unchanged | refined | expanded | replaced | no_good_fit |
|---|---|---|---|---|---|---|
| ood_01 Retraction Watch | 10 | 1 | 4 | 1 | 3 | 1 |
| ood_02 OpenReview | 10 | 7 | 1 | 1 | 1 | 0 |
| ood_03 TRIPOD+AI/PROBAST+AI | 10 | **0** | 0 | 0 | **9** | 1 |
| ood_04 F1000/eLife | 10 | 0 | 2 | 3 | 5 | 0 |
| **Total** | **40** | **8** | **7** | **5** | **18** | **2** |

ood_03's 9/10 REPLACED rate confirms `DIAGNOSIS.md` Failure 2: the agent-time CPs were systematically off-axis because the KB's 49 CPs were derived from Nature Comms peer review (mostly tabular EHR), while ood_03 pulls from meta-methodology / standards literature.

**Top REPLACED transitions:**

1. `ood03_tripod_ai_calibration_omitted_main_text`: `[CP-018, CP-027]` → `[CP-021, CP-026]` (cherry-pick / bootstrap → calibration / AUC-only)
2. `ood03_wong_epic_sepsis_internal_only_validation`: `[CP-009, CP-019]` → `[CP-008, CP-010]` (code / feature → missing-ext-val / low-PPV)
3. `ood03_zech_hospital_system_as_confounder`: `[CP-009, CP-010]` → `[CP-016, CP-022]` (code / clinical-utility → distribution-generalization + interpretability)

## Metric impact

Full 305-scenario benchmark with v3 (indist) + v4 (OOD) labels:

| Metric | v1.0 | v1.0.1 | **v1.0.2** | Δ from v1.0 |
|---|---|---|---|---|
| `mean_hit_at_k` | 0.858 | 0.858 | 0.858 | 0 |
| **`mean_cp_hit_at_k`** | **0.794** | **0.821** | **0.856** | **+0.062** |
| `n_cp_evaluable` | 252 | 252 | 250 | -2 (the 2 honest no_good_fit) |
| `coverage_rate` | 0.921 | 0.921 | 0.921 | 0 |

## CP-mint evidence — strengthened

The `would_fit_proposed_cp` field across all 40 OOD scenarios:

| Proposed CP | Description | Hits | Distribution |
|---|---|---|---|
| **CP-052** `shortcut_learning_audit_missing` | DeGrave / Zech / Maguolo style | **5** | spread across ood_01, ood_03 |
| **CP-050** `meta_checklist_underreporting` | TRIPOD+AI / PROBAST+AI items | **5** | all in ood_03 |
| **CP-051** `systematic_review_base_rate` | Wynants / Roberts / Andaur | **3** | ood_01, ood_03 |

This is stronger evidence than the ood_03-only analysis in `../MLGG-Bench-v1.0/v1.1_proposed/cp_mint_experiment.md`:
- CP-052 hits across **multiple slices** (5 cases, not just 3 anchor entries)
- CP-050 has 5 strong hits all in TRIPOD/PROBAST contexts — clean pattern
- CP-051 has 3 hits but is weakest of the three

**Updated recommendation:** mint **all 3** (CP-050, CP-051, CP-052), not just CP-052. The OOD distribution evidence is convincing enough.

## Two NEW CP gaps surfaced (v1.1 backlog)

The v4 OOD relabel also flagged 2 scenarios as `no_good_fit` that point to CPs not yet in any draft:

| Scenario | Gap | Proposed new CP |
|---|---|---|
| `ood10_springer-autism-face-bonkers-dataset` | Web-scraped Kaggle photos as ASD labels, no consent, no ethics | `CP-053 uncontrolled_dataset_provenance` (or similar — ethics/consent failure for derivative datasets) |
| `ood03_chexnet_radiologist_comparison_no_priors` | Asymmetric reader study (radiologists denied priors/laterals while algorithm has NIH labels) | `CP-054 reader_study_design_asymmetry` (STARD-AI / DECIDE-AI failure mode) |

These are well-known failure patterns in the medical AI literature but absent from our KB's 49-CP taxonomy. v1.1 / v2.0 backlog.

## Files

```
MLGG-Bench-v1.0.2/
├── README.md                          ← this file
├── all_scenarios.json                 ← 305 scenarios with v3 (indist) + v4 (OOD) CP labels
└── cp_relabel_v4_ood_changelog.json   ← per-scenario v4 change log with would_fit_proposed_cp
```

Everything else (SPEC.md, baselines, splits, runner, v1.1_proposed/) inherits from `../MLGG-Bench-v1.0/`. Run:

```bash
python3 scripts/rag/evals/run_eval.py \
  --scenarios references/retrieval_eval/MLGG-Bench-v1.0.2/all_scenarios.json \
  --top-k 5
```

## Version history summary

| Version | hit@5 | cp_hit@5 | Δ cp_hit | What |
|---|---|---|---|---|
| v1.0 | 0.858 | 0.794 | — | Initial 305-scenario release |
| v1.0.1 | 0.858 | 0.821 | +0.027 | indist_155 CP relabel (CP-Relabel v3 fullpass) |
| **v1.0.2** | 0.858 | **0.856** | **+0.035** | OOD CP relabel (CP-Relabel v4) |
| v1.1 (TBD) | TBD | TBD | — | Mint CP-050/051/052 + 30 META KB entries (pending clinical review) |

## Pending for v1.0.3 or v1.1.0

- Hand spot-audit of v4 REPLACED cases (especially ood_03's 9/10 replacement rate — that's high enough to warrant review even if mostly correct)
- CP relabel methodology on bench slices (bench_01/02/03/07) — currently still carrying agent-original labels
- 2 newly-identified CP gaps (CP-053 dataset-provenance, CP-054 reader-study asymmetry) — needs methodology expert to confirm the gaps are real and worth minting
- v1.1.0 itself: mint CP-050/051/052 + accept 30 META entries (clinical review pending)
