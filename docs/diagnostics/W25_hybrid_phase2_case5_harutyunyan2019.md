# W25 Hybrid Phase 2 — Case 5: Harutyunyan et al. 2019 (Scientific Data, MIMIC-III benchmarks)

**Phase**: Hybrid v1 validation, Phase 2 case study #5 of 7
**Spec**: `references/benchmark/hybrid_v1_spec.md`
**Target paper**: Harutyunyan H, Khachatrian H, Kale DC, Ver Steeg G, Galstyan A. *Multitask learning and benchmarking with clinical time series data.* Scientific Data (2019). DOI `10.1038/s41597-019-0103-9`.
**Code under test**: https://github.com/YerevaNN/mimic3-benchmarks (cloned `/tmp/W25_p2_harut`, 66 `.py` files, ~7,087 LoC)
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE5 (Claude Opus 4.7)

> **Circularity caveat**: the ground truth (GT) below is derived from `metadata.json`, which was itself produced by an MLGG team review of the paper. GT items therefore reflect what *the metadata reviewer flagged*, not what an oracle peer reviewer would flag. Treat recall numbers as **internal-consistency** measures, not external validity claims.

---

## 1. Paper card

Harutyunyan et al. published the de-facto **MIMIC-III benchmark suite**: four ICU prediction tasks (in-hospital mortality at 48h, decompensation in 24h windows, length-of-stay regression-as-classification, 25-phenotype labelling) over a cohort of **n=42,276 ICU stays** with **17 vitals/labs**. Five baselines per task (LSTM, channel-wise LSTM, multitask LSTM, logistic regression, standard RNN). Reported in-hospital mortality test AUROC ≈ 0.87 / AUPRC ≈ 0.52. The dataset and codebase are the *single most cited* MIMIC-III benchmark — downstream papers (Che 2018 GRU-D, Purushotham 2018, dozens more) reuse these splits verbatim, so any leakage or evaluation gap here propagates broadly. The paper is well-engineered for reproducibility (split files, normalizers, deterministic seeds) but has known gaps: **no bootstrap CI, AUROC-dominant panel, no calibration / DCA, no external validation, single-center, random rather than temporal split**.

---

## 2. 3-layer execution log

| Layer | What ran | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_harut/` | **7 findings** (2 errors / 4 warnings / 1 info) across 4 task subdirs | 66 `.py` files, ~7,087 LoC. Clean run modulo upstream `SyntaxWarning`s. |
| **L2 — Gates (33 available)** | Probed `sample_size_gate --help`, `split_protocol_gate --help` as representatives | **0 / 33 gates ran** | Same Phase 1 result: every gate requires structured evidence JSONs (`--evaluation-report`, `--protocol-spec`, `--prediction-trace`, `--train`/`--test` CSVs, `--id-col`) that a third-party repo does not ship. |
| **L3 — RAG retrieval** | `synthesize_flags_from_rag(q, top_k=20)` with `q` built from metadata bibliographic + dataset + performance fields | **20 flags** (3 CRITICAL / 16 HIGH / 1 MEDIUM) | Categories: `evaluation_metrics:9, split_protocol:5, study_design:4, external_validation:2`. Gate codes: `evaluation_quality_gate:6, split_protocol_gate:5, cohort_definition_gate:4, external_validation_gate:2, calibration_dca_gate:1, ci_matrix_gate:1, clinical_metrics_gate:1`. |

### L1 — lint flags, with per-task attribution

| File (task) | Line | R-rule | Severity | Issue |
|---|---:|---|---|---|
| `mimic3benchmark/mimic3csv.py` (preprocess) | 20 | R007 | ERROR | `admits` includes `DIAGNOSIS` column — flagged as target-like feature |
| `mimic3models/in_hospital_mortality/main.py` (IHM) | 143 | R002 | ERROR | `model.fit(... validation_data=val_raw ...)` — pattern-matched as "fit on validation" |
| `mimic3models/decompensation/logistic/main.py` (DECOMP) | 111 | R021 | WARNING | `predict_proba(test_X)` inside `for (penalty, C)` hyperparameter sweep |
| `mimic3models/length_of_stay/logistic/main_cf.py` (LOS) | 125 | R021 | WARNING | same pattern, custom-features LOS variant |
| `mimic3models/phenotyping/logistic/main.py` (PHENO) | 106 | R021 | WARNING | same pattern, phenotyping logistic |
| `mimic3models/metrics.py` (all tasks) | 23 | R009 | INFO | 6 metric calls without CI |
| `mimic3models/metrics.py` (all tasks) | 23 | R022 | WARNING | only `roc_auc_score` — no AUPRC / calibration / MCC |

**Per-task flag count**: IHM 1, DECOMP 1, LOS 1, PHENO 1, shared `metrics.py` 2, shared `mimic3csv.py` 1 → **shared evaluation harness is the dominant leverage point** (one fix in `metrics.py` would clear R009 + R022 for all four tasks).

### L2 — gates that COULD NOT run, and why (replication of Phase 1)

Same pattern as Yan 2020. Examples (full list in Phase 1 §2):

| Gate | Missing artefact |
|---|---|
| `sample_size_gate` | `--evaluation-report` JSON (events, EPV per task) |
| `split_protocol_gate` | `--protocol-spec`, `--train`, `--test`, `--id-col` |
| `calibration_dca_gate` | `--prediction-trace`, `--evaluation-report` |
| `ci_matrix_gate` | `--ci-matrix-report` |
| `external_validation_gate` | `--external-validation-report` |

**Phase 2 case-5 confirms Phase 1 L2 result**: 0/33 on an external repo, regardless of repo size (1,228 LoC Yan vs 7,087 LoC Harutyunyan). The blocker is contract, not scale.

### L3 — RAG hit aggregate (top-20)

- **Category histogram**: `evaluation_metrics:9, split_protocol:5, study_design:4, external_validation:2`
- **Severity**: 3 CRITICAL / 16 HIGH / 1 MEDIUM
- **Gate-code citations**: `evaluation_quality_gate:6, split_protocol_gate:5, cohort_definition_gate:4, external_validation_gate:2, calibration_dca_gate:1, ci_matrix_gate:1, clinical_metrics_gate:1`

---

## 3. Ground truth — 7 documented issues

Synthesised from `metadata.json` (`leakage_risk_assessment.notes` + `performance_metrics.*` + `reviewer_notes.notes`). **GT extraction is identical-template to Phase 1 case 1.**

| # | Severity | Issue | Evidence in metadata |
|---|---|---|---|
| GT1 | HIGH | Split is **random not temporal** — temporal leakage risk on ICU time-series spanning 2001–2012 | `split_strategy=random`, `temporal_split_confirmed=false` |
| GT2 | HIGH | Patient-level split **not verified in code** (metadata claims it but `preprocessing_fit_on_train_only=null`) | `patient_level_split_confirmed=true (unverified)`, notes say "needs code verification" |
| GT3 | HIGH | No bootstrap 95% CI on any reported metric | `bootstrap_ci_reported=false`, all `*_ci_lower/upper=null` |
| GT4 | HIGH | AUROC-dominant panel: no calibration curve, no DCA, no MCC | `calibration_reported=false`, `dca_reported=false` |
| GT5 | HIGH | No external validation (single-center MIMIC-III) | `has_external_validation=false`, `is_multicenter=false` |
| GT6 | MEDIUM | Hyperparameter selection on logistic baselines may touch test set (`predict_proba(test_X)` inside `(penalty, C)` sweep) | Inferred from `model.hyperparameter_tuning=grid search`, `tuning_set=validation_only` claimed but code shows test-scoring in tuning loop |
| GT7 | MEDIUM | No TRIPOD-AI / PROBAST-AI / STARD-AI compliance claimed | `tripod_ai_claimed=false`, `probast_ai_claimed=false`, `stard_ai_claimed=false` |

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|
| **GT1** Random-not-temporal split | HIGH | ✗ (lint has no temporal-vs-random discriminator) | ✗ (needs `split_protocol_gate` + `--time-col`) | ✓ (5 RAG split_protocol hits, incl. CRITICAL "cross-validation strategy unclear") | ✓ via L3 |
| **GT2** Patient-level split unverified in code | HIGH | ~ (lint can't see split files but R021 logistic sweep proves test set is *touched* per param; not a strict patient-overlap check) | ✗ | ✓ (split_protocol hits, incl. "patients included in cohort were not included in the original" CRITICAL) | ✓ via L3 + partial L1 |
| **GT3** No bootstrap CI | HIGH | ✓ (**R009** ×1 INFO on `metrics.py` — covers all 4 tasks because `metrics.py` is shared) | ✗ (needs `ci_matrix_gate` evidence) | ✓ (1 RAG `ci_matrix_gate` hit, plus repeated `evaluation_quality_gate` calls for "results modest with overlapping CI") | ✓ via L1 + L3 |
| **GT4** No calibration / DCA / AUPRC | HIGH | ✓ (**R022** WARNING on `metrics.py` — single fix benefits all tasks) | ✗ (needs `calibration_dca_gate` evidence) | ✓ (RAG `calibration_dca_gate:1`, `evaluation_quality_gate:6`, `clinical_metrics_gate:1`) | ✓ via L1 + L3 |
| **GT5** No external validation | HIGH | ✗ (out of scope for code lint) | ✗ | ✓ (2 RAG `external_validation` hits) | ✓ via L3 |
| **GT6** Test-set hyperparameter sweep | MEDIUM | ✓ (**R021** ×3 on DECOMP / LOS / PHENO logistic baselines — exact file:line for each) | ✗ (needs `tuning_leakage_gate` or `model_selection_audit_gate` evidence) | ~ (RAG generic "tuning unclear" but no specific test-leak code pattern) | ✓ via L1 (sole catcher with code-precision) |
| **GT7** No TRIPOD/PROBAST/STARD-AI | MEDIUM | ✗ (lint doesn't read reporting checklists) | ✗ | ~ (RAG `evaluation_quality_gate` and `cohort_definition_gate` orbit reporting-rigor concerns but don't tag TRIPOD-AI) | ~ partial via L3 |

Legend: ✓ caught with high confidence, ~ partial / proxy, ✗ missed.

---

## 5. Per-layer recall + complementarity + unique lift

| Metric | L1 lint | L2 gate | L3 RAG | **Hybrid** |
|---|---|---|---|---|
| Strict recall (✓ only) | 3 / 7 = **43%** | 0 / 7 = **0%** | 5 / 7 = **71%** | **6 / 7 = 86%** |
| Partial recall (✓ + ~) | 4 / 7 = **57%** | 0 / 7 = **0%** | 7 / 7 = **100%** | **7 / 7 = 100%** |
| GT items where this layer is the *sole* strict catcher | **1** (GT6 — test-set hyperparam sweep, code-only signal) | 0 | **2** (GT1 random-not-temporal, GT5 no external) | n/a |
| GT items where this layer adds *unique colour* (file:line or specific concern) | **4** (R007, R021×3, R009, R022 with exact `metrics.py:23` and per-task `:111/:125/:106`) | 0 | 7 (peer-reviewer citations) | n/a |

- **Unique lift of hybrid vs best single layer**: hybrid catches **+1 strict GT** vs L3 alone (RAG misses GT6 with code-precision; lint nails it). Hybrid catches **+3 strict GT** vs L1 alone.
- **L2 contribution**: zero on this OOD repo. **Phase 2 case 5 replicates Phase 1**: hybrid_v1_spec L2-as-external-audit framing is wrong. L2 is a pipeline contract, period.
- **Per-task lint scaling note**: Harutyunyan's shared `metrics.py` means *one* R009 + R022 flag pair covers all 4 tasks — so even though the repo is ~6× larger than Yan 2020, the lint flag count *dropped* from 17 to 7. Lint signal is **architecture-dependent**, not LoC-dependent.

---

## 6. Over-flag list (precision side)

Findings that did NOT map to any of the 7 GT issues.

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L1 R002 (ERROR) | `mimic3models/in_hospital_mortality/main.py:143` "fit on validation data" | **False positive.** Code is `model.fit(x=train_raw[0], y=train_raw[1], validation_data=val_raw, ...)` — Keras `validation_data=` is for epoch-end monitoring, not training. Lint regex substring-matched `model.fit(val_raw)` against the `validation_data=val_raw` token. **R002 needs `validation_data=` keyword exclusion.** |
| 2 | L1 R007 (ERROR) | `mimic3csv.py:20` "`admits` includes target-like column 'DIAGNOSIS'" | **Likely false positive.** This is a CSV-loader helper for `ADMISSIONS.csv`; `DIAGNOSIS` is a free-text admission reason later excluded from feature matrices. R007 has no downstream-usage context. |
| 3 | L3 RAG #1 | Adjusted R²=0.31 / Mayo Imaging Classification — wrong domain | Cardiac amyloid R², not ICU mortality |
| 4 | L3 RAG #2 | "PR-AUC vs IPI / German external cohort" | Lymphoma IPI score; conceptually transferred but wrong domain |
| 5 | L3 RAG #5 | ATTRwt-CM case-control assignment | Cardiac amyloid case-control |
| 6 | L3 RAG #6 | Bacterial/viral non-sepsis controls | Sepsis paper, not Harutyunyan |
| 7 | L3 RAG #7 | 30-day chemotherapy acute care window | ACU, wrong outcome |
| 8 | L3 RAG #8 | AMR prediction missing key metric | Antimicrobial-resistance, wrong domain |
| 9 | L3 RAG #9 | NetBio transcriptomic features | Genomics, wrong modality |
| 10 | L3 RAG #10–20 | mostly wrong-domain (preterm placenta, PRS/cancer, sentiment analysis, etc.) | Conceptual transfer at best; ~70% off-topic |

**Over-flag rates**:
- L1: 2 / 7 = **29%** (R002 + R007 both look like genuine false positives on this repo — higher than Yan's 1/17 = 6%; the larger codebase exposed two lint precision bugs).
- L3: ~13 / 20 = **65%** strict (off-domain), ~5 / 20 = **25%** if credited for "pattern transfer". Same magnitude as Phase 1.

---

## 7. Narrative (150 words)

On Harutyunyan et al. 2019 — the most-cited MIMIC-III benchmark, 7,087 LoC across four tasks — MLGG's 3-layer hybrid achieved **86% strict recall / 100% partial recall on the 7 metadata-derived ground-truth issues**, with layer contributions matching Phase 1's pattern: L1 lint pinned code-visible issues to exact file:line (R009 + R022 on the shared `metrics.py:23`, R021 on each of three logistic-baseline hyperparameter sweeps), L3 RAG provided the sole signal on temporal-split absence and external-validation absence, and L2 gates again ran **0/33** because every gate requires structured evidence JSONs an external repo cannot ship. Two new findings beyond Phase 1: (a) lint *flag count dropped* from 17 to 7 despite a 6× larger codebase — Harutyunyan's shared `metrics.py` means a single flag covers all four tasks, so signal is architecture-dependent, not LoC-dependent; and (b) the larger codebase exposed two lint false positives (R002 mismatching Keras `validation_data=` kwarg; R007 firing on a CSV-loader helper), raising L1 over-flag rate from 6% to 29%. **L2 verdict: 0/33, replicates Phase 1 — gates are a pipeline contract, not an external audit tool.**

---

## 8. L2 verdict + Phase 1 comparison

| Dimension | Phase 1 (Yan 2020) | Phase 2 case 5 (Harutyunyan 2019) | Delta |
|---|---|---|---|
| Repo size (LoC) | ~1,228 | ~7,087 | 6× |
| Lint flags (total) | 17 | 7 | -10 (shared `metrics.py` collapses 4 tasks → 1 flag pair) |
| Lint over-flag rate | 6% (1/17) | 29% (2/7) | **+23 pp** (two new FP modes surfaced: R002 keyword, R007 loader-helper) |
| L2 gates that ran | 0 / 33 | 0 / 33 | **identical** |
| RAG top-20, % off-domain | ~65% | ~65% | identical |
| Strict recall, hybrid | 100% (7/7) | 86% (6/7) | -14 pp (GT7 reporting-standards genuinely uncatchable) |
| Sole-strict-catcher: L1 | 0 | **1** (GT6 hyperparam sweep) | L1 gained value from code-visible tuning leak |
| Sole-strict-catcher: L3 | 2 (GT1, GT7) | 2 (GT1, GT5) | identical magnitude |

**L2 verdict**: **CONFIRMED 0/33 on external repos.** Two papers, two repo scales, identical zero. This is no longer an n=1 anomaly. Recommendation for Phase 3 spec revision: **remove L2 from the external-audit recall calculation**, rename to "L2 — internal pipeline contract gates (require MLGG-instrumented training run)", and either (a) build an adapter that synthesises evidence JSONs from `metadata.json` + lint output, or (b) explicitly scope L2 out of the hybrid for third-party audits.

---

## 9. Reproduce

```bash
# L1
python3 -m mlgg_lint check /tmp/W25_p2_harut/

# L3
python3 -c "
import json, sys, warnings; warnings.filterwarnings('ignore'); sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/sepsis_icu/harutyunyan_2019_mimic3_benchmarks/metadata.json'))
q = '. '.join([
  m['bibliographic']['title'],
  f\"multi-task binary classification predicting {m['study_design']['outcome']}\",
  f\"MIMIC-III ICU cohort n={m['dataset']['n_patients_total']}, prevalence {m['dataset']['prevalence_pct']}%, split {m['dataset']['split_strategy']}\",
  f\"LSTM channel-wise multitask logistic baselines, {m['dataset']['features_n']} clinical variables (vitals + labs)\",
  f\"test AUROC {m['performance_metrics']['test_auroc']}, AUPRC {m['performance_metrics']['test_auprc']}, no CI, no calibration, no DCA\",
  'random patient-level split, no temporal split, no external validation, single-center MIMIC'
])
print(len(synthesize_flags_from_rag(q, top_k=20)), 'flags')
"
```
