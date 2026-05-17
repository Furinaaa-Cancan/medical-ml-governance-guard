# W25 Hybrid Phase 2 — Case 2: Che et al. 2018 (Scientific Reports, GRU-D Missing Values)

**Phase**: Hybrid v1 validation, Phase 2 case study #2 of 7
**Spec**: `references/benchmark/hybrid_v1_spec.md` (commit `201eef1`)
**Precedent**: Phase 1 case 1 (`docs/diagnostics/W25_hybrid_phase1_case1_yan2020_covid.md`, commit `db1d7e0`)
**Target paper**: Che Z, Purushotham S, Cho K, Sontag D, Liu Y. *Recurrent Neural Networks for Multivariate Time Series with Missing Values.* Scientific Reports 8:6085 (2018). DOI `10.1038/s41598-018-24271-9`.
**Code under test**: https://github.com/PeterChe1990/GRU-D (cloned to `/tmp/W25_p2_che`, 1,202 LoC across 7 `.py` files + 3 `.ipynb`)
**Metadata card**: `references/case-studies/specialist_journals/other/che_2018_grud_missing_values/metadata.json`
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE2 (Claude Opus 4.7)

---

## 0. Circularity caveat (read first)

The **ground truth (GT) in §3 is synthesised from the same metadata card** (`leakage_risk_assessment.notes` and `reviewer_notes.notes`) that the RAG layer's L3 query was built from in §2. Both notes fields in the GRU-D card are stub values (`"TO BE VERIFIED VIA CODE SCAN."` and `"CODE SCAN TARGET. GRU-D for clinical time series with missing values."`) — i.e. the GT is *under-specified* by design. To avoid circularity, GT for this case was augmented from **first-principles methodology audit of the cloned repo + paper context** (split protocol comes from upstream `Benchmarking_DL_MIMICIII`, no calibration / DCA / CI mentioned in the paper, single-dataset training, etc.). This is weaker than Yan 2020's GT (which had 7 documented external-replication failures and explicit numeric AUROC values in metadata); recall numbers on this case should be read with that asymmetry in mind.

---

## 1. Paper card

Che et al. 2018 (Scientific Reports) introduce **GRU-D**, a GRU variant with a **trainable exponential decay** for missing values in multivariate clinical time series. The paper's flagship empirical claim is mortality classification (and ICD-9 multi-label classification) on **MIMIC-III** and the **PhysioNet Challenge 2012** dataset, with 33 clinical variables, on the first 48 hours of ICU admissions. The reference implementation under test (`PeterChe1990/GRU-D`) is **method code**: it defines the GRU-D layer, a data loader that consumes precomputed `data.npz` + `fold.npz` artefacts, a 5-fold CV training loop, and reports a single `roc_auc_score`. There is **no calibration code, no bootstrap CI, no DCA, no external dataset, and the split is imported from an upstream benchmarking codebase** (`USC-Melady/Benchmarking_DL_MIMICIII`). Notably, the loader explicitly applies train-fold-only mean/std (`data_handler.py:115-118` and `Generate-sample-data.ipynb` cell 10) — a small but real piece of leakage hygiene that lint cannot detect at the lexical level.

The paper is in our `specialist_journals/other/` bucket (Scientific Reports is a high-volume open-access generalist) and is **not in MLGG-Bench**, so this is the second OOD test of the hybrid stack.

---

## 2. 3-layer execution log

| Layer | What ran | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_che/` | **3 findings (0 errors / 1 warning / 2 infos)** | Inspected 1,202 LoC across 7 `.py` + 3 `.ipynb`. Quiet output reflects that this is method/library code, not an end-to-end study pipeline. |
| **L2 — Gates (33 available)** | Attempted 5: `request_contract_gate`, `sample_size_gate`, `missingness_policy_gate`, `split_protocol_gate`, `external_validation_gate` | **0 / 33 gates produced a substantive audit verdict** | Each gate exits with `FAIL` on missing structured-evidence JSONs (`--evaluation-report`, `--policy-spec`, `--prediction-trace`, `--protocol-spec`, etc.). Same fail mode as Phase 1. |
| **L3 — RAG retrieval** | `synthesize_flags_from_rag(q, top_k=20)` with query built from `metadata.json` `bibliographic.title + study_design.outcome + dataset.source_name + model.model_type + dataset.missing_data_strategy` plus leakage-pattern keywords | **20 flags: 5 CRITICAL + 15 HIGH** | Codes spread across 12 gate names; categories: data_leakage 5, evaluation_metrics 3, study_design 3, preprocessing 2, sample_size 2, external_validation 1, feature_selection 1, model_selection 1, reproducibility 1, reporting 1. |

### L1 — lint R-rule breakdown (3 findings total)

| R-rule | Count | Severity | Location | What it catches |
|---|---|---|---|---|
| **R016** `KFold()` without `random_state=` | 1 | INFO | `Generate-sample-data.ipynb` cell 9 line 4 | Reproducibility — applies to *sample-data* generation only, not the real MIMIC pipeline |
| **R009** metric without CI | 1 | INFO | `Run.ipynb` cell 4 line 59 | `roc_auc_score(...)` reported as point estimate, no bootstrap |
| **R022** AUROC-only metric panel | 1 | WARNING | `Run.ipynb` cell 4 line 59 | TRIPOD+AI 2024 Item 17 — no AUPRC / calibration / MCC |

### L2 — gates that COULD NOT run, and why

Same structural failure as Phase 1. Each attempted gate hits the same wall: an external GitHub repo does not ship the structured evidence JSONs that MLGG gates require.

| Gate attempted | Missing artefact | Exit |
|---|---|---|
| `request_contract_gate` | `--request` (structured study request) | FAIL `missing_request_file` |
| `sample_size_gate` | `--evaluation-report` JSON | FAIL on file open |
| `missingness_policy_gate` | `--policy-spec` + train/test CSVs | FAIL on file open |
| `split_protocol_gate` | `--protocol-spec` + train/test CSVs + `--id-col` | FAIL on file open |
| `external_validation_gate` | `--prediction-trace` + `--evaluation-report` | FAIL on file open |

### L3 — RAG hit aggregate (top-20)

- **Severity**: 5 CRITICAL, 15 HIGH, 0 MEDIUM/LOW (richer CRITICAL fraction than Yan 2020's 2/20)
- **Category histogram**: `data_leakage:5, evaluation_metrics:3, study_design:3, preprocessing:2, sample_size:2, external_validation:1, feature_selection:1, model_selection:1, reproducibility:1, reporting:1`
- **Gate-code histogram** (from `code` field of each flag): `leakage_gate:4, cohort_definition_gate:3, missingness_policy_gate:2, sample_size_gate:2, evaluation_quality_gate:2, seed_stability_gate:1, clinical_metrics_gate:1, feature_engineering_audit_gate:1, model_selection_audit_gate:1, external_validation_gate:1, definition_variable_guard:1, reporting_bias_gate:1`
- **Stand-out top hit**: a peer-reviewer concern flagging **bidirectional RNN using future timestamps as a CRITICAL leakage pattern** — directly relevant to time-series models with retrospective windowing, and exactly the conceptual mechanism a missing-data-decay RNN can mis-use if the imputation peeks at later observations.

---

## 3. Ground truth — 7 issues (under-specified card → first-principles audit)

Synthesised from `metadata.json` (notes are stubs) + first-principles code/paper audit on `/tmp/W25_p2_che`. See §0 caveat.

| # | Severity | Issue | Evidence |
|---|---|---|---|
| GT1 | HIGH | No calibration / DCA reported | `metadata.calibration_reported=false`, `dca_reported=false`; `Run.ipynb` only calls `roc_auc_score` |
| GT2 | HIGH | No bootstrap CI on AUROC | `metadata.bootstrap_ci_reported=false`, all `*_ci_lower/upper=null`; lint R009 confirms |
| GT3 | HIGH | Single-dataset training, **no external validation** | `metadata.has_external_validation=false`, `external_cohort_description=""`; PhysioNet and MIMIC are both used as training datasets, not cross-validated externally |
| GT4 | MEDIUM | Hyperparameter tuning protocol not reported (M01 risk) | `metadata.hyperparameter_tuning="not reported"`, `tuning_set="not_reported"`; `Run.ipynb` `argparse` exposes hyperparams as CLI args with no recorded tuning split |
| GT5 | MEDIUM | Split provenance opaque — folds imported from upstream `Benchmarking_DL_MIMICIII` repo; **patient-level grouping cannot be verified from this repo alone** | `Prepare-MIMIC-III-data.ipynb` cell 8 loads `5-folds.npz` from external codebase; no `groups=` / patient-ID logic visible in this repo |
| GT6 | MEDIUM | Missing-data mechanism (decay) is the model's headline novelty but **no sensitivity analysis** on missingness patterns or comparison to simple imputation baselines on identical splits | Paper structure + `models.py` (single model class only); no ablation in this repo |
| GT7 | LOW | Reproducibility — Python 3.6 / Keras 2.2 / TF 1.7 (2018-era) and one `KFold` without `random_state` in sample-data generation | `requirements.txt`; lint R016 |

**Note**: I deliberately did **not** include "missingness policy may leak future values" as a GT issue, because code inspection of `data_handler.py` and `nn_utils/grud_layers.py` shows the decay applies only to past observed values weighted by elapsed time — this is the model's *design*, not a leak. (RAG flagged it; see over-flag table.)

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|
| **GT1** No calibration / DCA | HIGH | ✓ (R022 ×1, AUROC-only panel) | ✗ (would need `calibration_dca_gate` evidence) | ✓ (3 RAG hits cat=`evaluation_metrics`, code=`clinical_metrics_gate` + `evaluation_quality_gate` ×2) | ✓ via L1 + L3 |
| **GT2** No bootstrap CI | HIGH | ✓ (R009 ×1) | ✗ (`ci_matrix_gate` needs report) | ~ (no flag explicitly tagged "no CI", but `evaluation_quality_gate` hits transfer conceptually) | ✓ via L1 |
| **GT3** No external validation | HIGH | ✗ (out of scope for code lint) | ✗ (`external_validation_gate` needs evidence) | ✓ (1 RAG hit code=`external_validation_gate`, cat=`external_validation`) | ✓ via L3 |
| **GT4** Tuning protocol not reported (M01 risk) | MEDIUM | ✗ (lint sees CLI args but not the absence of a tuning report) | ✗ (`model_selection_audit_gate` / `tuning_leakage_gate` need spec) | ✓ (1 RAG hit code=`model_selection_audit_gate`, cat=`model_selection`) | ✓ via L3 |
| **GT5** Split provenance opaque / patient-level grouping unverifiable | MEDIUM | ✗ (split is imported from external `5-folds.npz` — lint cannot reason about that) | ✗ (`split_protocol_gate` needs `--protocol-spec` + CSVs) | ~ (`cohort_definition_gate` ×3 hits transfer conceptually but talk about case/control definitions, not patient-level CV) | ~ via L3 partial |
| **GT6** No missingness ablation / no imputation baseline | MEDIUM | ✗ | ✗ | ✓ (2 RAG hits code=`missingness_policy_gate`, cat=`preprocessing`) | ✓ via L3 |
| **GT7** Reproducibility (no `random_state` in sample-data KFold) | LOW | ✓ (R016 ×1 — but flags sample-data not real pipeline) | ✗ | ✓ (1 RAG hit code=`seed_stability_gate`, cat=`reproducibility`) | ✓ via L1 + L3 |

Legend: ✓ = caught with high confidence, ~ = partial / conceptually-adjacent only, ✗ = missed.

---

## 5. Per-layer recall + complementarity

| Metric | L1 lint | L2 gate | L3 RAG | **Hybrid** |
|---|---|---|---|---|
| Strict recall (✓ only) | 3 / 7 = **43%** | 0 / 7 = **0%** | 5 / 7 = **71%** | **6 / 7 = 86%** (strict) |
| Partial recall (✓ + ~) | 3 / 7 = **43%** | 0 / 7 = **0%** | 7 / 7 = **100%** | **7 / 7 = 100%** |
| GT items where this layer is sole catcher | 0 | 0 | **2** (GT3, GT4, GT6 — 3 actually) | n/a |
| GT items with unique evidence richness | **3** (R022, R009, R016 with file:line) | 0 | 5 (named peer-reviewer concerns) | n/a |

- **L2 = 0/7 again, replicating Phase 1**. See §6 verdict.
- **Hybrid strict recall (86%) > best single layer (L3 71%)**: in the Yan 2020 Phase 1 case, hybrid added zero recall over RAG; here the hybrid adds **+1 GT (GT2 "no CI", which lint catches via R009 but RAG misses by name)**. This is the first observed instance of L1 contributing **unique recall** beyond RAG in this benchmark.
- **Partial recall reaches 100% only because of RAG's `cohort_definition_gate` hits on GT5** — but these are off-topic (they discuss case/control assignment, not patient-level CV). This is *coincidental* coverage, not a true catch.

---

## 6. L2 replication verdict — **CONFIRMED**

Phase 1 finding: gates require structured evidence JSONs (`--evaluation-report`, `--prediction-trace`, `--protocol-spec`, etc.) produced by an MLGG-instrumented training pipeline, which an external GitHub repo by definition does not have. Phase 2 case 2 reproduces this exactly: **0 / 33 gates produced a substantive audit verdict on GRU-D**, 5 / 5 attempted gates exited `FAIL` with missing-file errors. Two real-paper out-of-distribution cases is not yet a formal n=2 invariance proof, but it is consistent enough to land the spec rename recommended in Phase 1 (`L2 → "pipeline contract gates (require MLGG-instrumented training run)"`). I recommend continuing Phase 2 to n=7 before tightening the spec, in case a paper in our remaining queue (Johnson 2017, Harutyunyan 2019) ships sufficient artefacts to flip the finding.

---

## 7. Over-flag list (precision side)

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L1 R016 | `KFold()` w/o `random_state=` in `Generate-sample-data.ipynb` | True positive *for sample data*, but irrelevant to the real MIMIC pipeline (which imports precomputed folds from upstream) — narrow false-flavour |
| 2 | L3 #1 CRITICAL | "bidirectional RNN uses future data" | Wrong direction — GRU-D is **unidirectional** with **trainable decay on past observations**, not bidirectional. Pattern transferred but mechanism does not match this paper. |
| 3 | L3 #2 CRITICAL | ATTRwt-CM case/control assignment | Wrong domain (cardiac amyloid); cohort-definition pattern transfers but mechanism does not |
| 4 | L3 #3 CRITICAL | "Hospitalization total duration leakage" | Off-topic; different paper's variable-scale issue |
| 5 | L3 #4 CRITICAL | "UK Biobank phenotype evaluation leakage" | Wrong dataset; conceptual phenotype-correlation flag does not apply to MIMIC mortality |
| 6 | L3 #5 CRITICAL | "Model trained on clinical AD dementia diagnosis" | Wrong domain (Alzheimer's); cohort-definition transfers, mechanism doesn't |
| 7 | L3 #9 HIGH | "DL training details (optimizer/loss/epochs) missing — DICOM→PNG preprocessing" | Wrong modality (imaging). Conceptual reproducibility flag is valid but mechanism doesn't apply — Run.ipynb does expose optimizer + epochs as CLI args. |
| 8 | L3 #10 HIGH | "AMR prediction — clinical metric most important" | Wrong domain (antimicrobial resistance); clinical-metric flag transfers in spirit |
| 9 | L3 #11 HIGH | "Why only T2w, DWI, CEUS imaging modalities" | Wrong modality (radiology) |
| 10 | L3 #14 HIGH | "MAP@1 0.71-0.79 weakly-labeled propagation" | Wrong outcome family (NLP labels) |

**Over-flag rates**: L1 ≈ 0 / 3 strict (R016 is technically correct but flags sample-data not real pipeline). L3 strict precision ≈ 7 / 20 = **35%** if we credit conceptually-transferred patterns; ≈ 5 / 20 = **25%** if we count only mechanism-matching hits. Consistent with Yan 2020's 25–35% range — **RAG precision continues to be the dominant cost**.

---

## 8. Narrative (≈150 words)

On Che et al. 2018's GRU-D reference implementation — a 1,202-LoC method library that ships precomputed folds, train-fold-only normalisation, and a single `roc_auc_score` — the MLGG hybrid achieved **86% strict recall on 7 first-principles GT issues** (100% partial). The layers contributed asymmetrically and the asymmetry is *different* from Phase 1: lint fired only 3 findings, but **one of them (R009 "no CI") was the sole catcher of GT2**, marking the first observed instance in this benchmark where L1 adds unique recall beyond RAG. RAG was the sole catcher of GT3 (no external validation), GT4 (tuning not reported), and GT6 (no missingness ablation), reaffirming its role as the design-issue channel. L2 ran 0 / 33 gates, exactly as in Phase 1 — the replication is consistent enough that the spec should be renamed to clarify that gates are a *pipeline contract*, not an external audit tool. The pleasant surprise: GRU-D's data loader is actually **leakage-clean** (train-fold-only mean/std), which neither lint nor RAG can credit because they do not reason about good-practice presence — a small but real false-negative direction for the hybrid.

---

## 9. Phase 2 progress

| Case | Paper | Strict recall | L2 verdict | Status |
|---|---|---|---|---|
| Phase 1 #1 | Yan 2020 NMI COVID | 100% (7/7) | 0/33 | DONE |
| **Phase 2 #2** | **Che 2018 GRU-D** | **86% (6/7)** | **0/33** | **THIS REPORT** |
| Phase 2 #3 | Purushotham 2018 MIMIC benchmarks | — | — | next |
| Phase 2 #4 | Li 2020 BEHRT | — | — | queued |
| Phase 2 #5 | Johnson 2017 MIMIC mortality | — | — | queued |
| Phase 2 #6 | Harutyunyan 2019 MIMIC benchmarks | — | — | queued |
| Phase 2 #7 | Kaji 2019 sepsis attention | — | — | queued |
| Phase 2 #8 | Moor 2019 early sepsis | — | — | queued |

---

## Appendix A — Reproduce

```bash
# Clone
cd /tmp && rm -rf W25_p2_che && git clone --depth 1 https://github.com/PeterChe1990/GRU-D W25_p2_che

# L1
cd /Volumes/Seagate/Skill/ml-leakage-guard && python3 -m mlgg_lint check /tmp/W25_p2_che/

# L2 (representative)
python3 -m scripts.gates.request_contract_gate --request /tmp/W25_p2_che/missing.json
python3 -m scripts.gates.sample_size_gate --evaluation-report /tmp/W25_p2_che/missing.json
python3 -m scripts.gates.missingness_policy_gate --policy-spec /tmp/W25_p2_che/missing.json \
  --train /tmp/W25_p2_che/x.csv --test /tmp/W25_p2_che/y.csv

# L3
python3 -c "
import sys, json; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/other/che_2018_grud_missing_values/metadata.json'))
q = '. '.join([
    m['bibliographic']['title'],
    f'binary classification of {m[\"study_design\"][\"outcome\"]}',
    f'dataset {m[\"dataset\"][\"source_name\"]} with {m[\"dataset\"][\"features_n\"]} clinical time series features, ICU multivariate',
    f'{m[\"model\"][\"model_type\"]} GRU recurrent neural network with trainable decay for missing values',
    f'missing data handling: {m[\"dataset\"][\"missing_data_strategy\"]}',
    'imputation may leak future values, normalization/scaler fit on full data risk, k-fold without patient-level split risk, no CI / calibration / DCA reported, single dataset no external validation'
])
flags = synthesize_flags_from_rag(q, top_k=20)
print(len(flags), 'flags')
"
```
