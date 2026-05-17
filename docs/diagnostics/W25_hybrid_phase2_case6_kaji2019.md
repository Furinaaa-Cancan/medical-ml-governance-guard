# W25 Hybrid Phase 2 — Case 6: Kaji et al. 2019 (PLoS ONE, Attention LSTM, MIMIC-III ICU)

**Phase**: Hybrid v1 validation, Phase 2 case study #6 (of 7)
**Spec**: `references/benchmark/hybrid_v1_spec.md` (commit `201eef1`)
**Target paper**: Kaji DA, Zelber-Sagi S, Engel T. *An attention based deep learning model of clinical events in the intensive care unit.* PLoS ONE 14(2):e0211057 (2019). DOI `10.1371/journal.pone.0211057`.
**Code under test**: https://github.com/deepak-kaji/mimic-lstm (cloned `/tmp/W25_p2_kaji`)
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE6 (Claude Opus 4.7)

> **CIRCULARITY CAVEAT (top-billed)**: the ground truth below is **derived from the same `metadata.json` the agent used to seed the L3 RAG query**. This makes GT↔L3 recall artificially favourable. The metadata card itself has open `cannot_assess` fields for all four leakage-risk slots, so GT here is anchored to: (a) metadata-card structured facts (`split_strategy=random`, `is_multicenter=false`, `bootstrap_ci_reported=false`, etc.) and (b) **direct inspection of the GitHub code** (the agent's read-only verification). The code-grounded items (GT3, GT5) are independent of the RAG seed; the design-grounded items (GT1, GT2, GT6, GT7) overlap with the seed text. Treat the recall numbers as **upper-bound** for L3.

---

## 1. Paper card

Kaji et al. 2019 trained an **attention-based LSTM** in Keras/TensorFlow on **MIMIC-III** ICU patients to predict three targets — **myocardial infarction (MI)**, **sepsis**, and **vancomycin administration** — at the **admission-day** granularity. Sepsis labels are constructed by an in-paper heuristic (`heart rate > 90` + `respiratory rate > 20` + WBC-criterion + temperature-criterion ≥ 2 SIRS points AND `Infection == 1`) computed **on the same matrix used for training features**. The paper reports AUROC as the primary metric; **no calibration curve, no DCA, no bootstrap CI, no AUPRC, no MCC**. The repo contains `process_mimic.py` (preprocessing), `pad_sequences.py` (padding + a custom `MinMaxScaler` / `ZScoreNormalize`), `rnn_mimic.py` (training, 432 LoC), `attention_function.py`, and one Jupyter notebook (`attention_mimic_implementation-final.ipynb`).

Kaji 2019 is a known **target-leakage / preprocessing-leakage** candidate flagged in the metadata card's `reviewer_notes` (high-priority, "label-leakage concerns"). It is **NOT in MLGG-Bench** (PLoS ONE not ingested), making this another **OOD** test for the 3-layer hybrid.

---

## 2. 3-layer execution log

| Layer | What ran | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_kaji/` | **4 findings** (0 errors / 2 warnings / 2 infos) | Inspected 4 `.py` files + 1 `.ipynb`. Histogram: **R009 ×2, R022 ×2**. No R007/R020/R027/R004 fired — see §7 narrative for the miss diagnosis. |
| **L2 — Gates (33 available)** | Inspected the same 7 candidate gates as Phase 1 case 1 (`split_protocol_gate`, `sample_size_gate`, `external_validation_gate`, `calibration_dca_gate`, `ci_matrix_gate`, `model_selection_audit_gate`, `request_contract_gate`) via `--help` | **0 / 33 gates ran** | Each gate still requires structured evidence JSONs (`--protocol-spec`, `--evaluation-report`, `--prediction-trace`, `--tuning-spec`, etc.) produced by MLGG-instrumented training. None exist for an external repo. **L2 replication of Phase-1 `0/33`: confirmed.** |
| **L3 — RAG retrieval** | `synthesize_flags_from_rag(query, top_k=20)`; query seeded from `metadata.json` bibliographic + study_design + dataset + model fields | 20 flags returned, **4 CRITICAL + 14 HIGH + 2 MEDIUM** | Category histogram: model_selection 5, split_protocol 3, study_design 3, evaluation_metrics 2, feature_selection 2, data_leakage 2, sample_size 1, reproducibility 1, preprocessing 1. **No `mlgg_rules` fields populated** (RAG-side regression vs Phase 1 — flag dicts ship `code` = gate-name, not MLGG-rule IDs). |

### L1 — lint R-rule histogram

| R-rule | Count | Severity | What it caught | What it MISSED |
|---|---|---|---|---|
| **R022** AUROC-only metric panel | 2 | WARNING | `rnn_mimic.py:402`, `attention_mimic_implementation-final.ipynb` cell 11 | — |
| **R009** metrics without CI | 2 | INFO | `rnn_mimic.py:400` (2 metric calls), notebook cell 11 (29 metric calls) | — |
| **R027** scaler before split | 0 | — | — | **`rnn_mimic.py:192` `PadSequences().ZScoreNormalize(MATRIX)` runs on full matrix before the index-slice split at lines 207–225.** Custom class, not sklearn — heuristic pattern-match missed it. |
| **R020** ffill / impute before split | 0 | — | — | **`process_mimic.py:299` `df2[i].fillna(df2[i].median(), inplace=True)`** uses global median computed on full df, before any split. Custom merge pipeline — pattern-match missed it. |
| **R007** target-in-features risk | 0 | — | — | **`rnn_mimic.py:186` `MATRIX = df[COLUMNS+[target]].values`** then split into `X_MATRIX = MATRIX[:,:,0:-1]; Y_MATRIX = MATRIX[:,:,-1]`. Manual slice — pattern-match missed it. |
| **R004** train_test_split without `groups=` | 0 | — | — | Repo uses **index-slice** (`MATRIX[0:int(tt_split*...)]`) instead of `sklearn.train_test_split`. Same patient-overlap risk; outside R004's regex scope. |

This is a **lint precision-vs-recall failure mode**: the repo uses **custom numpy slicing** instead of sklearn idioms, so the R-rule set (calibrated against sklearn-style code) misses all five code-visible structural concerns. Phase 1 case 1 (Yan 2020, XGBoost + sklearn) saw 17 findings; this case (custom numpy/Keras) sees 4. **The lint signal is fragile to coding-idiom choice.**

### L2 — gates that COULD NOT run, and why

Same 7-gate matrix as Phase 1 case 1; replicates that table verbatim (missing `--evaluation-report`, `--prediction-trace`, `--protocol-spec`, `--tuning-spec`, `--external-validation-report`, `--ci-matrix-report`, `--model-selection-report`, `--request`). **Phase-2 sample 6: L2 contribution = 0%, consistent with Phase 1.**

### L3 — RAG hit aggregate (top-20)

- **Category histogram**: model_selection 5, split_protocol 3, study_design 3, evaluation_metrics 2, feature_selection 2, data_leakage 2, sample_size 1, reproducibility 1, preprocessing 1
- **Severity**: 4 CRITICAL, 14 HIGH, 2 MEDIUM
- **Notable hits**: RAG #4 (CRITICAL split-protocol, "SMOTE on pooled data before split"); RAG #7 (CRITICAL leakage, "bidirectional RNN uses future data" — directly applicable to Kaji's attention-LSTM if attention attends across the full sequence at evaluation); RAG #6 (CRITICAL study-design, "labelling sepsis prediction unusual — culture + antibiotics" — directly relevant to Kaji's SIRS-heuristic sepsis label); RAG #16 (HIGH preprocessing/missingness)
- **Regression vs Phase 1**: zero `mlgg_rules` populated on all 20 flags. Phase 1 reported MLGG-S01 ×1, MLGG-E01 ×1, MLGG-E02 ×3. Worth filing as a separate finding.

---

## 3. Ground truth — 7 documented issues

GT derived from (a) `metadata.json` structured fields and (b) read-only code inspection. **Circularity caveat repeated**: items derived from metadata text overlap with the RAG seed query; items derived from code (marked †) are independent.

| # | Severity | Issue | Evidence |
|---|---|---|---|
| GT1 | HIGH | Split strategy = `random` (admission-day rows, no patient grouping) → same-patient rows can appear in both train and test | `metadata.json` `dataset.split_strategy='random'`; code `rnn_mimic.py:207-225` index-slice on `MATRIX` rows, no `SUBJECT_ID` group key |
| GT2 | HIGH | Single-center MIMIC-III, no external validation | `is_multicenter=false`, `has_external_validation=false` |
| GT3 † | **CRITICAL (code-confirmed)** | **Z-score normalization computed on the full matrix BEFORE the train/val/test split** → leakage of distribution statistics | `rnn_mimic.py:192` `MATRIX = PadSequences().ZScoreNormalize(MATRIX)` runs prior to lines 207-225 split |
| GT4 † | **CRITICAL (code-confirmed)** | **Sepsis label constructed from features in same matrix** (SIRS heuristic on HR, RR, WBC, temp) — these criteria features remain in `X` after label slice unless explicitly dropped; only the intermediate `sepsis_points` columns are deleted (lines 125-129), the underlying vitals are kept as features | `rnn_mimic.py:117-130` |
| GT5 † | HIGH | Median imputation computed on global df before any split (preprocessing leakage) | `process_mimic.py:299` `df2[i].fillna(df2[i].median(), inplace=True)` |
| GT6 | HIGH | No calibration / DCA / AUPRC / MCC reported (incomplete metric panel) | `calibration_reported=false`, `dca_reported=false`, primary metric AUROC only |
| GT7 | HIGH | No bootstrap CI on any metric | `bootstrap_ci_reported=false`, all `*_ci_lower/upper=null` |

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|
| **GT1** Patient-overlap split risk | HIGH | ✗ (R004 doesn't fire on numpy index-slice) | ✗ | ✓ (3 split_protocol hits incl. #4 CRITICAL, #5 CRITICAL, #17 HIGH) | ✓ via L3 |
| **GT2** Single-center, no external | HIGH | ✗ | ✗ | ~ (no direct external_validation hit; partial via #5 cohort-overlap framing) | ~ partial |
| **GT3** † **Z-score on full matrix before split** | CRITICAL | ✗ (R027 misses custom `ZScoreNormalize`) | ✗ | ~ (#4 split_protocol "SMOTE on pooled data" is the conceptual analogue; #16 preprocessing is adjacent) | ~ via L3 conceptual |
| **GT4** † **Sepsis label from same-matrix vitals (target leakage)** | CRITICAL | ✗ (R007 misses manual `MATRIX[:,:,0:-1]` slice) | ✗ | ✓ (#6 CRITICAL cohort-definition "labelling sepsis unusual", #7 CRITICAL leakage "future data via bidirectional", #15 HIGH definition-variable-guard) | ✓ via L3 |
| **GT5** † Median imputation pre-split | HIGH | ✗ (R020 misses custom `fillna(median)` in process_mimic) | ✗ | ~ (#16 missingness-policy HIGH is closest; not exact) | ~ partial |
| **GT6** No calibration / DCA / AUPRC / MCC | HIGH | ✓ (R022 ×2: AUROC-only panel) | ✗ | ✓ (#13 evaluation_metrics HIGH "missing clinical metrics", #19 evaluation_quality) | ✓ via L1 + L3 |
| **GT7** No bootstrap CI | HIGH | ✓ (R009 ×2: metrics without CI) | ✗ | ~ (no explicit CI-rule hit; #17 hyperparameter-leakage tangential) | ✓ via L1 |

Legend: ✓ caught with high confidence, ~ partial / proxy, ✗ missed.

---

## 5. Per-layer recall + complementarity

| Metric | L1 lint | L2 gate | L3 RAG | **Hybrid** |
|---|---|---|---|---|
| Strict recall (✓ only) | 2 / 7 = **29%** | 0 / 7 = **0%** | 3 / 7 = **43%** | **4 / 7 = 57%** |
| Partial recall (✓ + ~) | 2 / 7 = **29%** | 0 / 7 = **0%** | 7 / 7 = **100%** | **7 / 7 = 100%** |
| GT items where this layer is the *sole* catcher | 1 (GT7) | 0 | 1 (GT1) | n/a |
| GT items where this layer adds *unique colour* (specific R-rule or specific source) | 2 (R022, R009) | 0 | 5 (RAG #4, #6, #7, #13, #16) | n/a |

- **Hybrid strict-recall lift vs best single layer**: +14% (4/7 vs 3/7) — meaningful, driven by L1 catching GT7 which RAG missed.
- **L1 strict recall (29%) is far below Phase 1 case 1 (43%)** because the codebase uses **custom numpy** instead of sklearn idioms. The two code-visible items that lint *did* catch (R022, R009) are metric-call surface patterns, which are idiom-stable. The five structural items (split, scaling, imputation, target-leak, group-key) all required idiom-matching that failed.
- **L3 partial recall = 100%** but **strict recall only 43%** — the seed query produced conceptually adjacent retrievals for GT3 (SMOTE-on-pooled-data instead of z-score-on-pooled-data) and GT5 (general missingness instead of pre-split median-fill) without naming the exact mechanism. **The hybrid_v1_spec's "RAG retrieval as concern anchor" framing holds at the partial-recall level but degrades at strict.**
- **L2 contribution: 0%, replicating Phase 1.** Two-sample evidence for the spec amendment is now in place.

---

## 6. Over-flag list (top-10)

Findings that did NOT map to any GT. Same pattern as Phase 1: L1 over-flag low, L3 over-flag dominant.

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L3 RAG #1 | DQN model-selection justification (Atari-style ML) | Wrong domain; transferred from RL paper |
| 2 | L3 RAG #2 | InceptionV3 CNN benchmarking | Wrong modality (imaging, not RNN) |
| 3 | L3 RAG #3 | Transformer ablation experiment | Wrong architecture family |
| 4 | L3 RAG #5 | AI-EF cardiology cohort-overlap question | Wrong domain (echo, not ICU); pattern transferable to GT1 but specific text not applicable |
| 5 | L3 RAG #8 | Bacterial/viral infection control selection | Conceptually adjacent to GT4 (sepsis label) but specific text is from a different study's control-arm critique |
| 6 | L3 RAG #9 | T2w/DWI/CEUS feature inclusion (radiology) | Wrong modality |
| 7 | L3 RAG #10 | 11-17 deterioration events sample size | Wrong scale (MIMIC has thousands); irrelevant |
| 8 | L3 RAG #11 | ICD-9/10 as predictor critique | Kaji doesn't use ICD codes as features; misfire |
| 9 | L3 RAG #14 | "Outdated analytical approach" comment | Generic; not actionable |
| 10 | L3 RAG #18 | PRSice/LDPred benchmarking (GWAS) | Wrong domain (omics) |

**Over-flag rates**: L1 ≈ 0 / 4 = 0% (the 4 findings all map to GT6/GT7). L3 ≈ 10 / 20 = 50% strict, 7 / 20 = 35% if we credit conceptually-transferred patterns. **Slightly worse than Phase 1's 25–65% range — the niche topic (ICU LSTM) attracts more cross-domain false positives.**

---

## 7. Narrative

Kaji et al. 2019 — an attention-LSTM on MIMIC-III with **two code-confirmed CRITICAL leakage mechanisms** (global z-score normalization before the train/test split at `rnn_mimic.py:192`, and a sepsis label derived from SIRS vitals that **remain in the feature matrix** at lines 117–130) — exposed the **central fragility of the hybrid's L1 layer**: the lint R-rule set is calibrated against sklearn idioms, but this repo splits with numpy index-slicing, normalizes with a custom `PadSequences().ZScoreNormalize`, and imputes with `df.fillna(df.median())`, so **R027, R020, R007, and R004 all silently miss the very issues they exist to catch**. L1 caught only the idiom-stable surface patterns (R022 AUROC-only, R009 no-CI) for 2/7 strict recall — far below Phase 1's 3/7 on a sklearn codebase. L3 RAG caught 3/7 strictly (GT1 patient-overlap, GT4 sepsis-label, GT6 metric panel) and partial-covered the rest, hitting 100% partial recall but with 50% strict over-flag from cross-domain retrievals. L2 ran **0/33 gates**, replicating Phase 1 and confirming the spec amendment in two-sample form. **Hybrid strict recall 57% (4/7), partial 100%.**

**L2 verdict (replication check)**: Phase 1 reported **0/33 gates executable on external repos**. Phase 2 case 6: **0/33 confirmed**. Same root cause — gates require structured `--evaluation-report`, `--prediction-trace`, `--protocol-spec`, `--tuning-spec`, etc. JSONs produced only by an MLGG-instrumented training run. **Recommendation persists**: rename L2 in `hybrid_v1_spec.md` to "pipeline contract gates (require MLGG-instrumented training run)", and either (a) accept L2 as out-of-scope for external audits, or (b) build an evidence-synthesis adapter from metadata cards. **Secondary recommendation (new for Phase 2)**: extend lint R-rules to cover **custom-class normalizer / imputer patterns** and **numpy-index-slice splits without group-key checks** — without this, L1 recall on DL repos will continue to underperform L1 recall on sklearn repos by ~15 percentage points.

---

## Appendix A — Raw lint output

```
Found 2 warning(s), 2 info(s).
R-rule histogram: R009 ×2, R022 ×2
```

## Appendix B — Raw RAG output

Top-20 records; aggregate categories `{model_selection:5, split_protocol:3, study_design:3, evaluation_metrics:2, feature_selection:2, data_leakage:2, sample_size:1, reproducibility:1, preprocessing:1}`; severities `{CRITICAL:4, HIGH:14, MEDIUM:2}`; **`mlgg_rules` field empty on all 20** (regression vs Phase 1, flag dicts now ship `code = gate-name` instead of `mlgg_rules = [...]`).

## Appendix C — Reproduce

```bash
# clone
cd /tmp && rm -rf W25_p2_kaji && git clone --depth 1 https://github.com/deepak-kaji/mimic-lstm W25_p2_kaji

# L1
python3 -m mlgg_lint check /tmp/W25_p2_kaji/

# L3
python3 -c "
import json, sys; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/sepsis_icu/kaji_2019_attention_lstm_icu/metadata.json'))
b, sd, ds, mdl = m['bibliographic'], m['study_design'], m['dataset'], m['model']
q = '. '.join([b['title'], f\"binary classification predicting {sd['outcome']} during ICU stay\", f\"setting {sd['setting']}, study period {sd['study_period_start']}-{sd['study_period_end']}\", f\"source {ds['source_name']}, split {ds['split_strategy']}, missing strategy {ds['missing_data_strategy']}\", f\"attention-based LSTM, Keras/TensorFlow\", 'attention RNN for sepsis and MI prediction in MIMIC-III ICU', 'no calibration, no DCA, no bootstrap CI, AUROC primary'])
print(len(synthesize_flags_from_rag(q, top_k=20)), 'flags')
"
```
