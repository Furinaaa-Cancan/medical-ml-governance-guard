# W25 Hybrid Phase 2 — Case 4: Johnson et al. 2017 (MLHC, MIMIC-III Reproducibility)

**Phase**: Hybrid v1 validation, Phase 2 case study #4 of 7
**Spec**: `references/benchmark/hybrid_v1_spec.md`; Phase 1 baseline: `W25_hybrid_phase1_case1_yan2020_covid.md`
**Target paper**: Johnson AEW, Pollard TJ, Mark RG. *Reproducibility in critical care: a mortality prediction case study.* MLHC (Machine Learning for Healthcare) 2017.
**Code under test**: https://github.com/alistairewj/reproducibility-mimic (cloned `/tmp/W25_p2_johnson`, depth 1)
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE4 (Claude Opus 4.7)

---

## 0. Circularity caveat (read first)

**Ground truth in §3 is synthesized from `metadata.json` written by the MLGG team, not from an independent expert audit of the paper.** Two confounders specific to this case:

1. **Meta-paper**: Johnson 2017 is *itself* a methodology paper *about* reproducibility of MIMIC-III mortality prediction. It deliberately exhibits **good** patterns (subject-level K-fold, Pipeline-scoped preprocessing) as illustrative material. The metadata reflects this: nearly every reporting field is `null` / `false` not because the paper failed at them, but because the paper is a **demonstration scaffold**, not a publication-grade clinical model.
2. **RAG-side topical bias**: the paper's abstract terms (`reproducibility`, `MIMIC-III`, `mortality`, `cross-validation`) overlap heavily with the KB's reporting-quality concerns, so RAG can score high on reporting-side categories *without those concerns actually applying to this paper's intended scope*. Read RAG hits in §4 with that in mind.

GT and RAG match in this case mostly because both anchor to the same surface signals (null metric fields, single-center, no external validation), not because both independently observed a flaw.

---

## 1. Paper card

Johnson, Pollard & Mark (MLHC 2017) is a **methodology demonstration**, not a clinical prediction paper. The authors — including Alistair Johnson, the MIMIC-III lead — re-implement several published MIMIC-III mortality models and show how subtle pipeline choices (cohort exclusions, label definition, feature windowing, fold construction) change reported AUROC. The accompanying GitHub repo (`alistairewj/reproducibility-mimic`) ships SQL extraction queries (~30 files under `queries/`), a 623-LoC utilities module (`mp_utils.py`), and two Jupyter notebooks (`reproducibility.ipynb` 2,866 lines / 30 cells, `generate-figures.ipynb`) that run XGBoost + LogisticRegression in a **subject-level K-fold** (subject_id → fold mapped via `idxK_sid[np.searchsorted(sid, X['subject_id'])]`, notebook cell 20 line 41–45) with `sklearn.pipeline.Pipeline([Imputer, StandardScaler, model])` fit inside the fold (line 72–80). The split protocol is methodologically clean — exactly what a Yan-2020-style paper failed to do. The point of the paper is that even with a clean split, reported AUROC drifts substantially across reasonable cohort-definition choices, which is the reproducibility story.

This case is a **negative control**: the hybrid should fire *few* code-level lint errors and *many* RAG over-flags (because RAG cannot distinguish "paper demonstrating a problem" from "paper exhibiting a problem"). If hybrid recall on the metadata-derived GT looks high here, that says more about GT–RAG circularity than about hybrid skill.

---

## 2. 3-layer execution log

| Layer | What ran | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_johnson/` | **4 findings (0 errors / 1 warning / 3 infos)** | All four hits in `notebooks/reproducibility.ipynb[cell 20]`. ~4,643 total lines across 2 notebooks + 1 .py + ~30 SQL files. SQL queries not scanned by lint. |
| **L2 — Gates (33 available)** | Inspected `--help` on 7 candidate gates (`evaluation_quality_gate`, `calibration_dca_gate`, `ci_matrix_gate`, `sample_size_gate`, `split_protocol_gate`, `external_validation_gate`, `model_selection_audit_gate`) | **0 / 33 gates ran** | Every gate requires structured evidence JSONs (`--evaluation-report`, `--prediction-trace`, `--protocol-spec`, `--tuning-spec`, `--external-validation-report`, `--ci-matrix-report`, etc.) produced by an MLGG-instrumented training run. Confirms Phase 1 finding. |
| **L3 — RAG retrieval** | `synthesize_flags_from_rag(q, top_k=20)` with query built from `metadata.json` bibliographic + study_design + dataset + model + performance fields | **20 records (4 CRITICAL + 16 HIGH)** | Categories: study_design 8, split_protocol 4, external_validation 3, evaluation_metrics 2, sample_size 1, model_selection 1, preprocessing 1, clinical_utility 1. |

### L1 — lint R-rule histogram

| R-rule | Count | Severity | Location | Note |
|---|---|---|---|---|
| **R019** 6 model classes without multi-comparison correction | 1 | INFO | `reproducibility.ipynb[cell 20]:10:18` | The notebook iterates xgb + logreg + (commented-out lasso, rf) — comparison without Bonferroni / Benjamini-Hochberg. Mild proxy for model-selection rigor. |
| **R018** Feature scaling with tree-based model | 1 | INFO | `reproducibility.ipynb[cell 20]:75:33` | `StandardScaler` in the pipeline path used by non-xgb models — strictly cosmetic. |
| **R009** Metrics without CI | 1 | INFO | `reproducibility.ipynb[cell 20]:93:21` | `roc_auc_score` reported per-fold without bootstrap CI. |
| **R022** AUROC-only metric panel | 1 | WARNING | `reproducibility.ipynb[cell 20]:93:21` | Only `roc_auc_score` — no AUPRC, calibration, MCC. |

**No R027 (preprocessing before split), no R020 (ffill before split), no R007 (target-in-features), no R004 (split without `groups=`).** This is materially cleaner than Yan 2020 (which had 17 lint findings including 4 errors). The split is subject-level K-fold (`idxK_sid[idxMap]`) and `Pipeline([Imputer, Scaler, mdl])` is fit *inside* the fold — correct ordering.

### L2 — gates that COULD NOT run, and why

Same 7 gates surveyed as Phase 1; all 7 demand evidence JSONs that an external repo does not emit. No adapter exists. Identical 0/33 outcome.

### L3 — RAG hit aggregate (top-20)

- **Severity**: 4 CRITICAL, 16 HIGH, 0 MEDIUM/LOW
- **Category histogram**: study_design 8, split_protocol 4, external_validation 3, evaluation_metrics 2, sample_size 1, model_selection 1, preprocessing 1, clinical_utility 1
- **MLGG gate codes invoked**: `split_protocol_gate` ×4, `cohort_definition_gate` ×8, `external_validation_gate` ×3, `evaluation_quality_gate` ×1, `model_selection_audit_gate` ×1, `sample_size_gate` ×1, `fairness_equity_gate` ×1, `calibration_dca_gate` ×1

---

## 3. Ground truth — 5 issues (circularity-flagged)

Synthesized from `metadata.json`. Per §0, GT5 is the only one with positive code-side evidence; GT1–GT4 are "field-is-null" inferences and *largely artefacts of the paper's methodology-demonstration scope*.

| # | Severity | Issue | Evidence in metadata | Genuine flaw? |
|---|---|---|---|---|
| GT1 | MEDIUM | No bootstrap CI on any metric | `bootstrap_ci_reported=false`, all `*_ci_lower/upper=null` | Mostly scope (per-fold AUROC reported instead). |
| GT2 | MEDIUM | No calibration / DCA | `calibration_reported=false`, `dca_reported=false` | Scope (demo, not deployment). |
| GT3 | MEDIUM | No external validation; single-center MIMIC-III | `is_multicenter=false`, `has_external_validation=false` | Scope (intentional — paper is *about* one cohort). |
| GT4 | LOW | TRIPOD-AI / PROBAST-AI not claimed | `tripod_ai_claimed=false`, `probast_ai_claimed=false` | Both standards post-date 2017. Anachronistic. |
| GT5 | MEDIUM | 6 candidate models without multiple-comparison correction | `model.n_candidate_models=5`; lint R019 confirms 6 classes in code | **Yes** — small genuine model-selection concern, though paper's intent is comparison not selection. |

`leakage_risk_assessment.notes` flags this as "Meta-study on reproducibility — particularly interesting to scan as it may contain both good and bad patterns intentionally" and all five leakage-risk fields are `null` (`cannot_assess`). The code scan (§2) confirms **no patient-level split leakage**, **no preprocessing leakage**, **no target leakage**. The repo passes the "code-visible" half of MLGG cleanly.

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|
| **GT1** No bootstrap CI | MEDIUM | ✓ (R009 ×1 with file:line) | ✗ (would need `ci_matrix_gate` evidence) | ~ (RAG hit #18 evaluation_metrics — generic) | ✓ via L1 |
| **GT2** No calibration / DCA | MEDIUM | ✓ (R022 ×1 AUROC-only panel) | ✗ (would need `calibration_dca_gate` evidence) | ✓ (RAG hits #6, #11, #18 evaluation_metrics + clinical_utility) | ✓ via L1 + L3 |
| **GT3** Single-center / no external | MEDIUM | ✗ (out of code-lint scope) | ✗ | ✓ (RAG hits #4, #17, #20 external_validation, CRITICAL) | ✓ via L3 |
| **GT4** TRIPOD/PROBAST not claimed | LOW | ✗ | ✗ | ✗ (RAG KB has no anachronism awareness) | ✗ |
| **GT5** 6 candidates without correction | MEDIUM | ✓ (R019 ×1 file:line) | ✗ (would need `model_selection_audit_gate` evidence) | ~ (RAG hit #5 model_selection — different paper, transferred pattern) | ✓ via L1 |

Legend: ✓ caught with high confidence, ~ partial / proxy, ✗ missed.

---

## 5. Per-layer recall + complementarity + unique lift

| Metric | L1 lint | L2 gate | L3 RAG | **Hybrid** |
|---|---|---|---|---|
| Strict recall (✓ only) | 3 / 5 = **60%** | 0 / 5 = **0%** | 2 / 5 = **40%** | **4 / 5 = 80%** |
| Partial recall (✓ + ~) | 3 / 5 = **60%** | 0 / 5 = **0%** | 4 / 5 = **80%** | **5 / 5 = 100%** |
| Sole catcher | 1 (GT5 — R019 file:line) | 0 | 1 (GT3 — external validation) | n/a |
| Unique colour | R009 / R019 / R022 file:line pins to `cell 20:line N` | 0 | KB concern_text grounding from 4 CRITICAL + 16 HIGH peer-reviewer concerns | n/a |

- **Hybrid lift vs best single layer (L1@60%)**: +20pp strict (covers GT3 external validation); +40pp partial.
- **L2 contribution = 0** (Phase 2 replication of Phase 1 finding — n=2).
- **GT4 (TRIPOD/PROBAST anachronism)** is genuinely uncatchable: KB lacks publication-year-aware suppression. Worth a backlog ticket.

---

## 6. Over-flag list (precision, top-10)

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L1 R018 | StandardScaler in non-xgb pipeline branch (cell 20:75) | True but cosmetic — only firing on logreg branch where scaling is *appropriate*. R018 should suppress when scaler is gated by `if mdl != 'xgb'`. |
| 2 | L3 RAG #1 | PR-EXP — SMOTE on pooled MIMIC-III+IV before 7:3 split | Different paper, different dataset. Topically related (MIMIC + split) but Johnson does subject-level K-fold, no SMOTE. |
| 3 | L3 RAG #2 | PR-EXP — sepsis label "culture + lactate ordered" | Different paper, different outcome (sepsis, not mortality). Generic cohort-definition concern. |
| 4 | L3 RAG #3 | PR-EXP-0110-C07 AI-EF cardiology overlap | Same generic "patient overlap" phrasing as Yan 2020 case — domain mismatch. |
| 5 | L3 RAG #5 | PR-EXP — "number of CV folds not specified, library/code not provided" | Ironic over-flag: Johnson 2017 is the *opposite* paper — full reproducibility (subject-level K-fold, public code). |
| 6 | L3 RAG #6 | proteomics AIDS vs NCD dichotomization | Off-topic (proteomics). |
| 7 | L3 RAG #7 | CVD mortality right-censoring | Off-topic (different cohort, different outcome framing). |
| 8 | L3 RAG #8 | "Only 11–17 deterioration events" feasibility study | Wrong cohort size; Johnson 2017 doesn't report n (metadata `n_patients_total=null`). |
| 9 | L3 RAG #10 | bacterial/viral sepsis controls | Off-topic. |
| 10 | L3 RAG #16 | GP records sub-population | Off-topic (UK primary-care). |

**Over-flag rates**: L1 ≈ 1 / 4 = **25%** (R018 cosmetic; everything else genuine). L3 ≈ ~15 / 20 = **75% strict** (only ~5 of 20 transfer meaningfully — RAG over-flag rate is *worse* on Johnson than on Yan because the paper's *correctness* leaves fewer real concerns to anchor on). RAG precision is again the dominant cost, and the Johnson case shows the failure mode sharply: when GT is small, RAG's fixed top-K=20 floods the output with adjacent-but-irrelevant concerns.

---

## 7. Narrative

Johnson et al. 2017 is a deliberate negative control: a MIMIC-III reproducibility *methodology* paper by the MIMIC lead, whose accompanying repo demonstrates correct subject-level K-fold splitting and in-fold Pipeline preprocessing. The 3-layer hybrid behaved consistently with Phase 1 in shape but with informative magnitude shifts: L1 fired only 4 findings (vs 17 on Yan 2020), zero errors, and zero leakage-pattern hits — the lint layer correctly recognised a clean pipeline. L2 ran 0/33 gates again, replicating Phase 1: gates remain a pipeline contract, not an external audit tool. L3 RAG retrieved 20 KB concerns (4 CRITICAL, 16 HIGH) with ~75% strict over-flag rate, including the ironic case of a "library/CV-fold count not specified" concern matched against a paper that fully specifies both — RAG cannot tell "demonstrates the problem" from "exhibits the problem." Hybrid strict recall on the metadata GT was 4/5 (80%); the unmatched item (GT4: TRIPOD-AI / PROBAST-AI not claimed) is anachronistic — both standards post-date 2017. The interesting finding here is **precision**, not recall: when a target paper is methodologically clean, RAG's fixed top-K=20 generates dense noise rather than admitting "few real concerns." This is a top-K-tuning lever the Phase 1 report already flagged. **L2 verdict: 0/33 gates applicable on external repo (n=2 replication confirms the pattern).**

---

## 8. Phase 2 aggregate snapshot (this row only)

| Phase | Paper | L1 errors / warns / infos | L2 gates run | L3 RAG hits (CRIT/HIGH) | Strict recall | Over-flag rate L3 |
|---|---|---|---|---|---|---|
| P1 | Yan 2020 COVID NMI | 4 / 7 / 6 | 0 / 33 | 2 / 18 | 100% (7/7) | ~25–65% |
| **P2-04** | **Johnson 2017 MLHC** | **0 / 1 / 3** | **0 / 33** | **4 / 16** | **80% (4/5)** | **~75%** |

Phase 2 aggregate table to be assembled after all 7 case studies land.

---

## Appendix A — Raw lint output

```
notebooks/reproducibility.ipynb[cell 20]:10:18  INFO    R019  6 model classes instantiated without multiple-comparison correction.
notebooks/reproducibility.ipynb[cell 20]:75:33  INFO    R018  Feature scaling used with tree-based model.
notebooks/reproducibility.ipynb[cell 20]:93:21  INFO    R009  4 metric computation(s) without confidence interval estimation.
notebooks/reproducibility.ipynb[cell 20]:93:21  WARNING R022  Only roc_auc_score found — no AUPRC, calibration, or MCC metrics.

Found 1 warning(s), 3 info(s).
```

## Appendix B — Raw RAG output (top-20 summary)

Categories `{study_design:8, split_protocol:4, external_validation:3, evaluation_metrics:2, sample_size:1, model_selection:1, preprocessing:1, clinical_utility:1}`; severity `{CRITICAL:4, HIGH:16}`; gate codes `{cohort_definition_gate:8, split_protocol_gate:4, external_validation_gate:3, evaluation_quality_gate:1, model_selection_audit_gate:1, sample_size_gate:1, fairness_equity_gate:1, calibration_dca_gate:1}`.

## Appendix C — Reproduce

```bash
# Clone
cd /tmp && rm -rf W25_p2_johnson && git clone --depth 1 https://github.com/alistairewj/reproducibility-mimic W25_p2_johnson

# L1
python3 -m mlgg_lint check /tmp/W25_p2_johnson/

# L3
python3 -c "
import json, sys; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/other/johnson_2017_reproducibility_mimic/metadata.json'))
q = '. '.join([m['bibliographic']['title'],
  f'binary classification predicting {m[\"study_design\"][\"outcome\"]}',
  f'MIMIC-III ICU cohort, study period {m[\"study_design\"][\"study_period_start\"]}-{m[\"study_design\"][\"study_period_end\"]}',
  f'split strategy {m[\"dataset\"][\"split_strategy\"]}, scikit-learn ensemble with {m[\"model\"][\"n_candidate_models\"]} candidate models',
  'reproducibility evaluation across multiple model implementations, no calibration, no DCA, no bootstrap CI',
  'reproducibility methodology study, no external validation, single-center MIMIC-III'])
print(len(synthesize_flags_from_rag(q, top_k=20)), 'flags')
"
```
