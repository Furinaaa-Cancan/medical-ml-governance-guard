# W25 Hybrid Phase 2 — Case 3: Li et al. 2020 (Scientific Reports, BEHRT EHR Transformer)

**Phase**: Hybrid v1 validation, Phase 2 case study #3 of 7
**Spec**: `references/benchmark/hybrid_v1_spec.md` (commit `201eef1`); template = `docs/diagnostics/W25_hybrid_phase1_case1_yan2020_covid.md` (commit `db1d7e0`).
**Target paper**: Li Y, Rao S, Solares JRA et al. *BEHRT: Transformer for Electronic Health Records.* Scientific Reports 10, 7155 (2020). DOI `10.1038/s41598-020-62922-y`. PMID 32273507.
**Code under test**: https://github.com/deepmedicine/BEHRT (cloned `/tmp/W25_p2_behrt`, 21 source files, 663 LoC `.py` + 4 `.ipynb`).
**Date**: 2026-05-17
**Author agent**: W25-PHASE2-CASE3 (Claude Opus 4.7, 1M-ctx).

---

## 0. Circularity caveat (READ FIRST)

The ground truth in §3 is derived from this paper's own `metadata.json` card (`reviewer_notes.notes`, `leakage_risk_assessment.notes`, `performance_metrics.*`), which was built by the MLGG team during the W14 ingestion sweep. The RAG knowledge base in §2 was built from a **disjoint corpus** (NCPR peer-reviewer concerns on other papers), so RAG retrieval is genuinely OOD with respect to this paper. **However, the GT itself is one-source and not independently re-extracted by a clinical reviewer for this case** — it inherits any framing bias of the W14 metadata pass. Treat recall numbers as *internal-consistency* metrics, not as an audited benchmark.

---

## 1. Paper card

Li et al. 2020 introduce **BEHRT**, a BERT-style transformer adapted to longitudinal EHR sequences (diagnosis codes + age + segment + position embeddings), pretrained with MLM on **1.6M CPRD patients** (UK primary care) and fine-tuned for **301 future disease prediction tasks**. The paper is widely cited as a foundational EHR-transformer; the GitHub repo at `deepmedicine/BEHRT` ships **4 task notebooks** (`MLM.ipynb`, `NextVIsit-6month.ipynb`, `NextVIsit-12month.ipynb`, `NextXVisit.ipynb`) and supporting modules but **no preprocessing/split scripts that build the train/test parquet files** — `file_config['train']` and `file_config['test']` are blank strings that downstream users must populate themselves. Reported performance metrics are absent from the metadata card (all `test_auroc*` = null), so the case probes **methodology transparency**, not headline numbers. Critically, BEHRT is **not in MLGG-Bench RAG KB**, and CPRD is single-source (no external validation), so this is a true OOD test for the 3-layer hybrid (lint + gate + RAG) on a deep-learning paper where most of the bias surface lies in undisclosed preprocessing rather than visible-in-code mistakes.

---

## 2. 3-layer execution log

| Layer | Command | Result | Notes |
|---|---|---|---|
| **L1 — `mlgg lint`** | `python3 -m mlgg_lint check /tmp/W25_p2_behrt/` | **4 INFO, 0 errors, 0 warnings** | All 4 are **R009** (metrics without CI) in `MLM.ipynb` cell 11 and the three `Next*Visit` notebooks cell 12/18. Linter sees almost nothing because all hard work (split, MLM cohort definition) is *outside the repo* — `file_config` is blank. |
| **L2 — Gates (33 available)** | Inspected `--help` on `sample_size_gate`, `split_protocol_gate`; same evidence-JSON requirement as Phase 1 | **0 gates ran** | Identical Phase-1 finding replicated: every gate needs `--evaluation-report`, `--prediction-trace`, `--protocol-spec`, `--train`, `--test`, etc. None exist for a third-party DL repo with no preprocessing scripts. |
| **L3 — RAG retrieval** | `synthesize_flags_from_rag(query, top_k=20)` with query built from `metadata.json` bibliographic + dataset + design + reporting fields | **20 flags returned (1 CRITICAL + 19 HIGH)** | Synthesizer maps each retrieved peer-concern to a gate code via `category → *_gate` mapping. |

### L1 — lint R-rule histogram (4 findings)

| R-rule | Count | Severity | Location |
|---|---|---|---|
| **R009** metrics without CI | 4 | INFO | `task/MLM.ipynb` cell 11 (×1); `task/NextVIsit-12month.ipynb` cell 18 (×3); `task/NextVIsit-6month.ipynb` cell 18 (×3); `task/NextXVisit.ipynb` cell 12 (×3) — counted as 4 findings (one per notebook) |

**No R007** (target-in-features), **no R020/R027** (ffill/normalize before split), **no R004** (train_test_split without `groups=`) — because the repo *does no splitting in code*. The split is delegated entirely to upstream parquet files. This is a **pattern-blindness failure mode** for lint: when bias-prone steps happen offline, the linter has no surface to fire on.

### L1.5 — manual code inspection (out-of-tool, recorded for §4)

Three concerns visible by reading the notebooks that lint *cannot* express as a rule:

| Concern | Evidence | Severity |
|---|---|---|
| **MLM pretraining on all 1.6M patients with no held-out cohort** | `MLM.ipynb` cell 7: `MLMLoader(data, …); trainload = DataLoader(dataset=Dset, …, shuffle=True)` — `data` is the full parquet, no split. If downstream `test` patients were in MLM pretraining (likely, since no preprocessing script enforces disjointness), patient-level information leaked from test → pretrained weights → downstream eval. | HIGH (potential S01 violation) |
| **Test set used for early-stopping / model selection** | `NextVIsit-12month.ipynb` cell 23: `for e in range(50): train(e); auc, roc = evaluation(); if auc > best_pre: … torch.save(...)`. `evaluation()` is the test loader. This is **M01 violation** (test set in tuning loop). Same pattern in `NextXVisit.ipynb` cell 15. | HIGH (M01) |
| **Primary metric is AUPRC `average_precision_score(..., average='samples')` + AUROC only, no calibration / DCA / threshold metrics** | `NextVIsit-12month.ipynb` cell 18; `NextXVisit.ipynb` cell 12 | MEDIUM (E02 panel incompleteness) |

These three items are caught by *eyes-on-code* but not by lint. They are recorded here because they materially change the per-layer recall in §4.

### L2 — gates that COULD NOT run (replication of Phase-1 verdict)

| Gate | Missing artefact | Same as Phase 1? |
|---|---|---|
| `sample_size_gate` | `--evaluation-report` JSON | yes |
| `split_protocol_gate` | `--protocol-spec`, `--train`, `--test`, `--id-col` | yes |
| `external_validation_gate` | `--prediction-trace`, `--external-validation-report` | yes |
| `calibration_dca_gate` | `--prediction-trace`, `--evaluation-report` | yes |
| `ci_matrix_gate` | `--ci-matrix-report` | yes |
| `model_selection_audit_gate` | `--model-selection-report`, `--tuning-spec` | yes |
| All 27 others | structured evidence JSONs | yes |

**Verdict (Phase-2 replication of Phase-1 finding)**: L2 = **0 / 33 gates** runnable on a raw third-party repo. This is now n=2 (Yan 2020 + Li 2020). The "gates are a pipeline contract" reframing from Phase-1 §8 holds.

### L3 — RAG hit aggregate (top-20)

- **Severity**: 1 CRITICAL, 19 HIGH, 0 MEDIUM/LOW
- **Category histogram**: `external_validation` 5, `study_design` 3, `evaluation_metrics` 3, `split_protocol` 2, `sample_size` 2, `clinical_utility` 2, `preprocessing` 1, `feature_selection` 1, `model_selection` 1
- **Mapped gate codes** (via `category → *_gate`): `external_validation_gate` 5, `cohort_definition_gate` 3, `evaluation_quality_gate` 3, `split_protocol_gate` 2, `sample_size_gate` 2, `clinical_metrics_gate` 2, `missingness_policy_gate` 1, `feature_engineering_audit_gate` 1, `model_selection_audit_gate` 1
- **Domain-relevance of retrieved concerns**: ~7 / 20 are on-topic for EHR-DL transformers (split, external, missingness on MNAR EHR, ICD-code utility, model-vs-baseline comparisons); the rest are conceptual transfers from cardiac / sepsis / NLP papers.

---

## 3. Ground truth — 8 issues (synthesised from `metadata.json` + paper card)

| # | Severity | Issue | Evidence in metadata |
|---|---|---|---|
| GT1 | HIGH | No external validation — single-source CPRD UK primary care | `has_external_validation=false`, `external_auroc=null`, `is_multicenter=false` |
| GT2 | HIGH | Split strategy under-documented (only "random"; patient-level disjointness not confirmed) | `dataset.split_strategy='random'`, `patient_level_split_confirmed=null` |
| GT3 | HIGH | Hyperparameter tuning protocol not reported (M01 risk; tuning_used_test_data=null) | `model.hyperparameter_tuning='not reported'`, `tuning_set='not_reported'` |
| GT4 | HIGH | Incomplete metric panel: no calibration, no DCA, no CI | `calibration_reported=false`, `dca_reported=false`, `bootstrap_ci_reported=false` |
| GT5 | MEDIUM | No TRIPOD-AI / PROBAST-AI compliance claimed | `tripod_ai_claimed=false`, `probast_ai_claimed=false` |
| GT6 | MEDIUM | Data availability restricted (reproducibility friction) | `data_availability='restricted'` |
| GT7 | HIGH | 301 disease-prediction tasks with **no multiple-comparison correction reported** | derived from `outcome` + absence of correction mention |
| GT8 | HIGH | MLM-pretraining-on-all-data + downstream test-set early-stopping = double-leakage risk specific to this architecture | derived from §1.5 manual code inspection (NOT in metadata card; **introduced by this report**) |

GT8 is **new vs. metadata.json** — the card was written before this code scan. Flag for back-propagation into the metadata `leakage_risk_assessment.notes` field (see §9).

---

## 4. Per-issue × per-layer match matrix

| GT | Severity | L1 lint | L1.5 manual | L2 gate | L3 RAG | Hybrid catch? |
|---|---|---|---|---|---|---|
| **GT1** No external validation (CPRD only) | HIGH | ✗ | ✗ | ✗ | ✓ (5 hits cat=`external_validation`) | ✓ via L3 |
| **GT2** Split strategy under-documented | HIGH | ✗ | ~ (visible: code reads pre-split parquets, can't verify disjointness) | ✗ | ✓ (2 hits cat=`split_protocol`, mapped to `split_protocol_gate`) | ✓ via L3 |
| **GT3** Hyperparameter tuning not reported (M01) | HIGH | ✗ | ✓ (early-stopping on test set, see §1.5) | ✗ | ✓ (1 hit cat=`model_selection`, code=`model_selection_audit_gate`) | ✓ via L1.5 + L3 |
| **GT4** No calibration / DCA / CI | HIGH | ✓ (R009 ×4 for CI) | ✓ (no calibration/DCA visible) | ✗ | ✓ (3 hits cat=`evaluation_metrics`, code=`evaluation_quality_gate`; +2 cat=`clinical_utility`) | ✓ via L1 + L1.5 + L3 |
| **GT5** No TRIPOD-AI / PROBAST-AI | MEDIUM | ✗ | ✗ | ✗ | ✗ (no flag mapped to `reporting`) | **✗ MISSED** by all 3 layers |
| **GT6** Restricted data availability | MEDIUM | ✗ | ✗ | ✗ | ✗ | **✗ MISSED** by all 3 layers |
| **GT7** 301 tasks, no multiple-comparison correction | HIGH | ✗ (R019 did NOT fire — no `for model in models:` pattern; the multiple-test is across *outcomes*, not models) | ~ (visible from `MLM` setup but no rule) | ✗ | ~ (no exact category; partially covered by evaluation_quality_gate hits) | ~ partial |
| **GT8** MLM-on-all + test-as-tuning leakage | HIGH | ✗ | ✓ (direct read of MLM.ipynb + NextVisit early-stop loop) | ✗ | ~ (cat=`split_protocol` hits adjacent but don't name the MLM-leakage mechanism) | ✓ via L1.5 (eyes-on-code only) |

Legend: ✓ caught, ~ partial, ✗ missed.

---

## 5. Per-layer recall + complementarity + unique lift

| Metric | L1 lint | L1.5 manual eyes-on | L2 gate | L3 RAG | **Hybrid (L1+L2+L3)** | **Hybrid + L1.5** |
|---|---|---|---|---|---|---|
| Strict recall (✓ only) | 1 / 8 = **12.5%** | 3 / 8 = **37.5%** | 0 / 8 = **0%** | 4 / 8 = **50%** | **4 / 8 = 50%** | **6 / 8 = 75%** |
| Partial recall (✓ + ~) | 1 / 8 = 12.5% | 5 / 8 = 62.5% | 0 / 8 = 0% | 6 / 8 = 75% | **6 / 8 = 75%** | **7 / 8 = 87.5%** |
| Items where this layer is the *sole* catcher | 0 | **1** (GT8) | 0 | **1** (GT1, with some help on GT2 from L1.5 only-partial) | n/a | n/a |
| Items where this layer adds *unique evidence colour* | 1 (R009 file:line for CI gap) | **2** (GT3 early-stop loop file:line; GT8 MLM scope) | 0 | 4 (peer-reviewer prose for GT1/2/3/4) | n/a | n/a |

### Key recall facts (n=2 cumulative)

| Case | L1 recall | L2 recall | L3 recall | Hybrid recall | GT count |
|---|---|---|---|---|---|
| Phase-1 case 1 (Yan 2020) | 43% | 0% | 100% | 100% | 7 |
| Phase-2 case 3 (Li 2020) | 12.5% | 0% | 50% | 50% | 8 |
| Phase-2 case 3 incl. L1.5 manual | n/a | 0% | n/a | **75%** | 8 |

**Striking delta vs Phase 1**: hybrid strict-recall **dropped from 100% → 50%** on this paper. Two root causes:
1. **L1 collapse from 43% → 12.5%** — the BEHRT repo does its splitting *outside the codebase* (blank `file_config` paths), so the lint rules that drove most of Yan-2020's L1 recall (R027 normalize-before-split, R020 ffill-before-split, R004 train_test_split-without-groups) **had no surface to fire on**. Lint depends on the bias-prone step being *visible in code*.
2. **L3 drop from 100% → 50%** — two GT items (GT5 TRIPOD-AI, GT6 data availability) are **reporting-standards concerns**, and the RAG KB is built from peer-reviewer *methods* concerns, not reporting-checklist concerns. There is no record in the KB that maps to "TRIPOD-AI not claimed". This is a **coverage gap in the RAG corpus**, not a retrieval failure.

### L2 contribution

**0% again**. n=2 replication of the Phase-1 finding. Recommend tightening the spec language now rather than waiting for n=8 (see §8).

---

## 6. Over-flag list (precision side, top-10)

| # | Layer | Flag | Why it's over-flag |
|---|---|---|---|
| 1 | L1 R009 | "metrics without CI" in `MLM.ipynb` cell 11 | Half-valid — MLM loss is a training diagnostic, not a publication-grade metric; flagging it is a **scope creep** but technically correct |
| 2 | L3 RAG #1 | AI-EF cardiac echo split_protocol concern | Wrong domain (echo, not EHR-DL); pattern transfers conceptually to GT2 but the peer-reviewer text is about echo cohort overlap |
| 3 | L3 RAG #2 | Vision Transformer multimodal benchmarks | Wrong domain (vision NLP), no direct mapping |
| 4 | L3 RAG #3 | n=11–17 hard-deterioration events | Wrong domain (small-n ICU), GT2/3 mismatch — BEHRT has n=1.6M, the opposite problem |
| 5 | L3 RAG #4 | Multi-Domain Sentiment dataset | Wrong domain (NLP sentiment), no mapping |
| 6 | L3 RAG #5 | ESRD onset clinical question | Wrong outcome focus |
| 7 | L3 RAG #10 | ground-truth responder/non-responder | Different study type |
| 8 | L3 RAG #11 | Preterm vs term obstetric split bias | Different domain |
| 9 | L3 RAG #13 | CVD as binary vs right-censored | Adjacent — partially supports GT4/7 |
| 10 | L3 RAG #18 | GPT-4-generated unit tests | Way off-domain (LLM eval) |

**Over-flag rates**:
- L1: 0 / 4 = **0%** (all 4 R009 findings map to GT4, even if `MLM.ipynb` cell 11 is borderline scope)
- L3: **~13 / 20 = 65% strict over-flag**, ~10 / 20 = 50% if generous about conceptual transfer
- Compare with Phase-1: L1 ≈ 6%, L3 ≈ 25–65%. **L3 precision is consistently the bottleneck, with strict over-flag of ~50–65% on both cases.**

---

## 7. Narrative (≤150 words)

Phase-2 case 3 — BEHRT, an EHR-transformer paper not in MLGG-Bench — replicates the Phase-1 finding that **L2 gates are 0% applicable to external code** (n=2 now), but exposes a **new layer-fragility pattern that Phase-1 hid**: when a repo delegates its preprocessing and splitting to upstream parquet files (BEHRT's `file_config['train']`/`['test']` are blank strings), **lint recall collapses from 43% → 12.5%** because the bias-prone steps simply aren't in the code surface. L3 RAG retrieval recovers 50% (4/8 GT items) but misses GT5/GT6 (reporting standards) because the KB has no TRIPOD-AI / data-availability concerns indexed. Eyes-on-code inspection (L1.5) catches two further critical leakage items lint cannot express (MLM-on-all-data + test-set early-stopping). **Hybrid strict recall = 50% (75% with L1.5)**, far below Phase-1's 100%. Headline implication: hybrid recall is **bounded by the union of (visible-in-code) ∪ (in-KB)**, and BEHRT-class papers fall in the gap.

---

## 8. L2 verdict (explicit)

**L2 = 0 / 33 gates runnable on raw repo, replicated** (Phase-1: 0/33, Phase-2 case 3: 0/33). Same root cause both cases: every gate requires a `--*-report` evidence JSON produced by an MLGG-instrumented training run; a third-party GitHub repo by definition has none. With n=2 the spec language ("L2 — pipeline contract gates, require MLGG-instrumented training run") proposed in Phase-1 §8 is now strongly supported. Recommend landing the rename before Phase-2 case 4 to avoid re-deriving the same conclusion 5 more times.

---

## 9. Phase-2 cumulative deltas vs `hybrid_v1_spec.md`

1. **L2 contribution = 0% (n=2 confirmed)**. Rename spec layer to "pipeline contract gates" — action item before case 4.
2. **L1 recall is highly variable (12.5% – 43%) and depends entirely on whether the repo's preprocessing pipeline is in-tree.** DL papers that ship "load my parquet" boilerplate (BEHRT pattern) expose almost nothing for the linter. Recommend: add a **"preprocessing-surface presence" check** to the L1 pre-flight; if absent, downgrade lint-derived confidence and upweight L3.
3. **RAG KB has a reporting-standards coverage gap.** GT5 (TRIPOD-AI not claimed) and GT6 (restricted data availability) were missed by all 20 top-K retrievals because no peer-reviewer concern in the KB phrases its objection as "TRIPOD compliance" or "data availability". Recommend: backfill the KB with TRIPOD-AI / PROBAST-AI / CONSORT-AI checklist items as first-class concern records.
4. **L1.5 manual eyes-on-code added 2 catches (GT3 M01 early-stop, GT8 MLM-leakage) the tooling missed entirely.** This is an argument for either (a) a new lint rule **R0xx "training loop uses test-set metric for early-stopping or model selection"** — pattern-matchable on `if <metric> > best…: torch.save(...)` near an `evaluation()` call on a test loader, or (b) a structured "post-lint LLM read-through" gate.
5. **GT8 is missing from `metadata.json`.** Recommend appending to `leakage_risk_assessment.notes` (with user approval per CLAUDE.md rule on `references/*.json` non-self-write): *"MLM pretraining on all 1.6M patients with no documented cohort split; downstream test set used for early-stopping in NextVIsit / NextXVisit notebooks — joint S01+M01 risk specific to pretrain+finetune architecture."*

---

## 10. Surprise

The biggest surprise was not the L2 zero (predicted by Phase-1) but **L1's collapse from 43% → 12.5%**. The implicit Phase-1 hypothesis was that lint recall is roughly stable across repos; this case shows it is **bimodal**: high when preprocessing is in-tree (Yan 2020: pandas + sklearn pipeline visible), near-zero when preprocessing is delegated to blank `file_config` paths (BEHRT 2020: 4 notebooks of training loops, all data wrangling upstream and invisible). This means the hybrid spec's "L1 always provides a precision floor" framing is **wrong for a substantial subclass of DL papers**. Phase-2 should compute the in-tree-preprocessing-presence indicator and stratify recall numbers by it.

---

## Appendix A — Raw lint output

```
/tmp/W25_p2_behrt/task/MLM.ipynb[cell 11]:10:16 INFO R009 metrics without CI
/tmp/W25_p2_behrt/task/NextVIsit-12month.ipynb[cell 18]:6:13 INFO R009 metrics without CI
/tmp/W25_p2_behrt/task/NextVIsit-6month.ipynb[cell 18]:6:13 INFO R009 metrics without CI
/tmp/W25_p2_behrt/task/NextXVisit.ipynb[cell 12]:6:13 INFO R009 metrics without CI

Found 4 info(s).
```

## Appendix B — Raw RAG output (top-20 summary)

`SEV`: `{CRITICAL: 1, HIGH: 19}`
`CAT`: `{external_validation: 5, study_design: 3, evaluation_metrics: 3, split_protocol: 2, sample_size: 2, clinical_utility: 2, preprocessing: 1, feature_selection: 1, model_selection: 1}`
`CODES`: `{external_validation_gate: 5, cohort_definition_gate: 3, evaluation_quality_gate: 3, split_protocol_gate: 2, sample_size_gate: 2, clinical_metrics_gate: 2, missingness_policy_gate: 1, feature_engineering_audit_gate: 1, model_selection_audit_gate: 1}`

## Appendix C — Reproduce

```bash
# Clone
cd /tmp && rm -rf W25_p2_behrt && git clone --depth 1 https://github.com/deepmedicine/BEHRT W25_p2_behrt

# L1
cd /Volumes/Seagate/Skill/ml-leakage-guard
python3 -m mlgg_lint check /tmp/W25_p2_behrt/

# L3
python3 -c "
import sys, json; sys.path.insert(0, '.')
from scripts.rag.evals.ncpr_paper_runner import synthesize_flags_from_rag
m = json.load(open('references/case-studies/specialist_journals/other/li_2020_behrt_transformer/metadata.json'))
q = '. '.join([
    m['bibliographic']['title'],
    f\"binary classification predicting {m['study_design']['outcome']}\",
    f\"EHR longitudinal cohort from {m['dataset']['source_name']}, n={m['dataset']['n_patients_total']} patients\",
    f\"transformer BERT-based deep learning, split strategy {m['dataset']['split_strategy']}\",
    '301 disease prediction tasks, no external validation, single-center CPRD UK primary care',
    'no calibration reported, no DCA, no bootstrap CI, no TRIPOD-AI, hyperparameter tuning not reported'
])
print(len(synthesize_flags_from_rag(q, top_k=20)), 'flags')
"
```
