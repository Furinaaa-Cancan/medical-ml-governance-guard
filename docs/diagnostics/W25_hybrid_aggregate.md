# W25 Hybrid Phase 1+2 Aggregate — 8 real published papers, 3-layer MLGG

**Status**: First N=8 real-world product validation per `references/benchmark/hybrid_v1_spec.md` (commit `201eef1`).

All 8 cases are **out-of-distribution** — none in MLGG KB. True external audit test.

## Per-case headline (8 cases)

| # | Paper | LoC | L1 lint | L2 gates | L3 RAG | Hybrid recall | Notes |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | Yan 2020 NMI COVID | 1.2k | 17 (4E/7W/6I) | **0/33** | 20 | **100%** (7/7) | Pathological outlier (ext AUROC 0.48) |
| 2 | Purushotham 2018 MIMIC DL | 272k | 33 (6E/27I) | **0/33** | 20 | **100%** (5/5) | DL/Theano/Keras; R-rule mix shifts |
| 3 | Che 2018 GRU-D | small | 3 (1W/2I) | **0/33** | 20 | **86%** (6/7) | L1 sole catcher GT2 (CI gap) |
| 4 | Li 2020 BEHRT | mid | 4 INFOs | **0/33** | 20 | **50%/75%** | DL pretrain+finetune; lint collapses |
| 5 | Johnson 2017 Reproducibility | small | 4 (1W/3I) | **0/33** | 20 | **80%** (4/5) | Clean repo; RAG 75% over-flag (ironic) |
| 6 | Harutyunyan 2019 MIMIC | 7.1k | 7 (2E/4W/1I) | **0/33** | 20 | **86%** (6/7) | L1 sole catcher GT6 (test-set tuning) |
| 7 | Kaji 2019 LSTM ICU | mid | 4 (R009/R022) | **0/33** | 20 | **57%** (4/7) | **2 CRITICAL real code leakage found** |
| 8 | Moor 2019 MGP-TCN | 3.7k | 2 (R009 only) | **0/33** | 20 | **86%** (6/7) | Clean repo; hybrid = RAG-only |

## 🔴 Finding 1 — L2 = 0/264 gate-paper pairs is **universal**

Across all 8 cases, **zero of 33 gates ran**. Same root cause every time: 33 gates need pre-built evidence JSONs (`--evaluation-report`, `--prediction-trace`, `--protocol-spec`, `--tuning-spec`) from an MLGG-instrumented training pipeline. External repos don't emit these.

**Implication for `hybrid_v1_spec.md`**: spec frames L1/L2/L3 as 3 co-equal external-audit layers. **L2 is structurally different** — it's a **pipeline contract for internal instrumented runs**, not an audit weapon for third-party papers. Product claim "33 gates audit any paper" is incorrect on external repos.

**Spec Amendment 2 mandate**:
1. Rename L2 → "pipeline contract gates (require MLGG-instrumented training run)"
2. External-audit hybrid is **L1 + L3 only**
3. Or build metadata → evidence-JSON adapter (weeks of work)

## 🟡 Finding 2 — L1 lint recall is **repo-style-dependent**

| Repo style | L1 strict recall | Sample |
|---|---:|---|
| sklearn / pandas tabular | 43-100% | Yan, Purushotham, Che |
| DL / Theano / Keras / numpy | 12-43% | Li BEHRT, Kaji |
| Clean methodology | 14-80% (varies) | Johnson, Moor |

R-rules R027/R020/R007/R004 are **calibrated for sklearn idioms**. DL/numpy repos with custom normalizer classes / numpy-index splits silently slip. Architectural calibration gap.

Also surfaced **2 lint precision bugs** from Harutyunyan run:
- **R002** false-fires on Keras `validation_data=` kwarg
- **R007** false-fires on CSV loader helper

These are W26 fix candidates.

## 🟡 Finding 3 — Phase 1's "L1 = evidence-channel only" was WRONG

Phase 1 (Yan 2020) concluded: "RAG saturates recall; L1 only adds file:line citation". Phase 2 contradicts:

- **Che 2018**: L1's R009 was **sole strict catcher** of GT2 (no bootstrap CI). RAG missed it.
- **Harutyunyan 2019**: L1's R021 was **sole strict catcher** of GT6 (test-set hyperparameter tuning across 3 logistic baselines). RAG missed it.

L1 adds unique recall when the bug is in **code structure, not study-design narrative**. Truly complementary in some configurations, not just channel-redundant.

## 🟡 Finding 4 — RAG strict precision is the bottleneck (25-75%)

| Case | RAG strict over-flag |
|---|---:|
| Johnson 2017 (clean methodology paper) | **75%** ← worst |
| Kaji 2019 | ~50% |
| Purushotham 2018 | ~60% |
| Che 2018 | ~57% |
| Yan 2020 | 25-35% (best, problematic paper) |

Fixed `top_k=20` floods output on clean papers. RAG cannot tell "paper has issues" from "paper has many similar-to-real-issues KB neighbors".

**Phase 3 recommendation**: per-paper adaptive top_k OR per-flag confidence threshold.

Also: **RAG cannot distinguish "paper demonstrating a problem" from "paper exhibiting a problem"** (Johnson 2017 finding — methodology papers ingested as concerns generate ironic matches).

## 🟢 Finding 5 — REAL code-level leakage found by hybrid (Kaji 2019)

W25-P2-06 strongest single result: hybrid surfaced **2 CRITICAL code-level findings** via direct repo inspection:

1. **`rnn_mimic.py:192`** — `MATRIX = PadSequences().ZScoreNormalize(MATRIX)` on full matrix BEFORE the index-slice train/val/test split at lines 207-225 (classic R001 leakage pattern)
2. **`rnn_mimic.py:117-130`** — Sepsis label constructed from SIRS heuristic (HR/RR/WBC/temp); only intermediate `sepsis_points` columns deleted, underlying vital-sign features remain in `X[:,:,0:-1]` → target leakage via predictor features

Both real bugs in a published ML paper's training code. **This is the kind of product evidence the project has been missing**. Cite this case in any external product claim.

## Headline aggregate (citable summary)

| Metric | Value | Caveat |
|---|---:|---|
| Macro hybrid recall (8 papers) | **81%** (range 50-100%) | Circularity bias — GT from metadata |
| Macro L1 strict recall | **31%** | Repo-style-dependent |
| Macro L2 gates ran | **0/264** | Structural finding |
| Macro L3 strict recall | **63%** | Saturates on most papers |
| Macro L1+L3 over-flag | **~45%** strict | Phase 3 bottleneck |
| Real code-level CRITICAL findings | **2 (Kaji 2019)** | Concrete product evidence |

## Comparison to prior MLGG measurements

| Benchmark | Measures | Macro number |
|---|---|---:|
| MLGG-Bench v1.0.2 (305 synthetic) | RAG retrieval (CP hit) | cp_hit@5 = 0.821 |
| W24 (20 NC KB papers) | RAG + matcher | macro F1 = 0.362 |
| **W25 (8 external papers, 3 layers)** | **Hybrid lint + RAG (L2 absent)** | **hybrid recall = 0.81** |

**W25 measures something fundamentally different**: first numbers that test the actual product claim ("MLGG catches what reviewers/critics find in real published papers we never trained on"). Not citable yet (circularity + N=8), but **first real evidence**.

## What this enables

1. **Spec Amendment 2**: rename L2, drop from external-audit recall
2. **W26 lint expansion**: extend R027/R020/R007/R004 for DL/numpy idioms
3. **W26 lint precision fixes**: R002 + R007 false-fire patches
4. **W26 RAG adaptive top_k**: stop flooding clean papers
5. **Phase 3 GT discipline**: pre-register from paper PDF + published critique, not metadata
6. **Citable case for product claim**: Kaji 2019 N=1 strong, concrete file:line

## What we still cannot claim

- "MLGG matches NC peer reviewers" — N=8, circularity, no L2
- "Hybrid > best single layer" — true for some, tautological for others
- Any precision-side product claim — 45% over-flag → human review still needed

## Provenance

- User-initiated 2026-05-17: "MLGG 30 多个门控的硬指标 + NC RAG 结合然后对真实文章去找问题, 这个是我们真实要处理的"
- Spec: `references/benchmark/hybrid_v1_spec.md` (commit 201eef1)
- Memory: `project_hybrid_benchmark_priority.md`
- 8 case studies in `docs/diagnostics/W25_hybrid_phase*_case*.md`
