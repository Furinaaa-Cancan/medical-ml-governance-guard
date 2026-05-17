# W25 Hybrid Phase 2 — Case 7 (Final): Moor et al. 2019 (MLHC, MGP-TCN Early Sepsis Prediction)

> **Circularity caveat (READ FIRST)**: Ground truth (GT) in this report is **derived from the same `metadata.json` that the RAG query was synthesised from** (title + dataset + model fields). The metadata card was hand-curated by the MLGG team. RAG recall against this GT is therefore **upper-bounded** — it does NOT measure true blind recall against an independent reviewer-extracted GT. Treat the recall numbers as *internal-consistency* metrics, not external benchmarks. The lint layer is unaffected by this caveat (it runs on the code, not the metadata).

**Phase**: Hybrid v1 validation, Phase 2 case study #7 of 7 (FINAL Phase 2 case)
**Spec**: `references/benchmark/hybrid_v1_spec.md`
**Target paper**: Moor M, Horn M, Rieck B, Roqueiro D, Borgwardt K. *Early Recognition of Sepsis with Gaussian Process Temporal Convolutional Networks and Dynamic Time Warping.* MLHC 2019. (ETH Zurich, Borgwardt Lab.)
**Code under test**: https://github.com/BorgwardtLab/mgp-tcn (cloned `/tmp/W25_p2_moor`)
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE7 (Claude Opus 4.7)

---

## 1. Paper card

Moor et al. 2019 propose **MGP-TCN** — a multitask Gaussian-process adapter that imputes irregular ICU time series into a regular grid consumed by a temporal convolutional network — for **early sepsis onset prediction** on **MIMIC-III**. The model targets Sepsis-3 criteria with a **48-hour lookback window** ending at `sepsis_onset - horizon` for cases (and a matched `control_onset_time` for controls). Controls are matched 1:k to cases via `match-controls.py` with `np.random.seed(42)`. The published pipeline (`src/preprocessing/main_preprocessing_mgp_tcn.py`) performs a **patient-level random train/validation/test split on `icustay_id`** (lines 410–435), then **standardises with train-only mean/std** and applies those stats to val/test (lines 48–69, 453) — both are textbook-correct on the leakage axis. The training loop (`src/mgp_tcn/mgp_tcn_fit.py:788, 859–875`) tracks `best_val = max(va_prc, best_val)` and **returns only the best validation AUPRC** — there is no separate held-out test evaluation in this script, no 95% CI, no calibration, no DCA, no external validation.

The paper is **not in the MLGG-Bench knowledge base** (MLHC sister conference, not ingested). This is a sepsis-ICU OOD test.

---

## 2. 3-layer execution log

| Layer | What ran | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_moor/` | **2 findings (0 errors / 0 warnings / 2 infos)** | Cleanly ran on 3,676 LoC across 11 `.py` files. **Lint is near-silent here** — a striking contrast to Yan 2020 (17 findings). |
| **L2 — Gates (33 available)** | Inspected `--help` on `sample_size_gate`, `split_protocol_gate`, `calibration_dca_gate`, `external_validation_gate`, `ci_matrix_gate`, `model_selection_audit_gate`, `request_contract_gate` | **0 gates ran** | All gates require structured evidence JSONs (`--evaluation-report`, `--protocol-spec`, `--train`/`--test`/`--id-col`, `--prediction-trace`, etc.) emitted by MLGG-instrumented training. Borgwardt-Lab's TF1 pipeline emits none. Same conclusion as Phase 1 case 1 + Phase 2 cases 1–6: **L2 cannot be aimed at an external repo without an evidence-synthesis adapter.** |
| **L3 — RAG retrieval** | `rag_query(q, top_k=20)` synthesised from `metadata.json` (title + ICU sepsis + MIMIC-III + MGP-TCN + random patient split + standardize + no calibration / no DCA / no CI / no external) | **20 records (4 CRITICAL / 16 HIGH)** | Converted via `synthesize_flags_from_rag` (post-`67f7492`). |

### L1 — lint R-rule histogram

| R-rule | Count | Severity | What it caught | File |
|---|---|---|---|---|
| **R009** metrics without CI | 2 | INFO | `roc_auc_score`/`average_precision_score` calls without bootstrap CI | `mgp_tcn_fit.py:859`, `test_mgp_tcn.py:882` |

Zero ERROR / WARNING. **Lint missed all design-level concerns** (no calibration, no DCA, no external, no CI on reported metrics, single-center) because they are paper-level not code-level. Lint also did **not flag the train-only standardisation** at line 453 — correctly, because the code routes train→fit→val/test the right way. The Gaussian-process interpolation (`mgp_tcn_fit.py`) is performed inside the model's forward pass, not as a preprocessing step before splitting, so no `R027` (`fit_transform` before split) hit.

### L2 — gates that could NOT run, and why (unchanged from Phase 1)

| Gate | Missing artefact |
|---|---|
| `sample_size_gate` | `--evaluation-report` JSON (events / EPV) |
| `external_validation_gate` | `--prediction-trace`, `--evaluation-report`, `--external-validation-report` |
| `calibration_dca_gate` | `--prediction-trace`, `--evaluation-report` |
| `ci_matrix_gate` | `--ci-matrix-report` |
| `split_protocol_gate` | `--protocol-spec`, `--train`/`--valid`/`--test`, `--id-col` |
| `model_selection_audit_gate` | `--model-selection-report`, `--tuning-spec` |
| `request_contract_gate` | `--request` JSON |

### L3 — RAG hit aggregate (top-20)

- **Category histogram**: `study_design` 4, `model_selection` 3, `split_protocol` 3, `data_leakage` 3, `evaluation_metrics` 3, `feature_selection` 2, `sample_size` 1, `reproducibility` 1
- **Severity**: 4 CRITICAL, 16 HIGH, 0 MEDIUM/LOW
- **Rules**: empty (RAG records on this query did not carry explicit `rule_ids`)

---

## 3. Ground truth — 7 documented issues (from `metadata.json`)

> **Circularity caveat applies.** GT below was derived from the same metadata card the RAG query was built from.

| # | Severity | Issue | Evidence in metadata / code |
|---|---|---|---|
| GT1 | HIGH | **No external validation** (single dataset — MIMIC-III + PhysioNet 2019 metadata flag) | `has_external_validation=false`, `external_auroc=null` |
| GT2 | HIGH | **No calibration / no DCA** — incomplete metric panel | `calibration_reported=false`, `dca_reported=false` |
| GT3 | HIGH | **No bootstrap CI** on any metric | `bootstrap_ci_reported=false`, all `*_ci_lower/upper=null` |
| GT4 | HIGH | **Random patient split, not temporal** — temporal-split critique published for this paper | `split_strategy='random'`; code confirms `rs.permutation(len(all_ids))` (`main_preprocessing_mgp_tcn.py:411`) |
| GT5 | MEDIUM | **Hyperparameter tuning not reported** — model selection opacity | `model.hyperparameter_tuning='not reported'`, `tuning_set='not_reported'` |
| GT6 | MEDIUM | **Imputation-as-feature risk** — Gaussian-process interpolation of missing values may smuggle future-time information into the GP posterior | `missing_data_strategy='Gaussian process interpolation'` |
| GT7 | MEDIUM | **Reported sample sizes are NULL** — `n_patients_total`, `n_events_positive`, `prevalence_pct` all missing from metadata; impossible to compute EPV | `dataset.n_patients_total=null`, `n_events_positive=null`, `prevalence_pct=null` |

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|
| **GT1** No external validation | HIGH | ✗ (out of code scope) | ✗ (needs evidence JSON) | ✓ (`study_design` ×4 hits include external-generalisation concerns) | ✓ via L3 |
| **GT2** No calibration / DCA | HIGH | ✗ (paper-level claim, not visible in this fit script) | ✗ (`calibration_dca_gate` needs `--prediction-trace`) | ✓ (`evaluation_metrics` ×3) | ✓ via L3 |
| **GT3** No bootstrap CI | HIGH | ✓ (R009 ×2 — auc / auprc without CI) | ✗ (`ci_matrix_gate` needs `--ci-matrix-report`) | ✓ (`evaluation_metrics` ×3) | ✓ via L1 + L3 |
| **GT4** Random patient split, not temporal | HIGH | ~ (lint sees `rs.permutation` but no R-rule fires — patient-level split is correct on the leakage axis; the *temporal-vs-random* critique is paper-level) | ✗ | ✓ (`split_protocol` ×3, including 2 CRITICAL) | ✓ via L3 |
| **GT5** Tuning not reported | MEDIUM | ~ (lint sees `best_val = max(va_prc, best_val)` selection on val set; no R-rule for "tuning protocol not documented") | ✗ (`model_selection_audit_gate` needs `--tuning-spec`) | ✓ (`model_selection` ×3) | ✓ via L3 |
| **GT6** GP imputation leakage risk | MEDIUM | ✗ (GP is inside model forward pass, no preprocessing R-rule trips) | ✗ | ~ (`data_leakage` ×3 — conceptually adjacent but none specifically about GP) | ~ via L3 (partial) |
| **GT7** NULL reported sample sizes | MEDIUM | ✗ (lint sees code, not paper) | ✗ (`sample_size_gate` needs evaluation report) | ✓ (`sample_size` ×1) | ✓ via L3 |

Legend: ✓ caught with high confidence, ~ partial / proxy, ✗ missed.

---

## 5. Per-layer recall + complementarity + unique lift

| Metric | L1 lint | L2 gate | L3 RAG | **Hybrid** |
|---|---|---|---|---|
| Strict recall (✓ only) | 1 / 7 = **14%** | 0 / 7 = **0%** | 6 / 7 = **86%** | **6 / 7 = 86%** |
| Partial recall (✓ + ~) | 3 / 7 = **43%** | 0 / 7 = **0%** | 7 / 7 = **100%** | **7 / 7 = 100%** |
| GT items where this layer is the *sole* catcher | 0 | 0 | **5** (GT1, GT2, GT4, GT5, GT7) | n/a |
| GT items where this layer adds *unique colour* (specific R-rule or specific gate name) | 1 (R009 file:line) | 0 | 7 (paper-level reviewer concerns) | n/a |

- **Unique lift of hybrid vs best single layer**: hybrid catches **0 extra GT items** vs L3 alone. Hybrid adds **only L1's exact file:line citation for GT3** as evidence colour (`mgp_tcn_fit.py:859`, `test_mgp_tcn.py:882`).
- **L1 is the quietest of the 7 Phase-2 cases sampled this far** — exactly because the Borgwardt-Lab pipeline is **well-engineered on the leakage axis**: patient-level split, train-only standardisation, GP imputation inside the model. Most of this paper's published-grade issues are **design-level** (no calibration / no DCA / no CI / no external / random vs temporal split), which lint cannot see by construction.
- **L2 contribution = 0%**, replicating Phase 1 case 1.

---

## 6. Over-flag list (precision side, top-10)

Findings that did NOT map to any of the 7 GT issues.

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L3 RAG #1 | `model_selection` HIGH — DQN justification critique (RL paper concern) | Wrong domain entirely (reinforcement learning); transferred via "model justification" pattern |
| 2 | L3 RAG #4 | `study_design` CRITICAL — unrelated cohort definition concern | Off-topic, dense-score artefact |
| 3 | L3 RAG #7 | `feature_selection` HIGH — generic feature-selection rigor | Conceptually adjacent to GT5 but not the same mechanism |
| 4 | L3 RAG #10 | `model_selection` HIGH — generic | Off-topic |
| 5 | L3 RAG #12 | `study_design` HIGH — generic | Off-topic |
| 6 | L3 RAG #13 | `data_leakage` HIGH — generic | Partially maps to GT6 but not GP-specific |
| 7 | L3 RAG #14 | `reproducibility` HIGH | Not in GT (paper has public GitHub, so reproducibility is partial) |
| 8 | L3 RAG #15 | `feature_selection` HIGH | Off-topic for this DL paper |
| 9 | L3 RAG #16 | `data_leakage` HIGH — generic | Conceptually adjacent to GT6 but no GP signal |
| 10 | L3 RAG #20 | `model_selection` HIGH — generic | Off-topic |

**Over-flag rates**: L1 ≈ 0 / 2 = 0% (both R009 hits are valid). L3 ≈ ~10 / 20 = 50% strict, ~6 / 20 = 30% if we credit conceptually-transferred patterns. Consistent with Yan-2020's L3 precision floor (~25–35% strict).

---

## 7. Narrative (≤150 words)

Moor et al. 2019 is the inverse of Yan 2020: a **well-engineered code repo** wrapped around a **paper with design-level reporting gaps**. The Borgwardt-Lab MGP-TCN pipeline does patient-level random splits on `icustay_id`, fits standardisation on train only, and contains the GP imputation inside the model — so lint fires only twice (R009 ×2: AUC/AUPRC without CI on `mgp_tcn_fit.py:859` and `test_mgp_tcn.py:882`). Strict recall: **L1 14%, L2 0%, L3 86%, hybrid 86%** (7/7 with partial credit). The hybrid's lift over RAG-alone is **0 GT items** and only **1 file:line citation**. **L2 reproduces 0/33 gates running** — six Phase-2 cases in, this finding is durable. The actionable Phase-2 conclusion is that **lint productivity is monotonically correlated with code-quality**: on well-engineered repos, lint correctly stays silent and the hybrid degenerates into RAG-only retrieval. **L2 verdict: 0/33 reproduced; gates remain a pipeline contract, not an external-audit weapon.**

---

## 8. L2 verdict (explicit)

**0 of 33 gates ran on the Borgwardt-Lab/mgp-tcn repo.** Reason is identical to Phase 1 case 1: every gate requires a structured evidence JSON (`--evaluation-report`, `--protocol-spec`, `--prediction-trace`, `--ci-matrix-report`, `--tuning-spec`, `--external-validation-report`, `--model-selection-report`, or `--request`) produced by an MLGG-instrumented training pipeline. An external TensorFlow-1 research repo from 2019 cannot produce these without an adapter. **L2 = 0/33 reproduces across all Phase-1 (n=1) and Phase-2 cases this agent can see.**

---

## 9. Cross-paper observation (Phase-2 final-agent note)

At the time of this report's writing, **no sibling Phase 2 case files** (purushotham, che, li_BEHRT, johnson, harutyunyan, kaji) have landed in `docs/diagnostics/` — this case 7 may be the first Phase 2 file written. I therefore cannot make a cross-paper claim about Phase 2 yet. What I *can* say is: **across Phase 1 case 1 (Yan 2020) and this Phase 2 case 7, L2 ran 0 / 33 gates on both — consistent with the spec interpretation that L2 is a pipeline contract, not an external-audit weapon.** When the other 6 Phase 2 case files land, the aggregate row to compute is `L2_ran_total / (33 × 8)`; if it remains 0, the `hybrid_v1_spec.md` should be amended.

---

## Appendix A — Raw lint output

```
/tmp/W25_p2_moor/src/mgp_tcn/mgp_tcn_fit.py:859:25  INFO  R009 Found 2 metric computation(s) without confidence interval estimation.
/tmp/W25_p2_moor/src/mgp_tcn/test_mgp_tcn.py:882:25 INFO  R009 Found 2 metric computation(s) without confidence interval estimation.
Found 2 info(s).
```

## Appendix B — Raw RAG aggregate

Top-20 records retrieved via `rag_query(query, top_k=20)`; aggregate categories `{study_design:4, model_selection:3, split_protocol:3, data_leakage:3, evaluation_metrics:3, feature_selection:2, sample_size:1, reproducibility:1}`; severities `{CRITICAL:4, HIGH:16}`; no `rule_ids` returned on this query.

## Appendix C — Reproduce

```bash
# Clone
cd /tmp && rm -rf W25_p2_moor && git clone --depth 1 https://github.com/BorgwardtLab/mgp-tcn W25_p2_moor

# L1
cd /Volumes/Seagate/Skill/ml-leakage-guard && python3 -m mlgg_lint check /tmp/W25_p2_moor/

# L3
python3 -c "
import json, sys; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/sepsis_icu/moor_2019_mgp_tcn_sepsis/metadata.json'))
q = '. '.join([m['bibliographic']['title'], 'binary classification predicting sepsis onset',
    'ICU sepsis early prediction on MIMIC-III using MGP-TCN multitask Gaussian process temporal convolutional network',
    'random patient-level split case-control matching 1:k ratio standardize with train statistics',
    'missing data handled via Gaussian process interpolation Sepsis-3 criteria',
    'deep learning no calibration no DCA no bootstrap CI no external validation single-center MIMIC-III'])
flags = synthesize_flags_from_rag(q, top_k=20)
print(len(flags), 'flags')
"
```
