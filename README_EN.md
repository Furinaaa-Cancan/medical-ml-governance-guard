<p align="right">
  English | <a href="./README.md">中文</a>
</p>

<p align="center">
  <br>
  <img src="https://img.shields.io/badge/MLGG-v1.0-FF6B35?style=for-the-badge&labelColor=1a1a2e" alt="MLGG v1.0">
  <br><br>
  <strong style="font-size: 2.5em;">ML Governance Guard</strong>
  <br>
  <em>Top-Journal Review Standards &times; AI-Driven Medical Prediction Model Governance Framework</em>
  <br><br>
  <a href="https://polyformproject.org/licenses/noncommercial/1.0.0/"><img src="https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/tests-5501%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/gates-33%20fail--closed-critical" alt="Gates">
  <img src="https://img.shields.io/badge/datasets-14%20medical-purple" alt="Datasets">
  <img src="https://img.shields.io/badge/code-145K%20lines-informational" alt="Code">
  <a href="https://doi.org/10.1136/bmj-2023-078378"><img src="https://img.shields.io/badge/TRIPOD%2BAI-2024-blue" alt="TRIPOD+AI"></a>
  <a href="https://doi.org/10.1136/bmj-2024-082505"><img src="https://img.shields.io/badge/PROBAST%2BAI-2025-blue" alt="PROBAST+AI"></a>
</p>

---

<p align="center">
<strong>33 Fail-Closed Gates</strong> &middot; <strong>9-Phase Workflow</strong> &middot; <strong>12-Dimension Scoring</strong> &middot; <strong>3-Level Compliance</strong>
<br>
<strong>23 Model Families</strong> &middot; <strong>16 Real Medical Datasets (630K+ rows)</strong> &middot; <strong>335 NC+CM Peer Review PDFs · 154 Curated with Concerns</strong> &middot; <strong>21 Analysis Tools</strong>
<br><br>
<em>Every audit recommendation cites real top-journal peer review opinions as evidence.<br>Not a rule engine &mdash; an AI co-review system that thinks like a Nature Medicine reviewer.</em>
</p>

---

## MLGG vs Claude Skill — Architecture Boundary

> **MLGG is hybrid**: Claude Skill is the shell, Python gates are the core. **Hallucination can change *which gates ran*, but not *whether each gate passed*.**

### Three layers (hallucination risk annotated in-place)

```
┌──────────────────────────────────────────┐
│  SKILL.md + CLAUDE.md  ~380 lines        │  ⚠️ may hallucinate
│  Soft decisions: which stage, intent     │  Consumer: LLM
└──────────────────────────────────────────┘
                  ↓ orchestrates
┌──────────────────────────────────────────┐
│  33 gates  ~40K LOC Python               │  ✅ zero hallucination
│  Hard verdict: pass / fail / critical    │  Consumer: CPython
│  Same input → same output, CI-replayable │
└──────────────────────────────────────────┘
                  ↓ KB lookups
┌──────────────────────────────────────────┐
│  references/  ~2 MB human-curated KB     │  ✅ zero hallucination
│  peer-review-kb.json (154 curated +181 pend)│  Consumer: SQL / JSON
│  codebooks/ukb (8-layer verify, 1.87M)   │
│  methodology/disease-kb.json             │
└──────────────────────────────────────────┘
```

**Hallucination is locked in the top layer** — the lower two always resolve pass/fail via deterministic code + static data.

### Per-action risk: what can hallucination touch?

| Action | Layer | Hallucination risk | Can it change the verdict? |
|---|---|---|---|
| `/mlgg` picks which workflow to run | Skill | ⚠️ | ❌ May skip or double-run, but **each gate that runs is still deterministic** |
| Claude narrates gate output in natural language | Skill | ⚠️ | ❌ Presentation-layer bias only |
| `leakage_gate.py` detects label leakage | Python | ✅ | ❌ Deterministic algorithm |
| `calibration_dca_gate.py` computes ICI / DCA | Python | ✅ | ❌ Pure numeric computation |
| `verify_ukb_codebook.py` runs 8-layer verify | Python | ✅ | ❌ 1.87M cell-level comparison |
| Quoting reviewer opinions from `peer-review-kb.json` | references | ✅ | ❌ Exact SQL / JSON lookup |

### Two usage paths, one verdict

- **Interactive**: `/mlgg` → Claude interprets intent → auto-orchestrates the 9-phase pipeline
- **CI / publication-grade**: `python3 scripts/gates/leakage_gate.py --data x.csv` — skips the Skill entirely, calls the gate directly

Both end up running the **same Python gate**. The Skill saves keystrokes, not correctness.

### Engineering guarantees (not just aspirations)

- **SKILL.md ≤ 500 lines**: currently 290 lines, within Claude Code's official guidance; longer content lives under `docs/` or inside gate docstrings.
- **Pre-commit doc-number check**: `check_docs_consistency.py` + `check_readme_stats.py` catch drift across `SKILL.md ↔ README ↔ reviewer.yaml`; **PRs fail before merge**, not after.
- **Thresholds are code, not prompts**: every pass/fail threshold, validator rule, and detection algorithm is a Python constant + function. Gates do not consult markdown for verdict logic.

---

## Table of Contents

- [MLGG vs Claude Skill — Architecture Boundary](#mlgg-vs-claude-skill--architecture-boundary)
- [Why MLGG](#why-mlgg)
- [System Overview](#system-overview)
- [Quick Start](#quick-start)
- [9-Phase Workflow](#9-phase-workflow)
  - [Phase 1: Cohort Definition & Sample Size](#phase-1-cohort-definition--sample-size)
  - [Phase 2: Data Splitting](#phase-2-data-splitting)
  - [Phase 3: Preprocessing](#phase-3-preprocessing)
  - [Phase 4: Feature Selection](#phase-4-feature-selection)
  - [Phase 5: Model Training & Selection](#phase-5-model-training--selection)
  - [Phase 6: Evaluation & Calibration](#phase-6-evaluation--calibration)
  - [Phase 7: Multi-Model SHAP Interpretability](#phase-7-multi-model-shap-interpretability)
  - [Phase 8: Fairness & Equity](#phase-8-fairness--equity)
  - [Phase 9: Reporting & Compliance](#phase-9-reporting--compliance)
- [33 Safety Gates (Gate DAG)](#33-safety-gates-gate-dag)
- [12-Dimension Scoring](#12-dimension-scoring)
- [33 Methodology Rules](#33-methodology-rules)
- [23 Model Families](#23-model-families)
- [16 Medical Datasets](#16-medical-datasets)
- [28 Static Analysis Rules (R001-R028)](#27-static-analysis-rules-r001-r027)
- [21 Analysis Tools](#21-analysis-tools)
- [Security Hardening Layer](#security-hardening-layer)
- [Project Structure](#project-structure)
- [Installation Guide](#installation-guide)
- [Command Reference](#command-reference)
- [Literature Foundation](#literature-foundation)
- [Claude Code Integration](#claude-code-integration)
- [CI/CD](#cicd)
- [License & Citation](#license--citation)

---

## Why MLGG

The prevalence of data leakage and methodological flaws in medical ML papers far exceeds expectations. The proportion of high risk-of-bias in published prediction models is alarmingly high (Wynants et al. 2020, BMJ; Navarro et al. 2023, BMJ).

| Common Mistake | Consequence | How MLGG Prevents It |
|:---------------|:------------|:---------------------|
| Normalize on full data before splitting | Inflated performance, invisible to reviewers | Gate P01: Pipeline isolation audit |
| Include deceased patients in readmission prediction | Structurally impossible outcome, AUROC contaminated | Gate C01: Cohort definition review |
| Use OrdinalEncoder for nominal variables | LR coefficients lose clinical meaning (measured AUROC +0.02) | Gate P05: Enforce OneHot |
| Report only AUROC without MCC and LR+/LR- | AUROC 0.65 looks acceptable, but MCC 0.12 means near-random | Gate E02: Complete 14-metric panel |
| Use train-test gap for model selection | No literature support, may select suboptimal model | Gate M04: Validation PR-AUC + one-SE |
| Feature selection on full data | Information leaks from test to training set | Gate F03: Training-set-only constraint |
| HbA1c both defines diabetes and serves as predictor | Perfect leakage, model learns the definition itself | Gate C02: Definition column forced exclusion (disease-scoped — glucose is only flagged when the target is diabetes, not e.g. 30-day mortality) |
| Bootstrap CI with normal approximation | Unreliable for small samples/asymmetric distributions | Gate E01: Forced percentile bootstrap |
| `time_in_hospital` / `num_medications` / `discharge_*` used as features | Textbook post-index leakage (diabetes_130 / MIMIC canonical pattern) | Gate L01: feature-name regex catches 5 post-index pattern groups + `forbidden_features` blacklist |
| Doctor-provided `surv2m` / `prg6m` as features | Clinician estimate of the target — near-perfect target leak | Gate C02 + Gate F03: 3 regex families (`surv\d` / `prognos` / `prg\d`) + feature-lineage tracing |
| `received_drug_x` / `prescribed_statin` as features | Immortal time bias: patients who received treatment necessarily survived to the treatment window (Suissa 2008; Hernán 2016) | Gate L01 `IMMORTAL_TIME_RE`: 9 treatment-verb prefixes with exemptions for `history_*` / `prior_*` / `ever_*` / `_before_enrollment` legitimate baselines |
| Cohort filter cascade undocumented — reviewers cannot audit selection bias | Top-3 cause of NC peer-review rejections | Gate C01 `--cohort-spec`: declare inclusion/exclusion cascade → monotonicity + final row-count consistency check; publication-grade tier fails without it |
| Feature names `gene_BRCA1` / `rs12345` / `ENSG00000...` | Out-of-scope: using MLGG for omics data is a modality mismatch | `mlgg-lint` R028: ≥3 omics-pattern name matches → rejected with pointers to Scanpy / TCGAbiolinks / PLINK |

> **MLGG is not yet another ML toolkit.** It is an AI co-review system meeting top-journal review standards &mdash; 33 fail-closed gates + 154 NC+CM curated reviews (Nature Communications + Communications Medicine; 817 structured concerns; 181 additional PDFs cataloged and pending extraction) as a knowledge base. Every recommendation can cite reviewer quotes as evidence.

---

## Reviewer-Grade Review Mechanism

MLGG's core is not running scripts, but **reviewing your code like a top-journal reviewer**.

```
Your code ──→ /mlgg review ──→ Find issues ──→ Cite reviewer quotes ──→ Provide fix code ──→ Re-verify
```

**Three-Layer Review Architecture:**

| Layer | Mechanism | What It Catches |
|:------|:----------|:----------------|
| **Layer 1: 28 AST Static Analysis Rules** | Code pattern matching (R001-R028) | `scaler.fit(X)` before split, SMOTE on test, threshold selected on test |
| **Layer 2: 33 Fail-Closed Gates** | Runtime validation, JSON report output | Patient cross-split, calibration ECE > 0.1, EPV < 10, CI width > 0.20; **post-index feature-name detection** (time_in_hospital / num_medications / discharge / ventilation / vasopressor); **disease-scoped definition-variable matching** (glucose only for diabetes targets) |
| **Layer 3: Clinical Semantic Review + Peer Review Evidence** | AI agent understands code semantics + 154-paper curated peer-review KB (817 concerns) + **issue-code-aware retrieval** | Post-discharge variables predicting post-discharge outcomes, HbA1c definition leakage, missing subgroup calibration. RAG re-ranks by keyword overlap with the actual failure codes — not just severity |

**Peer Review Knowledge Base:**

Structurally extracted 817 review opinions from 154 NC + CM medical ML papers (181 additional PDFs cataloged but pending extraction). **Retrieval precision refactored 2026-04**: the previous `retrieve_by_gate(gate_name)` filtered by `mlgg_gates` then sorted by severity alone (~20% precision on clinical_metrics_gate's ppv-specific failures). The replacement `retrieve_for_failure(gate_name, issue_codes)` tokenizes the failure code list, filters stopwords, and re-ranks by `3 × tag_overlap + text_overlap`; falls back to severity-only when no keywords match so coverage never regresses to empty.

| Category | Proportion | Example Reviewer Quote |
|:---------|:-----------|:-----------------------|
| Evaluation Metrics | 31.7% | *"AUC should not be the only metric. Provide PPV, NPV, calibration."* |
| Study Design | 21.6% | *"Using future data which would not be available for clinical decision."* |
| Reporting Standards | 13.9% | *"Should report calibration and net benefit analysis."* |
| External Validation | 5.6% | *"External validation on independent cohort is essential."* |

**KB index completeness**: all 817 concerns now have at least one `mlgg_gates` mapping (before the 2026-04 backfill, 73.6% were empty arrays and `peer_review_lookup.py --gate` silently missed ~75% of the KB). Warning-only gates (failed via `--strict` warning-upgrade) now also retrieve context — previously they left `peer_review_context: []` because the retrieval was guarded on `failures` only.

**Honest coverage caveat**: the KB is peer-review opinions on already-published NC papers. The pre-publication filter removes egregious leakage, so leakage-category concerns are rare by design (≈4%). The KB is strong on evaluation / reporting / external validation; for leakage failures rely on `leakage_gate` + `mlgg-lint` R001-R028 rather than the KB.

> When MLGG finds an issue in your code, it doesn't just say "violated rule E02" &mdash; it tells you: *"NC+CM reviewers requested improved evaluation metrics 196 times (24%) across 154 papers. This is the most frequently raised concern category."*

**RAG Semantic Retrieval Layer (`scripts/rag/`):** local dense-vector RAG over the 817 reviewer_concerns KB (817 concerns indexed for RAG), covering the colloquial / long-tail / cross-tag queries that pure BM25 misses.

```bash
# 30-second quickstart
python3 scripts/rag/query.py "no calibration in evaluation"
# concern_id          paper_id    severity  score    concern_text
# ------------------  ----------  --------  -------  ------------------------------------------------
# PR-018-EVL          PR-018      HIGH      0.812    AUC should not be the only metric. Provide PPV…
# PR-042-RPT          PR-042      MEDIUM    0.751    Should report calibration and net benefit ana…
# ... (top-5)
```

**Architecture:**

```
query → embed (BGE-small) → cosine top-50 → + BM25 (issue-code) + gate filter
     → tag/canonical-pattern boost + severity tiebreak → top-K
```

**Three usage modes:**

| Scenario | Command | Expected behavior |
|:---------|:--------|:------------------|
| **Free-text** | `python3 scripts/rag/query.py "no calibration in evaluation"` | Returns evaluation_metrics category + MLGG-E02 related concerns |
| **Gate-anchored** | `python3 scripts/rag/query.py "training data leak" --gate leakage_gate --codes future_information_leakage` | Returns CRITICAL leakage concerns under that gate only |
| **Domain-specific** | `python3 scripts/rag/query.py "sepsis prediction in ICU"` | Returns reviewer concerns from sepsis / ICU papers |

**Caching:** first call ~30 s (downloads BGE-small + builds `.cache/rag/concerns_embeddings.npz`); subsequent calls < 1 s (npz reused while KB sha256 is unchanged).

**Gate integration:** any gate can call `scripts.core.gate_rag_bridge.rag_context_for_failure(gate_name, failure_codes)` to embed the reviewer-quote context into its `report.json` under `peer_review_context`, so the "why did this fail" explanation cites a real reviewer's words.

**Limitation:** the current vector model is `BAAI/bge-small-en-v1.5` (384-dim, English-tuned). Chinese-language free-text queries will have reduced precision &mdash; the KB itself is English reviewer text, so English queries hit hardest; for Chinese descriptions of a failure, pass `--codes MLGG-XXX` so the BM25 + tag-overlap path can compensate.

### Known Limitations

The 5-agent strict review surfaced 5 honest limitations users should know about. None are ship-blocking, but all are material to expectation-setting.

**1. BM25 is gate-anchored**

When you call `rag_query(q)` without a `gate=` argument (the CLI default), the hybrid ranker silently skips BM25 and free-text scoring becomes dense + tag + severity only. After the F1 fix, active weights are re-normalized so final scores still reach 1.0, but users should know BM25 is a gate-anchored signal.

> For production gate hooks, always pass `(gate, failure_codes)` to get the full 4-signal ranking. CLI users querying for exploration should expect dense-dominated results.

**2. Four MLGG dimensions have weak retrieval**

Mean P@5 over 12 representative queries is 0.80. Four dimensions scored below 0.4:

| Dimension | P@5 | Why |
|:----------|:----|:----|
| Complete-case missing data | 0.2 | KB lexically thin; severity boost masks the gap |
| AUROC without CI | 0.2 | Embedding anchors on the "AUROC" token; can't model "without" |
| Temporal hold-out | 0.3 | KB sparse on time-series concerns |
| Tuning-on-test | 0.4 | Canonical-pattern boost promotes adjacent topics |

> When retrieving for these dimensions, manually inspect the top-5 for relevance.

**3. Four infra gates have honest empty RAG by design**

The following gates have no peer-review precedent in the KB by design (infrastructure / meta layers):

- `manifest_lock` &mdash; file integrity
- `request_contract_gate` &mdash; request validation
- `security_audit_gate` &mdash; security check
- `self_critique_gate` &mdash; reflection layer

After the F2 fix, the gate report no longer shows a placeholder for these. Before F2, the placeholder said "no concerns retrieved" which was misleading.

**4. Cold first-query latency**

The first call after process start incurs ~228 ms vs steady-state ~12 ms (model load + first BGE forward pass). Consider adding a `prewarm()` call in long-running services. Cold index build (no cache) is ~15 s on CPU.

**5. Memory footprint**

Steady-state RSS ~460 MB per process (BGE-small + tokenizer + 817 &times; 384 float32 matrix). Plan accordingly for multi-worker gate runners.

---

## System Overview

```
Raw Data ──→ 9-Phase Workflow ──→ 33-Gate Audit ──→ Compliance Certificate ──→ Publication-Ready Report
```

| Module | Description | Scale |
|:-------|:------------|:------|
| **33 Safety Gates** | Fail-closed DAG architecture covering leakage/interpretability/fairness/calibration/robustness/TRIPOD+AI/PROBAST+AI | 9-layer parallel execution |
| **12-Dimension Scoring** | Data integrity/leakage protection/pipeline isolation/model selection/statistical validity/generalization evidence/clinical completeness/reporting standards/reproducibility/security/fairness/sample size | 0-100 score |
| **3-Level Compliance** | L1 (12 gates, leakage audit) / L2 (25 gates, statistically valid) / L3 (all 33 gates, publication-grade) | Progressive certification |
| **23 Model Families** | LR (L1/L2/ElasticNet) / SVM (linear/RBF) / RandomForest (balanced) / ExtraTrees / XGBoost / CatBoost / LightGBM / HistGradientBoosting / KNN / MLP / AdaBoost / RUSBoost / EasyEnsemble / BalancedRandomForest / GaussianNB / DecisionTree / TabPFN + Stacking / Soft-Voting / Weighted-Voting | Auto hyperparameter search |
| **16 Real Datasets** | UCI / CDC / NCI / Vanderbilt official data | 630K+ total rows |
| **Multi-Model SHAP Engine** | Multi-family L1-normalized ensemble + Kendall tau consistency (FDR-BH correction) + cross-model Spearman rank correlation + 5 publication-grade CSVs | RF/XGB/CatBoost/LGBM/LR |
| **Academic Compliance Engine** | TRIPOD+AI 2024 (27 items) / PROBAST+AI 2025 (4 domains) / STARD-AI | Item-by-item verification |
| **Peer Review Evidence Base** | 154 NC+CM papers &times; 817 structured review opinions, retrieved by gate/tag/severity (181 additional PDFs cataloged but pending) | Each recommendation cites original text |
| **28 Lint Rules** | Static analysis detecting code-level leakage anti-patterns (R001-R028) | .py + .ipynb |
| **Security Hardening Layer** | HMAC-SHA256 / AES-256-GCM / chained audit log / path traversal defense / restricted deserialization | fail-closed |
| **21 Analysis Tools** | Riley sample size / calibration triple / NRI-IDI / learning curve / VIF / MNAR sensitivity / PDP marginal effects / FDR-BH correction / temporal drift / ... | 100% Nature ML Checklist coverage |

---

## Quick Start

### 30 Seconds: Check Your Data for Leakage

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
cd medical-ml-governance-guard
pip install -r requirements.txt

# Built-in heart disease dataset: split → detect leakage (2 commands)
python3 scripts/training/split_data.py \
  --input examples/heart_disease.csv --output-dir /tmp/mlgg_demo \
  --target-col y --patient-id-col patient_id --time-col event_time \
  --strategy grouped_temporal --seed 42

python3 scripts/gates/leakage_gate.py \
  --train /tmp/mlgg_demo/train.csv --valid /tmp/mlgg_demo/valid.csv \
  --test /tmp/mlgg_demo/test.csv \
  --target-col y --id-cols patient_id --time-col event_time \
  --report /tmp/mlgg_demo/leakage_report.json
```

Output `Status: PASS` = correct split, no patient overlap, no temporal leakage. Replace `heart_disease.csv` with your own CSV and column names.

> Full 5-minute tutorial: [Beginner-Quickstart.md](references/docs/Beginner-Quickstart.md)

### AI Reviewer Full Guidance (Recommended)

```bash
claude          # Open Claude Code
/mlgg           # AI reviewer guides 9-phase workflow
```

Auto-completes: observe data → split → train 23 model families → 33-gate audit → TRIPOD+AI compliance report. Cites real peer review opinions at each step.

### More Entry Points

```bash
python3 scripts/orchestration/mlgg.py doctor         # Verify installation
python3 scripts/orchestration/mlgg.py play           # Pixel-art terminal UI

# Guided modeling (no Claude Code needed)
python3 scripts/orchestration/mlgg.py onboarding \
  --project-root /tmp/mlgg_demo --mode guided --yes

# Audit any ML project (zero configuration)
python3 scripts/reporting/generate_audit_report.py --project-dir /path/to/project

# Static code scan (28 AST leakage rules)
cd plugin && pip install -e . && cd ..
python3 -m mlgg_lint check /path/to/your_script.py
```

---

## 9-Phase Workflow

MLGG enforces sequential execution across 9 phases, each with explicit checkpoints &mdash; no proceeding without passing.

```
  Phase 1          Phase 2          Phase 3          Phase 4
  Cohort     ────>  Data       ────>  Prepro-    ────>  Feature
  Definition        Splitting         cessing          Selection
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ EPV      │       │ Patient │       │ Fit on  │       │ ElasticN│
  │ Riley    │       │ disjoint│       │ train   │       │ Stability│
  │ Missing  │       │ Temporal│       │ only    │       │ Ridge   │
  │ Types    │       │ order   │       │ OneHot  │       │ control │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       v                  v                  v                  v
  Phase 5          Phase 6          Phase 7          Phase 8
  Model      ────>  Evaluation ────>  Interpret- ────>  Fairness
  Training          & Calibr.        ability          & Equity
  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐
  │ >=3 fam │       │ 14 metr │       │ Multi   │       │ EqOdds  │
  │ One-SE  │       │ Boot CI │       │ model   │       │ Disparate│
  │ Optimism│       │ DCA+NRI │       │ SHAP    │       │ Subgroup│
  │ LrnCurve│       │ Calibr  │       │ Kendall │       │ DCA     │
  └────┬─────┘       └────┬────┘       └────┬────┘       └────┬────┘
       │                  │                  │                  │
       └──────────────────┴────────┬─────────┴──────────────────┘
                                   v
                            Phase 9: Reporting & Compliance
                            ┌─────────────────┐
                            │ TRIPOD+AI 2024  │
                            │ PROBAST+AI 2025 │
                            │ L1 / L2 / L3    │
                            │ 12-Dim Score    │
                            └─────────────────┘
```

---

### Phase 1: Cohort Definition & Sample Size

> **Script**: `cohort_definition_gate.py` &nbsp;|&nbsp; **Layer**: 0 &nbsp;|&nbsp; **Rules**: C01, F05, Z01

#### 1.1 Cohort Definition (MLGG-C01)

Exclude records where the outcome is structurally impossible. For example, in readmission prediction, deceased/hospice patients cannot be readmitted &mdash; including them inflates AUROC (measured +0.004). Exclusion rules must be determined before any analysis, with exclusion counts and reasons documented (TRIPOD+AI Item 4a).

#### 1.2 Sample Size &mdash; Riley Triple Criteria (Riley 2019, Stat Med)

The traditional EPV >= 10 rule has been shown to be "overly simplistic and lacking evidence" (Riley 2019 original text). MLGG implements three criteria:

| Criterion | Formula (simplified) | Meaning | Threshold |
|:----------|:---------------------|:--------|:----------|
| C1 Shrinkage factor | n >= p / ((1-S) x phi), S >= 0.9 | Prediction coefficients shrink no more than 10% | S >= 0.90 |
| C2 Optimism | n >= p / 0.05 | R^2 apparent vs adjusted difference <= 0.05 | delta <= 0.05 |
| C3 Precision | n >= phi(1-phi) / (0.05/1.96)^2 | Overall risk estimate 95% CI half-width <= 0.05 | SE <= 0.05 |

Take the maximum of all three as the minimum sample size. p = candidate parameters, phi = event rate.

| EPV Range | Verdict |
|:----------|:--------|
| EPV < 5 | **FAIL** &mdash; Severely insufficient sample size |
| EPV 5-10 | **WARNING** &mdash; Additional evidence required |
| EPV 10-20 | **INFO** &mdash; Acceptable, recommend >= 20 |
| EPV >= 20 | **PASS** |

#### 1.3 Automatic Data Type Detection

Each column is classified by cardinality and type:

| Type | Detection Condition | Processing |
|:-----|:--------------------|:-----------|
| `numeric` | High-cardinality continuous values | Keep original |
| `binary` | Exactly 2 unique values | Map to 0/1 |
| `categorical` | 3-20 unique values | OneHot encoding |
| `constant` | 0-1 unique values | Auto-drop |
| `id_or_text` | High-cardinality non-numeric | Flag as non-feature |

Output: `feature_profile.csv` with missing rate, unique count, and descriptive statistics per column.

#### 1.4 Missing Value Profile

Missing rates computed per feature. >50% missing auto-flagged. Correlation between missingness and outcome detected (|r| > 0.1 flagged as MNAR signal). Longitudinal/cross-sectional detection: duplicate patient IDs -> longitudinal data.

#### 1.5 Suspicious Correlation Detection

| Condition | Verdict | Meaning |
|:----------|:--------|:--------|
| \|r\| > 0.95 | **FAIL** | Almost certainly leakage |
| \|r\| > 0.80 | **WARNING** | High risk, manual review needed |
| \|r\| > 0.50 | **INFO** | Normal predictive power |

---

### Phase 2: Data Splitting

> **Script**: `split_data.py` &nbsp;|&nbsp; **Gates**: `split_protocol_gate` + `leakage_gate` &nbsp;|&nbsp; **Rules**: S01, S02

#### 2.1 Patient-Level Disjoint Splitting (MLGG-S01)

All records of the same patient (e.g., multiple hospitalizations) must belong to the same split. Violating this allows the model to "memorize" patient characteristics, inflating test performance. Implementation: group by `patient_id`, groups as the minimum indivisible unit.

#### 2.2 Three Splitting Strategies

| Strategy | Suitable Data | Time Column | Rationale |
|:---------|:-------------|:------------|:----------|
| `grouped_temporal` | Longitudinal EHR / cohort | Required | Sort by patient's first event time, first 60% train / middle 20% valid / last 20% test. Guarantees train time < valid < test (MLGG-S02) |
| `grouped_random` | Cross-sectional surveys (NHANES, BRFSS) | Not needed | Patients randomly shuffled then proportionally assigned. `--cross-sectional` skips temporal checks |
| `stratified_grouped` | Cross-sectional + need consistent positive class ratio | Not needed | Stratify by outcome label, random assignment within strata, positive rate difference < 3% across splits |

#### 2.3 Safety Constraints

| Constraint | Threshold | Violation Consequence |
|:-----------|:----------|:----------------------|
| Min rows per split | 20 | FAIL |
| Min positive cases per split | 10 | FAIL |
| Min negative cases per split | 10 | FAIL |
| Min independent patients per split | 5 | FAIL |
| Positive rate drift across splits | > 10% | WARNING |
| Patient ID overlap across splits | Any | **FAIL (zero tolerance)** |

#### 2.4 Leakage Detection (7 Regex Categories)

The leakage gate detects 7 categories of suspicious feature name patterns:

| Category | Match Patterns | Examples |
|:---------|:---------------|:---------|
| Explicit labels | `future`, `leak` | `future_value`, `data_leak` |
| Target aliases | `target`, `label`, `outcome` | `target_col`, `outcome_flag` |
| Post-diagnosis variables | `pred_`, `confirmed_`, `staging` | `pred_risk`, `confirmed_diagnosis` |
| Pathology results | `pathology`, `biopsy_result`, `histology` | `biopsy_result_code` |
| Temporal leakage | `next_`, `future_`, `post_`, `after_` | `next_visit_date`, `post_surgery` |
| Outcome dates | `diagnosis_date`, `death_date`, `event_date` | `discharge_date` |
| Derived metrics | `readmit`, `mortality_flag`, `los_days` | `readmit_30d`, `survival_status` |

#### 2.5 Output Artifacts

- `train.csv`, `valid.csv`, `test.csv`
- `split_protocol.json` (auto-generated, gate-verifiable)
- `split_report.json` (SHA-256 checksums)

---

### Phase 3: Preprocessing

> **Script**: `train_select_evaluate.py` Pipeline &nbsp;|&nbsp; **Rules**: P01-P06

#### 3.1 Iron Rule: All fit() Only on Training Set (P01/P03/P04)

Preprocessing pipeline structure: `Imputer -> Scaler -> Classifier`. Statistics at every step (median, mean, std, category mappings) are computed only from the training set; validation and test sets only call `.transform()`. This prevents the most common data leakage &mdash; preprocessing leakage (Kaufman 2012, ACM TKDD).

#### 3.2 Categorical Variable Encoding (MLGG-P05)

| Feature Type | Detection | Encoding Method | OOD Safety |
|:-------------|:----------|:----------------|:-----------|
| Binary (2 values) | `nunique == 2` | Map to 0/1 per train, `.fillna(0.0)` | Unseen category -> 0.0 |
| Categorical (3-15 values) | `3 <= nunique <= 15` | OneHot, train categories determine dummy columns | Unseen category -> all-zero row |
| Numeric (>15, continuous) | `nunique > 15` and numeric | Keep original | N/A |
| High-cardinality (>15 non-numeric) | `nunique > 15` and string | Keep original (user handles) | N/A |

**Why not OrdinalEncoder for nominal variables**: Nominal variables (e.g., race=1,2,3,4,5) with OrdinalEncoder make the model assume race=5 is 5x race=1 &mdash; LR coefficients lose clinical meaning (measured: switching to OneHot improved LR AUROC by +0.02).

#### 3.3 Tiered Missing Data Strategy (MLGG-P06, Madley-Dowd 2019)

Instead of fixed thresholds (e.g., "drop >60% missing"), stratify by missing mechanism:

| Tier | Missing Rate | Recommended Strategy | Rationale |
|:-----|:-------------|:---------------------|:----------|
| Tier 4 | > 80% | Drop values, keep missing indicator | Extremely sparse; "whether missing" may itself be predictive |
| Tier 3 | 40-80% | Impute + missing indicator | Imputation may be inaccurate; indicator compensates |
| Tier 2 | 5-40% | Impute + missing indicator | Standard MAR handling |
| Tier 1 | < 5% | Simple imputation (median/mode) | Too little missing to warrant complex handling |

> **Implementation note**: Current code uses `SimpleImputer(median, add_indicator=True)` uniformly. The tiered approach above is the recommended analytical framework. Tree models (RF/XGB/LGBM) do not add indicator columns (native missing handling).

> **Mechanism testing enforced**: When any feature has >5% missing, `missingness_policy_gate` requires `mechanism_assessment` in the policy (method + conclusion: MCAR/MAR/MNAR/mixed); >40% additionally requires `mnar_sensitivity` analysis results. Per Madley-Dowd 2019, Cro 2020.

#### 3.4 SMOTE Position

van den Goorbergh 2022 (JAMIA) demonstrated that SMOTE severely harms probability calibration in risk prediction models. MLGG defaults to no SMOTE, using `class_weight="balanced"` + post-hoc Platt scaling calibration instead.

---

### Phase 4: Feature Selection

> **Script**: `train_select_evaluate.py` &nbsp;|&nbsp; **Rules**: F01-F06

#### 4.1 Design Philosophy

Harrell 2015 and Steyerberg 2019 recommend "clinical prior pre-specification + penalized shrinkage" over data-driven selection. But when candidate features far exceed clinical knowledge, MLGG provides controlled selection paths.

#### 4.2 Elastic Net CV (Zou & Hastie 2005)

Joint regularization parameter tuning:
- alpha in {0.1, 0.3, 0.5, 0.7, 1.0}: 0.1 approaches Ridge (retain all features), 1.0 equals LASSO (sparse)
- C in {0.001, 0.01, 0.1, 1.0, 10.0}
- 5-fold StratifiedKFold internal CV, select optimal combination by PR-AUC
- **Group selection** (Yuan & Lin 2006, Group LASSO): OneHot-generated dummy columns belong to the same original variable and must enter/exit together

#### 4.3 Stability Selection (Meinshausen & Buhlmann 2010)

- 100 subsampling iterations (each draws 80% of training set)
- Fit Elastic Net (C=0.3, L1) each time, record non-zero features
- Feature selection probability = times selected / 100
- Retain features with selection probability > 0.6
- **Correction**: Use global train median for imputation (not bootstrap local median) to avoid information leakage

#### 4.4 Ridge Control (Harrell 2015)

Always compare with a "no selection, Ridge shrinkage only" full model. If Elastic Net selection causes PR-AUC loss > 0.005, fall back to full Ridge.

#### 4.5 Deprecated: Univariate Screening

Heinze 2018 (Biometrical Journal) explicitly opposes univariate p-value screening: causes multiple comparison problems, discards weak but jointly effective features, introduces selection bias. MLGG only uses univariate analysis (Mann-Whitney U) as a diagnostic tool, not for feature selection decisions.

---

### Phase 5: Model Training & Selection

> **Script**: `train_select_evaluate.py` &nbsp;|&nbsp; **Gate**: `model_selection_audit_gate` &nbsp;|&nbsp; **Rules**: M01-M04, R01

#### 5.1 Training Pipeline Structure

Each candidate model is constructed as an sklearn `Pipeline`, ensuring preprocessing and model training are strictly bound:

```
Pipeline([
    ("imputer",    SimpleImputer(strategy="median", add_indicator=True)),
    ("scaler",     StandardScaler()),
    ("classifier", model)      # e.g., LogisticRegression / RandomForest / XGBoost ...
])
```

- **Imputer**: Median imputation + missing indicators (tree models skip indicators, native missing handling)
- **Scaler**: StandardScaler fit only on training set, validation/test only transform
- **Classifier**: Determined by model family, with predefined hyperparameter grids

#### 5.2 Candidate Model Families (MLGG-M03: >= 3)

MLGG supports 23 model families (see [23 Model Families](#23-model-families)), recommending comparison of at least 3:

| Recommended Family | Advantages | Typical Hyperparameter Grid |
|:-------------------|:-----------|:---------------------------|
| **Logistic Regression** (L1/L2/ElasticNet) | Linear baseline, coefficients directly clinically interpretable | C in {0.01, 0.1, 1, 10}, penalty in {l1, l2, elasticnet} |
| **Random Forest** | Non-linear + feature interactions, natively handles missing | n_estimators in {300, 500}, max_depth in {4, 5, 6} |
| **XGBoost / LightGBM** | Gradient boosting, typically best performance | n_estimators in {200, 400}, max_depth in {3, 5, 7}, learning_rate in {0.01, 0.05, 0.1} |
| **CatBoost** (optional) | Native categorical encoding | depth in {4, 6, 8}, learning_rate in {0.03, 0.1} |
| **SVM** (optional) | High-dimensional spaces, advantages with small samples | C in {0.1, 1, 10}, kernel in {linear, rbf} |

Tuning: Optuna TPE sampler or Grid Search, tuned on **validation set**, never touching test set. Default 5-fold StratifiedKFold internal CV.

#### 5.3 Model Complexity Ranking

The one-SE rule requires "select simplest model", so each candidate has a complexity score:

```
Family base complexity (lower = simpler):
  Gaussian NB (1) < LR-L1 (2) < LR-L2 (3) < LR-EN (4) < KNN (5)
  < Decision Tree (6) < SVM-linear (7) < SVM-rbf (8) < AdaBoost (9)
  < RF (10) < ExtraTrees (11) < HistGB (12) < MLP (13)
  < XGBoost (14) < CatBoost (15) < LightGBM (16) < TabPFN (17)

Within-family ranking: complexity points added by hyperparameters
  - LR: larger C = more complex (weaker regularization)
  - RF: deeper max_depth + more n_estimators = more complex
  - XGBoost: depth x tree count x learning rate combination

Ensemble models: complexity = 15000+ (always ranked last)
```

#### 5.4 Class Imbalance Handling

Medical data is typically severely imbalanced (5-15% positive class). MLGG supports 7 strategies, **all resampling performed only on training set**:

| Strategy | Implementation | Use Case |
|:---------|:---------------|:---------|
| `auto` | Auto-select based on imbalance ratio | Default recommended |
| `none` | No handling | Balanced data |
| `class_weight` | `class_weight="balanced"` | **Recommended** &mdash; no synthetic samples, pair with Platt scaling |
| `random_oversample` | Random duplication of minority class | Simple, no noise introduced |
| `random_undersample` | Random removal of majority class | When data is abundant |
| `smote` | Synthetic minority oversampling | **Use with caution** &mdash; van den Goorbergh 2022 proved calibration harm |
| `adasyn` | Adaptive synthetic sampling | **Use with caution** &mdash; same issues as SMOTE |

> **Iron rule**: Resampling only affects training set (`apply_imbalance_strategy_to_train()`); validation and test sets maintain original distribution.

#### 5.5 Cross-Validation Details

| Parameter | Default | Description |
|:----------|:--------|:------------|
| CV folds | 5 | StratifiedKFold, consistent positive class ratio per fold |
| Min folds | 3 | Below 3 folds forces error |
| Selection data source | `cv_inner` | Model selection based on internal CV out-of-fold predictions |
| Alternative source | `valid` | Use independent validation set (suitable for large datasets) |
| Nested CV | `nested_cv` | Outer selects model + inner tunes params (strictest but slowest) |

When using `cv_inner`, the model performs K-fold CV on training set, collects out-of-fold predictions, and computes PR-AUC on OOF for model selection. **The test set never participates in any selection process.**

#### 5.6 Model Selection Criteria (MLGG-M04, Yang KDD 2023)

**Do not use train-test gap for model selection.** Yang et al. 2023 proved validation set performance is a more reliable model selection criterion:

```
  Wrong approach:  Select model with smallest |AUC_train - AUC_test|
  MLGG:            Select model with highest validation PR-AUC (one-SE rule breaks ties)
```

**One-SE Rule**: Within 1 standard error of optimal performance, select the model with lowest complexity (prefer LR > RF > XGBoost):

```python
best_se = best_std / sqrt(n_folds)        # Standard error of best model
threshold = best_mean - best_se            # Minimum acceptable performance
eligible = [m for m in candidates if m.mean >= threshold]  # Filter eligible
selected = min(eligible, key=complexity_rank)               # Select simplest
```

#### 5.7 Overfitting Callback Mechanism

When the selected model's train-test gap exceeds thresholds, an overfitting callback automatically triggers:

```
1. Compute overfitting risk:
   - PR-AUC gap > 0.15  →  risk = "high"
   - PR-AUC gap > 0.10  →  risk = "medium"
   - Otherwise           →  risk = "low"

2. If risk >= "medium":
   - Search candidate pool for alternative with smaller gap
   - Alternative must still satisfy one-SE rule
   - If found, switch to alternative and log fallback_trace
   - If not found, keep original model but emit WARNING

3. Output:
   - callback_activated: true/false
   - original_model_id: original selection
   - fallback_trace: alternative search process
```

> Gap is still **not used for model selection** &mdash; callback only triggers as a safety net after selection is complete.

#### 5.8 Threshold Selection (MLGG-M02)

Optimal classification threshold determined on **validation set** via F-beta maximization + clinical constraints. Threshold is never selected on test set (MLGG-M01 zero tolerance).

**Selection process**:

```
1. Generate 299 quantile thresholds + 0.5 (300 candidates total)
2. For each threshold, compute metrics on selection set (valid/cv_inner OOF)
3. Filter "feasible thresholds" satisfying all clinical constraints
4. Select highest F-beta among feasible thresholds
5. If guard split exists (internal cross-validation), secondary validation on guard split
6. If guard split has no feasible thresholds, select threshold with minimum constraint violation
```

Default clinical constraints (overridable via `--sensitivity-floor` etc.):

| Clinical Metric | Default Floor | Meaning |
|:----------------|:-------------|:--------|
| Sensitivity | >= 0.70 | Max 30% missed diagnosis rate |
| NPV | >= 0.70 | Negative predictive value floor |
| Specificity | >= 0.60 | Max 40% false positive rate |
| PPV | >= 0.50 | Positive predictive value floor |

> **Why not Youden's J**: Youden's J (Sensitivity + Specificity - 1) ignores clinical constraints. F-beta + clinical floors guarantee the model operates within clinically acceptable ranges. For example, Youden's J might select a threshold with Sensitivity=0.50 (missing half the patients), while MLGG's constraints prevent this.

#### 5.9 Probability Calibration

`class_weight="balanced"` distorts predicted probabilities (ECE can reach 0.3-0.4). MLGG automatically performs probability calibration after training:

| Calibration Method | Implementation | Use Case |
|:-------------------|:---------------|:---------|
| Platt scaling | `CalibratedClassifierCV(method="sigmoid")` | **Default** &mdash; suitable for most models |
| Isotonic regression | `CalibratedClassifierCV(method="isotonic")` | Non-monotonic relationships |
| No calibration | &mdash; | Model natively calibrated (e.g., LR) |

Calibrator fit on **validation set**, applied to test set. Post-calibration ECE should be < 0.06.

#### 5.10 Bootstrap Optimism Correction (Steyerberg 2019 Ch.17)

Internal validation method estimating the "optimistic bias" of model performance:

```
For B bootstrap resamples (B >= 100):
    1. Fit model on bootstrap sample
    2. Score on bootstrap sample → apparent_i
    3. Score on original training set → test_i
    4. optimism_i = apparent_i - test_i

Corrected performance = original apparent performance - mean(optimism_i)
```

Output: `bootstrap_optimism_correction` block with apparent / optimism / corrected values for pr_auc / roc_auc / brier.

#### 5.11 Learning Curve (Figueroa 2012)

Assess whether the model has "converged" &mdash; whether adding more training data still improves performance:

- Train at {10%, 20%, 30%, 50%, 70%, 85%, 100%} of training set
- Stratified subsampling at each proportion to maintain positive class ratio
- Convergence criterion: relative std of last 3 points < 2%
- Output: `learning_curve` block with train_score / valid_score + converged flag per point
- If not converged, suggest increasing data or simplifying model

#### 5.12 Definition Column Forced Exclusion

`--definition-cols HbA1c,fasting_glucose` &mdash; outcome definition columns are **forcibly excluded**, not merely suggested. Prevents the most common medical ML leakage: variables used to define the outcome mixed into prediction features.

#### 5.13 Output Artifacts

All artifacts generated after training, signed with HMAC-SHA256:

| Artifact | File | Content |
|:---------|:-----|:--------|
| Best model | `model.pkl` | Serialized Pipeline (Imputer + Scaler + Classifier + Calibrator + Threshold) |
| Model pool | `model_pool.pkl` | Best candidate per family (for SHAP analysis) |
| Selection report | `model_selection_report.json` | Candidate pool, CV scores, one-SE trace, selected model |
| Evaluation report | `evaluation_report.json` | Test metrics, CI, overfitting analysis, calibration, DCA, NRI/IDI |
| Prediction trace | `prediction_trace.csv.gz` | Per-row y_true / y_score / y_pred (for replay verification) |
| Feature engineering report | `feature_engineering_report.json` | Feature selection process, stability, VIF, nonlinearity tests |
| Distribution report | `distribution_report.json` | Feature distribution drift (JSD) across train/valid/test |
| CI matrix report | `ci_matrix_report.json` | Bootstrap 95% CI for all metrics |
| Robustness report | `robustness_report.json` | Temporal slice and subgroup performance |
| Seed sensitivity report | `seed_sensitivity_report.json` | Multi-seed stability analysis |
| Permutation null | `permutation_null.txt` | PR-AUC permutation test null distribution |

---

### Phase 6: Evaluation & Calibration

> **Script**: `train_select_evaluate.py` + 13 statistical gates &nbsp;|&nbsp; **Rules**: E01-E06

#### 6.1 Complete 14-Metric Panel (MLGG-E02)

Test set used once, reporting 5-domain 14-item metrics (benchmarked against Riley et al. Lancet Digital Health 2025; doi:10.1016/S2589-7500(25)00021-4):

| Domain | Metrics | Target/Interpretation |
|:-------|:--------|:----------------------|
| **Discrimination** | AUROC, PR-AUC | Model's ability to distinguish positive/negative. PR-AUC more sensitive to imbalanced data |
| **Calibration** | Calibration intercept(->0), slope(->1), O:E ratio(->1), ECE | Consistency between predicted probabilities and actual risk (Van Calster 2019) |
| **Overall Performance** | Brier score | BSS = 1 - Brier_model / Brier_prevalence, >0 beats baseline |
| **Classification** | Sensitivity, Specificity, PPV, NPV, F1, **MCC**, Accuracy | MCC is the only reliable single classification metric for imbalanced data (Chicco 2020) |
| **Clinical Utility** | **LR+, LR-**, DCA net benefit, NRI, IDI | LR+ > 5 has clinical value, LR- < 0.2 can rule out (Deeks 2004) |

> **Why MCC and LR+/LR- must be reported**: AUROC 0.65 might look "okay", but MCC 0.12 (near-random) and LR+ 1.6 (no decision value) reveal the model's true capability. Reporting only AUROC/F1 is selective reporting.

#### 6.2 Calibration Triple (Van Calster 2019, BMC Medicine)

Via logistic recalibration fitting `logit(y) ~ a + b x logit(y_hat)`:

| Metric | Ideal Value | Deviation Meaning | Gate Threshold |
|:-------|:------------|:------------------|:---------------|
| Calibration intercept a | 0 | a < 0 systematic overestimation; a > 0 systematic underestimation | \|a\| <= 1.00 |
| Calibration slope b | 1 | b < 1 overfitting; b > 1 underfitting | 0.80 <= b <= 2.00 |
| O:E ratio | 1 | Observed vs expected events | 0.70-1.43 (fail), 0.80-1.25 (warn) |
| ECE | 0 | Predicted probability binned error | <= 0.06 |
| CITL | 0 | Calibration-in-the-large | \|CITL\| <= 0.10 (fail), <= 0.05 (warn) |

#### 6.3 Decision Curve Analysis (Vickers 2006)

DCA evaluates clinical net benefit at different decision thresholds:

| Parameter | Default | Meaning |
|:----------|:--------|:--------|
| Threshold grid | 0.05-0.50, step 0.05 | Clinical decision threshold range |
| Superiority coverage | >= 50% | Proportion of thresholds where model outperforms "treat all" |
| Average benefit | >= 0.0 | Average net benefit improvement |

#### 6.4 NRI / IDI (Pencina 2008)

| Metric | Meaning |
|:-------|:--------|
| Categorical NRI | Net proportion correctly reclassified at threshold |
| Continuous NRI | Reclassification improvement independent of threshold |
| IDI | Improvement in predicted probability difference between event and non-event groups |

#### 6.5 Bootstrap 95% CI (MLGG-E01)

All primary metrics use percentile bootstrap for 95% CI:

| Parameter | Default | Constraint |
|:----------|:--------|:-----------|
| Test CI resamples | 500 | >= 200 (evaluation_quality_gate) |
| CI matrix resamples | 2000 | Covers all splits and cohorts |
| Permutation resamples | 300 | Permutation test null distribution |
| CI width max | 0.20 | Exceeding triggers FAIL |
| Min baseline delta | 0.01 | Must outperform prevalence baseline |

#### 6.6 Generalization Gap Thresholds

| Comparison | Metric | WARNING | FAIL |
|:-----------|:-------|:--------|:-----|
| train -> valid | PR-AUC | > 0.05 | > 0.08 |
| valid -> test | PR-AUC | > 0.04 | > 0.06 |
| train -> test | F2-beta | > 0.07 | > 0.10 |
| valid -> test | Brier | > 0.02 | > 0.03 |

Gap is only used for diagnostic reporting, not for model selection (MLGG-E04).

#### 6.7 Multi-Seed Stability (MLGG-R02)

| Metric | Std Max | Range Max |
|:-------|:--------|:----------|
| PR-AUC | 0.03 | 0.08 |
| F2-beta | 0.05 | 0.12 |
| Brier | 0.02 | 0.05 |

Strict mode requires >= 5 seeds, non-strict >= 3 seeds.

#### 6.8 Post-Hoc Calibration (MLGG-E05)

`class_weight="balanced"` distorts predicted probabilities (ECE can reach 0.3-0.4). Must use Platt scaling or isotonic regression fit on **validation set**, then apply to test set. Post-calibration ECE should be < 0.06.

---

### Phase 7: Multi-Model SHAP Interpretability

> **Gate**: `shap_interpretability_gate` &nbsp;|&nbsp; **Layer**: 5

#### 7.1 Why Multi-Model Instead of Single-Model

Different model families have different inductive biases: RF prefers interaction features, XGBoost prefers non-linear segments, LR only sees linear effects. Single-model SHAP rankings reflect that model's "worldview", not the data's truth (Rashomon effect, Breiman 2001). Multi-model averaging is more robust.

#### 7.2 Computation Process

```
For each model family m in {RF, XGB, CatBoost, LGBM, LR, ...}:
    1. Extract clf from Pipeline, transform data with preceding steps
    2. Select Explainer:
       - TreeExplainer  (exact, O(TLD)):  RF / XGB / CatBoost / LGBM
       - LinearExplainer (exact, O(MxD)):  LR
       - KernelExplainer (approx, O(2^M)): SVM / KNN / MLP
    3. Background data: train subset (default 200 rows)
    4. Explanation data: test subset (default 500 rows)
    5. Compute SHAP values -> (n_explain x n_features) matrix
```

#### 7.3 Proportional Normalization Ensemble (PMC11513550)

```
For each model m:
    abs_importance_m = mean(|SHAP_m|, axis=samples)    -> (n_features,)
    proportion_m     = abs_importance_m / sum(...)      -> sum = 1

Cross-model ensemble:
    ensemble_proportion = mean(proportion_m, for all m) -> equal-weight average
```

L1 normalization eliminates cross-model scale differences (RF SHAP values in [0, 0.02], XGBoost in [0, 0.15]), ensuring each model family has equal voting power.

#### 7.4 Cross-Model Consistency Tests

| Test | Meaning | FAIL | WARN |
|:-----|:--------|:-----|:-----|
| Kendall tau (FDR-BH corrected) | Feature importance rank correlation between two models | tau < 0.3 | tau < 0.5 |
| Top-N Jaccard | Top-10 feature set overlap | &mdash; | Jaccard < 0.3 |
| Direction consistency | All models signed SHAP same direction? | &mdash; | `mixed` direction |
| Extreme concentration | Single feature > 50% total importance | &mdash; | WARNING |

> When model families >= 3, multiple Kendall tau p-values automatically apply Benjamini-Hochberg FDR correction to avoid multiple comparison false positives.

#### 7.5 PDP Marginal Effects (Partial Dependence, complementary to SHAP)

SHAP may be misleading for correlated features (coalition game theory assumption). PDP provides a complementary perspective &mdash; showing the marginal effect curve of individual features on predictions:

- Automatically compute PDP for SHAP Top-K features (default 5) (`sklearn.inspection.partial_dependence`)
- Computed separately across all model families to observe different models' responses to the same feature
- Zero-variance features automatically skipped with `PDP_FEATURE_CONSTANT` warning

#### 7.6 Five Publication-Grade CSV Tables

| Table | Filename | Purpose | Columns |
|:------|:---------|:--------|:--------|
| **A** | `shap_table_a_ensemble_importance.csv` | Paper main table | Rank, feature, ensemble proportion, direction, per-model proportions |
| **B** | `shap_table_b_per_model_detail.csv` | Reviewer supplementary table | Feature, per-model MeanAbsSHAP / proportion / signed SHAP / rank |
| **C** | `shap_table_c_rank_agreement.csv` | Methodological evidence | ModelA, ModelB, Kendall_tau, P-value (FDR corrected), Top10 overlap, Jaccard |
| **D** | `shap_table_d_case_explanations.csv` | Clinical narrative | Case index, risk category, true label, predicted score, Top-3 driving features |
| **E** | `pdp_table_e_marginal_effects.csv` | Marginal effects | Model family, feature, feature value, PD value |

Each CSV has a methodology annotation in the first row (`# Method: ...`), skippable with `pd.read_csv(comment="#")`.

---

### Phase 8: Fairness & Equity

> **Gate**: `fairness_equity_gate` &nbsp;|&nbsp; **Rules**: Q01, Q02

#### 8.1 Subgroup Analysis (MLGG-Q01, TRIPOD+AI Item 16b)

Stratify by protected attributes (race, gender, age), independently computing per group: AUROC, PR-AUC, Sensitivity, Specificity, PPV, FPR, prevalence.

#### 8.2 Fairness Thresholds (7 Metrics)

| Metric | WARNING | FAIL | Definition |
|:-------|:--------|:-----|:-----------|
| Equalized odds gap (sensitivity) | > 0.10 | > 0.15 | Maximum sensitivity gap across subgroups |
| Disparate impact ratio (80% rule) | < 0.85 | < 0.80 | Minority/majority positive prediction rate ratio |
| Subgroup PR-AUC minimum | < 0.50 | < 0.40 | Minimum performance of any subgroup |
| FPR parity gap (HEAL) | > 0.10 | > 0.15 | Maximum FPR gap across subgroups |
| FNR parity gap (HEAL) | > 0.10 | > 0.15 | Maximum FNR gap across subgroups |
| PPV parity gap (predictive value fairness) | > 0.10 | > 0.15 | Maximum PPV gap across subgroups |
| Calibration slope deviation (calibration fairness) | > 0.20 | > 0.30 | Maximum calibration slope deviation from 1.0 across subgroups |

> **Multiple comparison warning**: When N features x 7 metrics > 10 comparisons, automatically emits multiplicity warning and reports Bonferroni-adjusted alpha to avoid false positives.

#### 8.3 Small Subgroup Handling (MLGG-Q02)

| Subgroup Size | Handling |
|:-------------|:---------|
| n < 20 | Do not compute fairness metrics |
| n 20-50 | Compute but flag as "unstable" |
| n 50-200 | Compute, emit WARNING |
| n >= 200 | Fully reliable |

#### 8.4 Impossibility Theorem Disclaimer

When reporting >= 3 fairness metrics, automatically prompts the impossibility theorem (Chouldechova A. Big Data 2017;5(2):153-163; Kleinberg J et al. ITCS 2017): except when base rates are equal or prediction is perfect, it is impossible to simultaneously satisfy all fairness criteria.

---

### Phase 9: Reporting & Compliance

> **Gates**: `publication_gate` + `self_critique_gate` + `security_audit_gate` &nbsp;|&nbsp; **Rule**: T01

#### 9.1 TRIPOD+AI 2024 Checklist (Collins 2024, BMJ)

27 items checked item-by-item, machine-verifying each has corresponding evidence files. 17 items mandatory (including 6 AI-specific additions):

| New AI Item | Requirement |
|:------------|:------------|
| Item 12 | Fairness assessment reported |
| Item 13 | Interpretability analysis reported |
| Item 18 | Model uncertainty reported |
| Item 20 | Fairness results reported |
| Item 24 | AI-specific limitations discussed |
| Item 27 | Model/code availability declared |

#### 9.2 PROBAST+AI 2025 Risk of Bias (Moons 2025, BMJ)

4-domain assessment, 16 signaling questions:

| Domain | Assessment Content |
|:-------|:-------------------|
| D1 Participants | Data source, inclusion/exclusion criteria, representativeness |
| D2 Predictors | Feature definitions, temporal availability, blinding |
| D3 Outcome | Outcome definition, adjudication method, time window |
| D4 Analysis | Sample size, missing data handling, model selection, validation |

Each domain judged low / high / unclear. Overall ROB must be `low` to claim publication-grade.

#### 9.3 Three-Level Compliance (L1/L2/L3)

| Level | Name | Gates | Use Case | TRIPOD+AI | PROBAST ROB |
|:------|:-----|:------|:---------|:----------|:-----------|
| **L1** | Leakage Audit | 12 | Conference papers, preliminary reports | &mdash; | &mdash; |
| **L2** | Statistically Valid | 25 | Professional journals (JAMIA, npj DM) | >= 17/27 | low/unclear |
| **L3** | Publication-Grade | **All 33 gates** | Nature Medicine, Lancet, JAMA, BMJ | >= 23/27 | **low** |

> **External validation policy**: Without external validation data, `external_validation_gate` returns `status="skipped"`, total audit score hard-capped at 85 (impossible to reach >=90 top-journal level), L3 compliance auto-blocked, and Limitations must declare this. Supports three external validation types: `cross_period` (temporal validation) / `cross_institution` (geographic validation) / `independent_cohort` (independent cohort).

**L1 Gates (12)**: request_contract, manifest, execution_attestation, leakage, split_protocol, covariate_shift, definition_guard, feature_lineage, imbalance, missingness, tuning, reporting_bias

**L2 adds (13)**: model_selection_audit, feature_engineering_audit, clinical_metrics, prediction_replay, generalization_gap, seed_stability, calibration_dca, ci_matrix, metric_consistency, evaluation_quality, permutation, sample_size, robustness

**L3 adds (8)**: distribution_generalization, external_validation, fairness_equity, cohort_definition, shap_interpretability, publication, self_critique, security_audit

#### 9.4 Structured Limitations Discussion

Must cover: data source limitations, temporal validity, coding system changes (ICD-9 -> ICD-10), external validity, fairness limitations, DCA clinical utility conclusions. If DCA shows no net benefit, must honestly report &mdash; never hide negative results.

---

## 33 Safety Gates (Gate DAG)

33 gates arranged in a directed acyclic graph (DAG) across 9 layers. Same-layer gates run in parallel; all must pass to claim L3 Publication-Grade.

```
Layer 0  Contract validation      cohort_definition  |  request_contract
   |
Layer 1  Fingerprint lock         manifest_lock
   |
Layer 2  Execution attestation    execution_attestation
   |
Layer 3  Data validation (4 parallel)   leakage  |  split_protocol  |  covariate_shift  |  reporting_bias
   |
Layer 4  Policy audit (5 parallel)      definition_guard  |  feature_lineage  |  imbalance  |  missingness  |  tuning
   |
Layer 5  Model audit (4 parallel)       model_selection_audit  |  feature_engineering  |  clinical_metrics  |  shap
   |
Layer 6  Statistical validation (13 parallel)   calibration_dca  |  ci_matrix  |  distribution  |  eval_quality
                                                 external_validation  |  fairness  |  gap  |  metric_consistency
                                                 permutation  |  prediction_replay  |  robustness  |  sample_size  |  seed
   |
Layer 7  Publication aggregation  publication_gate
   |
Layer 8  Final review (2 parallel)    self_critique  |  security_audit
```

<details>
<summary><strong>Detailed Description of All 33 Gates (click to expand)</strong></summary>

| # | Layer | Gate | Checks | Output Report |
|:--|:------|:-----|:-------|:--------------|
| 1 | 0 | `cohort_definition_gate` | EPV adequacy, Riley triple criteria, data types, missing values, suspicious correlations | `cohort_definition_report.json` |
| 2 | 0 | `request_contract_gate` | Request JSON schema, file paths, publication strategy anti-downgrade protection | `request_contract_report.json` |
| 3 | 1 | `manifest_lock` | SHA-256 cryptographic fingerprinting of all data/config/evaluation/gate scripts | `manifest.json` |
| 4 | 2 | `execution_attestation_gate` | Detached signature verification + **out-of-band `trusted_signers.json` fingerprint allowlist (external trust anchor)** + `--max-age-hours` freshness (default 168h, anti-replay) + bundle path sandbox (rejects symlink escape) + witness arbitration. See `references/attestation/README.md` | `execution_attestation_report.json` |
| 5 | 3 | `leakage_gate` | Row hash overlap, patient ID overlap, temporal boundary violations, 7-category feature name regex | `leakage_report.json` |
| 6 | 3 | `split_protocol_gate` | Patient-level disjoint splits, temporal correctness, prevalence check, minimum split sizes | `split_protocol_report.json` |
| 7 | 3 | `covariate_shift_gate` | Per-feature Jensen-Shannon divergence, prevalence drift, missing rate drift | `covariate_shift_report.json` |
| 8 | 3 | `reporting_bias_gate` | TRIPOD+AI 2024 (17 items) + PROBAST+AI 2025 (6 domains) + STARD-AI checklist | `reporting_bias_report.json` |
| 9 | 4 | `definition_variable_guard` | Block outcome definition variables as predictors; **circular definition detection, time window documentation, post-prediction feature leakage check** | `definition_guard_report.json` |
| 10 | 4 | `feature_lineage_gate` | Block post-index-time derived features from training | `lineage_report.json` |
| 11 | 4 | `imbalance_policy_gate` | Class imbalance strategy, training-set-only resampling, prevalence validation | `imbalance_policy_report.json` |
| 12 | 4 | `missingness_policy_gate` | Missing data strategy, MICE scale protection, imputer isolation; **>5% enforced mechanism testing, >40% enforced MNAR sensitivity** | `missingness_policy_report.json` |
| 13 | 4 | `tuning_leakage_gate` | Hyperparameter tuning protocol, test set isolation, CV nesting | `tuning_leakage_report.json` |
| 14 | 5 | `model_selection_audit_gate` | One-SE rule replay, >= 3 candidate models, logistic regression baseline, fingerprint verification | `model_selection_audit_report.json` |
| 15 | 5 | `feature_engineering_audit_gate` | Feature group provenance, training-set-only scope, stability evidence | `feature_engineering_audit_report.json` |
| 16 | 5 | `clinical_metrics_gate` | 14-metric panel completeness, confusion matrix consistency, clinical floor validation | `clinical_metrics_report.json` |
| 17 | 5 | `shap_interpretability_gate` | Multi-model SHAP ensemble, Kendall tau consistency, 4 publication-grade CSVs | `shap_interpretability_report.json` |
| 18 | 6 | `calibration_dca_gate` | ECE, slope/intercept, O:E ratio, CITL, DCA net benefit, per-cohort validation | `calibration_dca_report.json` |
| 19 | 6 | `ci_matrix_gate` | Bootstrap CI matrix across all splits and external cohorts | `ci_matrix_gate_report.json` |
| 20 | 6 | `distribution_generalization_gate` | Cross-split distribution drift, feature-level JSD, transfer readiness | `distribution_generalization_report.json` |
| 21 | 6 | `evaluation_quality_gate` | CI width <= 0.20, resamples >= 200, baseline improvement >= 0.01 | `evaluation_quality_report.json` |
| 22 | 6 | `external_validation_gate` | External cohort metrics, transfer gap, >= 100 events per cohort; **missing = score cap 85, L3 blocked** | `external_validation_gate_report.json` |
| 23 | 6 | `fairness_equity_gate` | Equalized odds, disparate impact ratio, subgroup performance floor, HEAL FPR/FNR, **PPV fairness, calibration fairness, multiple comparison warning** | `fairness_equity_report.json` |
| 24 | 6 | `generalization_gap_gate` | Train-validation-test performance gaps (PR-AUC, F2-beta, Brier) | `generalization_gap_report.json` |
| 25 | 6 | `metric_consistency_gate` | Metric value consistency between request and evaluation reports | `metric_consistency_report.json` |
| 26 | 6 | `permutation_significance_gate` | Permutation null distribution significance test | `permutation_report.json` |
| 27 | 6 | `prediction_replay_gate` | Row-level prediction trace metric replay (tolerance 1e-6) | `prediction_replay_report.json` |
| 28 | 6 | `robustness_gate` | Temporal slice and patient subgroup performance stability | `robustness_gate_report.json` |
| 29 | 6 | `sample_size_gate` | EPV >= 10, shrinkage factor >= 0.90, external >= 100 events, CI precision | `sample_size_report.json` |
| 30 | 6 | `seed_stability_gate` | Multi-seed variance (PR-AUC std <= 0.03, strict >= 5 seeds) | `seed_stability_report.json` |
| 31 | 7 | `publication_gate` | Aggregate L1/L2/L3 compliance, fingerprint baseline comparison, quality score | `publication_gate_report.json` |
| 32 | 8 | `self_critique_gate` | 12-dimension quality score + actionable recommendations | `self_critique_report.json` |
| 33 | 8 | `security_audit_gate` | HMAC model signature, evidence integrity, dependency authenticity, sensitive data scan | `security_audit_report.json` |

</details>

---

## 12-Dimension Scoring

Each dimension scored independently, weighted sum yields total score (0-100):

| # | Dimension | Weight | Assessment Content |
|:--|:----------|:------:|:-------------------|
| 1 | Data Integrity | 12 | Split isolation, patient non-overlap, temporal correctness, no duplicate rows |
| 2 | Leakage Prevention | 15 | Target leakage, definition variables, post-index features, feature name patterns |
| 3 | Pipeline Isolation | 12 | Training-set-only preprocessing, imputer/scaler/resampling scope enforcement |
| 4 | Model Selection Rigor | 10 | Candidate pool diversity, one-SE rule, test set isolation, baseline comparison |
| 5 | Statistical Validity | 12 | Bootstrap CI, permutation test, calibration triple, DCA, metric consistency |
| 6 | Generalization Evidence | 10 | Train-test gap, external cohorts, transfer CI, seed stability |
| 7 | Clinical Completeness | 7 | Complete 14-metric panel (MCC, LR+/LR-), confusion matrix, threshold feasibility |
| 8 | Reporting Standards | 7 | TRIPOD+AI 2024, PROBAST+AI 2025, exclusion criteria, limitations |
| 9 | Reproducibility | 6 | Seed locking, version tracking, execution attestation, fingerprint locking |
| 10 | Security & Provenance | 3 | HMAC-SHA256 signatures, AES-256-GCM, audit chain, restricted deserialization |
| 11 | Fairness | 3 | Subgroup analysis, equalized odds, disparate impact ratio, HEAL FPR/FNR |
| 12 | Sample Size | 3 | EPV criteria, Riley triple criteria, shrinkage factor, effective sample size |

**Score Interpretation**:

| Score Range | Grade | Meaning |
|:------------|:------|:--------|
| >=90 | L3 | Top-journal level (Nature Medicine, Lancet, JAMA, BMJ) |
| 75-89 | L2 | Needs supplementation (professional journals) |
| 60-74 | L1 | Major deficiencies (conference papers only) |
| < 60 | &mdash; | Not publishable |

---

## 33 Methodology Rules

<details>
<summary><strong>Complete Rules Table (click to expand)</strong></summary>

| ID | Severity | Rule | Literature Source |
|:---|:---------|:-----|:-----------------|
| **C01** | CRITICAL | Define eligible cohort &mdash; exclude records where outcome is structurally impossible | TRIPOD+AI 2024 Item 4a |
| **S01** | CRITICAL | Split by patient ID &mdash; same patient never crosses splits | Steyerberg 2019 Ch.5 |
| **S02** | CRITICAL | Test set time must be later than training set | Futoma 2020 (Lancet DH) |
| **P01** | CRITICAL | Preprocessors fit only on training set | Kaufman 2012 (ACM TKDD) |
| **P02** | CRITICAL | SMOTE only on training set; use with caution: harms calibration | van den Goorbergh 2022 (JAMIA) |
| **P03** | CRITICAL | No global cleaning before splitting | |
| **P04** | CRITICAL | Imputation statistics only from training set | |
| **P05** | CRITICAL | Nominal -> OneHotEncoder; ordinal -> OrdinalEncoder (verify monotonicity) | Measured AUROC +0.02 |
| **P06** | WARNING | Stratify missing by mechanism, not fixed drop threshold | Madley-Dowd 2019 |
| **F01** | CRITICAL | Target variable must not be a feature | |
| **F02** | CRITICAL | Future information must not be a feature | |
| **F03** | CRITICAL | Feature selection only on training set | |
| **F04** | WARNING | Univariate screening deprecated &mdash; use Elastic Net or Ridge | Heinze 2018 |
| **F05** | CRITICAL | Define prediction time point; classify all features' temporal attribution | TRIPOD+AI Item 4b |
| **F06** | WARNING | Elastic Net group selection + stability selection + Ridge control | Zou 2005, Meinshausen 2010 |
| **M01** | CRITICAL | No hyperparameter tuning on test set | |
| **M02** | CRITICAL | Threshold selected on validation set | |
| **M03** | WARNING | Compare >= 3 model families | TRIPOD+AI Item 7b |
| **M04** | CRITICAL | Model selection uses validation performance, not train-test gap | Yang 2023 (KDD) |
| **E01** | CRITICAL | All primary metrics need 95% CI (bootstrap >= 1000) | Efron 1993 |
| **E02** | CRITICAL | Complete 14-metric panel: discrimination + classification (incl. MCC, LR+/LR-) + calibration + DCA | Van Calster 2019, Chicco 2020 |
| **E03** | WARNING | Calibration ECE < 0.06 | |
| **E04** | WARNING | Train-test gap for diagnostics only, not selection criteria | Steyerberg 2019 |
| **E05** | WARNING | class_weight="balanced" requires post-hoc calibration | Platt 2000 |
| **E06** | WARNING | Bootstrap optimism correction (>= 100 resamples) | Steyerberg 2019 Ch.17 |
| **Z01** | WARNING | Sample size: EPV >= 10 (simplified); strict uses Riley 2019 | Peduzzi 1996, Riley 2019 |
| **R01** | INFO | Set random_state for reproducibility | |
| **R02** | WARNING | Multi-seed stability (>= 5 seeds, std < 0.03) | Riley 2023 (Biom J) |
| **T01** | WARNING | TRIPOD+AI 2024 compliance | Collins 2024 (BMJ) |
| **Q01** | WARNING | Subgroup analysis (gender/age/race) | TRIPOD+AI Item 16b |
| **Q02** | WARNING | Subgroup metrics need Bootstrap CI; n < 200 marked unreliable | Steyerberg 2019 Ch.25 |

</details>

---

## 23 Model Families

| Model Family | Alias | Type | Description |
|:-------------|:------|:-----|:------------|
| `logistic_l1` | `lr_l1` | Logistic Regression | L1 penalty (sparse) |
| `logistic_l2` | `lr_l2` | Logistic Regression | L2 penalty (Ridge) |
| `logistic_elasticnet` | `lr_en` | Logistic Regression | L1+L2 hybrid |
| `random_forest_balanced` | `rf` | Random Forest | Balanced class weights |
| `extra_trees_balanced` | `extra_trees` | Extra Trees | Balanced class weights |
| `hist_gradient_boosting_l2` | `hgb` | Gradient Boosting | sklearn histogram gradient boosting |
| `adaboost` | &mdash; | AdaBoost | Binary classification |
| `xgboost` | `xgb` | XGBoost | Requires xgboost package |
| `catboost` | &mdash; | CatBoost | Requires catboost package |
| `lightgbm` | `lgbm` | LightGBM | Requires lightgbm package |
| `svm_linear` | `svm_lin` | SVM | Linear kernel |
| `svm_rbf` | `svm` | SVM | RBF kernel |
| `knn` | &mdash; | K-Nearest Neighbors | Distance-based |
| `gaussian_nb` | &mdash; | Naive Bayes | Gaussian assumption |
| `mlp` | &mdash; | MLP | Neural network |
| `tabpfn` | &mdash; | TabPFN | Foundation model |
| `decision_tree` | `dt` | Decision Tree | Single tree baseline |
| `soft_voting` | `voting` | Soft Voting Ensemble | Top-K ensemble |
| `weighted_voting` | &mdash; | Weighted Voting | Performance-weighted |
| `stacking` | `stack` | Stacking | Meta-learner ensemble |

Complexity ranking: Gaussian NB (1) < LR (2-4) < DT (5) < KNN (6) < SVM (7-8) < RF/Trees (9-10) < Boosting (11-14) < MLP (15) < TabPFN (17) < Ensemble (15000+).

---

## 16 Medical Datasets

<details>
<summary><strong>Large Datasets (>10K rows)</strong></summary>

```bash
python3 examples/download_real_data.py diabetes130_full   # UCI 101K readmission
python3 examples/download_real_data.py sepsis_survival    # UCI 129K sepsis survival
python3 examples/download_real_data.py rhc                # Vanderbilt 5.7K ICU mortality
python3 examples/download_cdc_data.py brfss               # CDC BRFSS 100K diabetes
python3 examples/download_cdc_data.py nhis                # CDC NHIS 28K diabetes
python3 examples/download_cdc_data.py covid               # CDC COVID-19 100K hospitalization
python3 examples/download_nhanes.py --cycles both         # CDC NHANES 16K diabetes
python3 examples/download_nci_gdc.py                      # NCI/NIH 25K cancer survival
```

</details>

<details>
<summary><strong>Small UCI Datasets</strong></summary>

```bash
python3 examples/download_real_data.py heart    # 297 rows
python3 examples/download_real_data.py breast   # 569 rows
python3 examples/download_real_data.py pima     # 768 rows
```

</details>

<details>
<summary><strong>Pre-bundled Datasets</strong></summary>

- `chronic_kidney_disease.csv` &mdash; UCI CKD (400 rows)
- `support2.csv` &mdash; Vanderbilt SUPPORT2 ICU prognosis (9K rows)
- `diabetes_130_readmission.csv` &mdash; UCI diabetes readmission (compact)
- `covid19_hospitalization.csv` &mdash; COVID-19 hospitalization prediction

</details>

All data from official institutions (CDC / UCI / NCI-NIH / Vanderbilt), no registration required, one-click download. Total 630K+ rows.

---

## 28 Static Analysis Rules (R001-R028)

| Category | Rules | Severity |
|:---------|:------|:---------|
| **Data Leakage** | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split, R023 target-encoding-leak, R024 frequency-encoding-leak, R026 fillna-before-split, R027 manual-scaling-before-split | ERROR |
| **Splitting Issues** | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
| **Cross-Validation** | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced, R025 smote-after-model-in-pipeline | ERROR/WARNING |
| **Evaluation Misuse** | R010 train-metric-as-final, R013 hardcoded-threshold, R021 test-loop-tuning, R022 single-metric-report | WARNING |
| **Preprocessing** | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING/INFO |
| **Reproducibility** | R016 no-random-state | INFO |
| **Statistical Rigor** | R009 no-CI, R019 multiple-comparison | INFO |
| **Modality Guard** | R028 omics-feature-prefix (rejects `gene_/probe_/snp_/cpg_/rs#/ENSG` feature names; directs users to Scanpy/TCGAbiolinks/PLINK) | ERROR |

```bash
# Run static analysis on any Python project
python3 -m mlgg_lint /path/to/code/
```

---

## 21 Analysis Tools

| Tool | Function | Common Reviewer Question | Literature |
|:-----|:---------|:------------------------|:-----------|
| Riley Sample Size | `riley_sample_size()` | "Sample size justification?" | Riley 2019 |
| Calibration Triple | `calibration_metrics()` | "Calibration slope/intercept?" | Van Calster 2019 |
| Calibration Bin CI | `calibration_bin_ci()` | "Calibration curve has CI?" | NC Reviewer #2 |
| NRI / IDI | `compute_nri_idi()` | "How much better than baseline?" | Pencina 2008 |
| Learning Curve | `learning_curve_data()` | "Is data sufficient?" | Figueroa 2012 |
| VIF Collinearity | `compute_vif()` | "Feature collinearity?" | PMC4888898 |
| Nonlinearity Test | `check_nonlinearity()` | "Is linearity assumption reasonable?" | Harrell 2015 |
| Coefficient Export | `export_model_coefficients()` | "What are the model coefficients?" | NC Reviewer #1 |
| MNAR Sensitivity | `mnar_sensitivity_analysis()` | "What if MAR assumption is wrong?" | PMC10481859 |
| Temporal Drift | `temporal_drift_analysis()` | "Is model still accurate post-deployment?" | PMC8627243 |
| Model Card | `generate_model_card()` | "Structured model documentation?" | Mitchell M et al. FAT* 2019 |
| Imputation Sensitivity | `imputation_sensitivity()` | "Do conclusions change with different imputation?" | Madley-Dowd et al. J Clin Epidemiol 2019 |
| Subgroup DCA | `subgroup_dca()` | "Clinical utility for minorities?" | Vickers 2006 + PROBAST+AI 2025 |
| Baseline Comparison | `baseline_comparisons()` | "How much better than random/prevalence?" | NC ML Checklist |
| Feature Ablation | `feature_ablation()` | "Performance change without key features?" | NC ML Checklist |
| Compute Resources | `compute_resource_report()` | "Training resource usage?" | NC ML Checklist |
| Rubin's Rules | `rubins_rules_combine()` | "How to combine multiple imputations?" | Rubin 1987 |
| Robustness Stress Test | `robustness_stress_test()` | "Stable against outliers/noise?" | Original |
| Bootstrap Optimism | `bootstrap_optimism_correction()` | "Internal validation optimism bias?" | Steyerberg 2019 |
| PDP Marginal Effects | `_compute_pdp_ice()` | "Marginal feature impact on prediction?" | Friedman 2001 |
| FDR-BH Correction | `fdr_bh_correction()` | "Multiple comparisons corrected?" | Benjamini-Hochberg 1995 |

100% coverage of [Nature Portfolio ML Checklist V1.1](https://www.nature.com/documents/machine-learning-checklist.pdf) (30 items).

---

## Security Hardening Layer

| Component | Implementation | Status |
|:----------|:---------------|:-------|
| Model Signature | HMAC-SHA256 timing-safe `hmac.compare_digest()` | fail-closed |
| Evidence Encryption | AES-256-GCM (no downgrade &mdash; requires cryptography package) | fail-closed |
| Audit Chain | Append-only JSONL + chained HMAC hashes, fsync per entry | Tamper-proof |
| Deserialization | RestrictedUnpickler module whitelist + callable blacklist | Sandboxed |
| Path Traversal | safe_path() symlink resolution + prefix prohibition + sandbox enforcement | Defended |
| Execution Attestation | OpenSSL detached signatures **+ `trusted_signers.json` fingerprint allowlist (external trust anchor) + freshness window (default 7 days) + bundle path sandbox** + witness arbitration (min 2) + key rotation (180 days) | Fail-closed against self-authentication, replay, and path escape |
| Sensitive Data | 18-pattern scan (API keys, PEM blocks, PHI fields, SSN, credit cards) | Auto-detect |
| Key Protection | .mlgg_model_key chmod 0o600, .gitignore protection, upward search + downgrade warning | Hardened |

---

## Project Structure

```
medical-ml-governance-guard/
│
├── scripts/                              # ─── Core Code (106 files, ~83K lines) ───
│   │                                     # File / LOC snapshot 2026-04-24; counts drift per commit.
│   ├── core/              (7)            # Framework foundation
│   │   ├── _gate_framework.py            #   GateIssue/Severity, report envelope v2.0, CLI contract
│   │   ├── _gate_registry.py             #   33-gate DAG (8-layer topological sort, parallel markers)
│   │   ├── _gate_utils.py                #   60+ stat/IO/security functions (calibration, VIF, NRI...)
│   │   ├── _audit_shared.py              #   12-dimension scoring + 12 code anti-pattern regex scan
│   │   ├── _security.py                  #   HMAC signing, AES-256-GCM, RBAC, RestrictedUnpickler
│   │   └── gate_rag_bridge.py            #   gate → RAG bridge: rag_context_for_failure() + format_for_gate_report()
│   │   # Note: peer-review KB retrieval (_peer_review_retrieval.py, 793 LOC) moved to
│   │   # scripts/rag/retrieval/bm25.py — the BM25 half of the RAG hybrid ranker.
│   │   # gate_rag_bridge.py is the consumer (gate → RAG); dep direction stays one-way:
│   │   # gates know about RAG, RAG doesn't know about gates.
│   │
│   ├── gates/             (34)           # 33 fail-closed gates (standalone CLI, exit 0/2)
│   │   ├── cohort_definition_gate.py     #   Layer 0: Cohort definition + codebook RAG validation
│   │   ├── request_contract_gate.py      #   Layer 0: Request contract validation
│   │   ├── manifest_lock.py              #   Layer 1: Evidence file integrity locking
│   │   ├── execution_attestation_gate.py #   Layer 2: Execution proof signing
│   │   ├── leakage_gate.py               #   Layer 3: Data leakage detection
│   │   ├── split_protocol_gate.py        #   Layer 3: Split protocol validation
│   │   ├── definition_variable_guard.py  #   Layer 4: Definition variable leakage guard
│   │   ├── feature_lineage_gate.py       #   Layer 4: Feature lineage tracking
│   │   ├── model_selection_audit_gate.py #   Layer 5: Model selection audit
│   │   ├── calibration_dca_gate.py       #   Layer 6: Calibration + Decision Curve Analysis
│   │   ├── fairness_equity_gate.py       #   Layer 6: Fairness + subgroup analysis
│   │   ├── publication_gate.py           #   Layer 7: TRIPOD+AI / PROBAST+AI compliance
│   │   ├── self_critique_gate.py         #   Layer 8: AI self-critique
│   │   ├── security_audit_gate.py        #   Layer 8: Security audit
│   │   └── ... (19 more gates)           #   Covers covariate shift, robustness, seed stability, etc.
│   │
│   ├── orchestration/     (11)           # Workflow orchestration
│   │   ├── mlgg.py                       #   Unified CLI entry (28+ subcommands, state machine)
│   │   ├── mlgg_onboarding.py            #   Project init + auto-detect data source/disease/codebook
│   │   ├── mlgg_interactive.py           #   Interactive wizard (play mode)
│   │   ├── mlgg_pixel.py                 #   Pixel-art terminal UI + i18n
│   │   ├── run_dag_pipeline.py           #   Parallel DAG executor (checkpoint resume, layer-parallel)
│   │   ├── run_productized_workflow.py   #   Production pipeline (doctor → preflight → strict → summary)
│   │   ├── run_endurance_test.py         #   Endurance benchmark runner
│   │   └── triage.py / semantic_audit.py / failure_diagnosis.py
│   │
│   ├── training/          (8)            # Model training & data preparation
│   │   ├── train_select_evaluate.py      #   Training engine (5+ model families, one-SE selection)
│   │   ├── split_data.py                 #   Patient-level safe splitting (grouped_temporal / stratified)
│   │   ├── init_project.py               #   Project scaffolding (configs/ + data/ + evidence/)
│   │   └── schema_preflight.py           #   CSV column/type/semantic validation
│   │
│   ├── reporting/         (16)           # Reports, audits & exports
│   │   ├── audit_metrics.py              #   Zero-dep publication-readiness checker
│   │   ├── audit_external_project.py     #   10-dimension project audit (100-point scale)
│   │   ├── generate_audit_report.py      #   TRIPOD+AI/PROBAST+AI audit report
│   │   ├── export_latex.py               #   Publication-ready LaTeX tables
│   │   ├── record_session.py             #   Interactive session recorder (audit replay)
│   │   └── ...                           #   render_user_summary, compliance_certificate, etc.
│   │
│   ├── codebooks/         (13)           # Data dictionary tools (7.0K LOC)
│   │   ├── nhanes_codebook_lookup.py     #   NHANES 60K variable FTS5 full-text search
│   │   ├── ukb_codebook_lookup.py        #   UKB 12K field + disease-KB join + --exclude-risk
│   │   ├── build_ukb_codebook_db.py      #   UKB Showcase → SQLite (11,821 fields + 533K encoding values)
│   │   ├── verify_ukb_codebook.py        #   UKB 8-layer verify: L1 sha / L2 49 HARD invariants / L2c cell-by-cell / L3 golden seeds / L3b disease-KB / content-facet hash / (L4 live)
│   │   ├── verify_ukb_against_live.py    #   L4 live cross-check vs biobank.ndph.ox.ac.uk
│   │   └── ...                           #   fetch/build/verify for NHANES + codebook_factory
│   │
│   ├── review/            (9)            # Paper analysis & peer review
│   │   ├── peer_review_lookup.py         #   154 NC+CM papers × 817 review opinions
│   │   ├── backfill_peer_review_gates.py #   Backfill reviews into gate × tag index
│   │   ├── add_robustness_permutation_gates.py  # Extend review index with robustness/permutation
│   │   ├── correct_subgroup_overmatch.py #   Fix subgroup over-match in review index
│   │   └── ...                           #   batch_journal_review, extract/score metadata
│   │
│   ├── rag/               (4)            # Dense-vector RAG over the peer-review KB (__init__ + 3 modules + index/ + retrieval/ + evals/ subpkgs)
│   │   ├── config.py                     #   Constants / paths / weights (BGE-small, .cache/rag/, dense/BM25/tag)
│   │   ├── embeddings.py                 #   sentence-transformers wrapper (singleton model loader + normalize)
│   │   ├── query.py                      #   [entry point] High-level API + CLI (--gate / --codes / --top-k / --format)
│   │   ├── index/                        #   Index subpackage: builder.py (KB → npz) + cache.py (atomic writes / sha256)
│   │   ├── retrieval/                    #   Retrieval signal subpackage: dense.py (cosine) + bm25.py (keyword re-rank) + hybrid.py (fusion)
│   │   └── evals/                        #   Evals subpackage: harness.py (peer-review retrieval precision benchmark)
│   │   # Note: gate → RAG bridge (gate_rag_bridge.py, 204 LOC) lives in scripts/core/ as RAG's consumer,
│   │   # not inside scripts/rag/ — keeps the dep direction one-way (gates → RAG).
│   │
│   └── diagnostics/       (27)           # Environment, docs-consistency & KB hygiene
│       ├── env_doctor.py                 #   Dependency health check
│       ├── mlgg_web.py                   #   Flask Web UI
│       ├── check_docs_consistency.py     #   SKILL.md ↔ README ↔ reviewer.yaml drift detector (pre-commit)
│       ├── check_readme_stats.py         #   README CN/EN stat parity + live-KB freshness
│       ├── disease_kb_review_check.py    #   Disease-KB clinical review checklist generator
│       ├── kb_hygiene_check.py           #   KB provenance / citation / freshness check
│       └── ...                           #   gate visualization, threshold analysis, policy generator
│
├── tests/                  (134)         # ─── Tests (~35K lines) ───
│   ├── conftest.py                       #   Shared fixtures (tmp_path, path injection, test data)
│   ├── test_*_gate.py      (32)          #   One test file per gate
│   ├── test_*_e2e.py       (8)           #   End-to-end flow tests (onboarding, workflow, train, split, rag)
│   ├── test_stress_*.py    (5)           #   Stress tests (audit chain, pipeline, numeric, security)
│   ├── test_security*.py   (4)           #   Security + red team tests
│   └── SKILL_RED_TEAM.md                 #   Red team attack scenario documentation
│
├── references/                           # ─── Knowledge Bases (8 domain subdirectories) ───
│   ├── standards/          (6)           # Reporting standards
│   │   ├── tripod-ai-official-checklist.json     # TRIPOD+AI 2024 (27 machine-verifiable items)
│   │   ├── probast-ai-signalling-questions.json  # PROBAST+AI 2025 (4-domain bias assessment)
│   │   ├── stard-ai-checklist.json               # STARD+AI diagnostic accuracy
│   │   └── journal-rigor-standards.json          # 5 top-tier journal review standards
│   │
│   ├── methodology/        (6)           # Methodology knowledge
│   │   ├── disease-definition-knowledge-base.json  # 11 diseases (ICD, labs, meds, UKB fields)
│   │   ├── leakage-taxonomy.md                     # Kapoor 8-type leakage classification
│   │   └── literature-knowledge-base.json          # 58 IF>10 literature citations
│   │
│   ├── codebooks/                        # Data dictionaries
│   │   ├── nhanes/         (8+SQLite)    #   Harvard 58K vars + 202K codebook entries + BM25 index
│   │   ├── ukb/            (12+SQLite)   #   UKB Showcase 11,821 fields + 533,286 encoding values + 216 golden seeds + 106 aliases + 8-layer verification (source_manifest.json + ukb_golden_fields.yaml + KNOWN_GAPS.md)
│   │   └── dataset-codebook-registry.json  # Generic registry (BRFSS/NHIS/MIMIC)
│   │
│   ├── case-studies/                     # Peer review KB ("others review others" → structured KB)
│   │   ├── peer-review-kb.json           #   817 structured review opinions (indexed by gate/dim/tag)
│   │   ├── nature_communications/        #   286 NC peer-review PDFs (101 with extracted concerns)
│   │   └── <journal>/<disease>/          #   5 journals × 10 disease domains
│   │
│   ├── templates/          (27)          # JSON templates (request, split, evaluation, attestation...)
│   ├── operations/         (13)          # Runtime KBs (107 error diagnoses, scoring, gate matrix)
│   ├── protocols/          (16)          # Phase 1-9 rules + audit/blind-audit/sampling protocols
│   ├── attestation/        (3)           # HMAC signing onboarding + trusted-signers template
│   ├── retrieval_eval/     (2)           # Peer-review retrieval benchmarks (baseline + scenarios)
│   └── docs/               (8)           # Architecture, API-Reference, Quickstart, Troubleshooting
│
├── plugin/                               # ─── Static Analysis Lint (independent sub-package) ───
│   ├── mlgg_lint/          (9+30 files)  # AST-level 28 leakage detection rules (R001-R028)
│   │   └── rules/                        #   fit_before_split, smote_on_test, target_encoding_leak...
│   ├── tests/              (5+60 samples)# good/bad samples + CLI/engine tests
│   ├── vscode/             (4)           # VS Code extension
│   └── pyproject.toml                    # Independent package config (pip install -e plugin/)
│
├── agents/                 (3)           # ─── Multi-Agent Configs ───
│   ├── extractor.yaml                    #   Paper → metadata.json (Sonnet/Gemini/GPT-4o)
│   ├── reviewer.yaml                     #   metadata → 12-dim review (Sonnet/Gemini/GPT-4o)
│   └── README.md                         #   Agent role separation docs
│
├── examples/               (22)          # ─── Example Data + Project Templates ───
│   ├── *.csv               (16)          #   16 medical datasets (630K+ rows, UCI/CDC/NHANES/NCI)
│   ├── download_*.py       (4)           #   Data downloaders (real_data, cdc, nhanes, nci_gdc)
│   ├── demo_diabetes130/                 #   Complete 9-phase reference implementation
│   └── template/                         #   Reusable project scaffold (cp -r, then add your data)
│
├── papers/                               # ─── Paper Audit Library ("we review others") ───
│   ├── README.md                         #   Metadata review methodology + 12-dim scoring standard
│   ├── templates/                        #   paper_metadata_template.json
│   └── <journal>/<disease>/<author>/     #   PDF + metadata.json + audit_output/
│
├── experiments/                          # ─── E2E Benchmark Suite ───
│   └── authority-e2e/                    #   4 UCI dataset adversarial validation + benchmark matrix
│
├── .claude/                              # ─── Claude Code Configuration ───
│   ├── commands/mlgg.md                  #   /mlgg skill definition (9-phase state machine)
│   └── QUEUE_PROMPTS.md                  #   Prompt template library (66KB, gate review/dev tasks)
│
├── .github/workflows/      (5)          # ─── CI/CD ───
│   ├── ci-unit.yml                       #   Fast unit tests (2-5 min)
│   ├── ci-extended.yml                   #   Extended tests (30-45 min)
│   ├── ci-full.yml                       #   Full tests + benchmarks (60+ min)
│   ├── ci-overnight.yml                  #   Authority benchmarks + stress tests (overnight)
│   └── ci-security.yml                   #   Security audit + red team + RBAC
│
└── ROOT FILES
    ├── CLAUDE.md                         #   Agent operating protocol (reviewer role + safety bounds)
    ├── SKILL.md                          #   /mlgg skill definition (9-phase methodology guide)
    ├── pyproject.toml                    #   Package metadata + dependency declarations
    ├── README.md / README_EN.md          #   Project documentation (Chinese / English)
    ├── CONTRIBUTING.md                   #   Development standards
    ├── CHANGELOG.md                      #   Version history
    └── LICENSE                           #   PolyForm Noncommercial 1.0.0
```

### Data Flow

```
User CSV ──→ /mlgg (orchestration)
              │
              ├─ Phase 1: cohort_definition_gate ←── codebooks/ (variable semantic validation)
              ├─ Phase 2: split_data.py + split_protocol_gate
              ├─ Phase 3-4: leakage/feature gates ←── methodology/ (leakage taxonomy)
              ├─ Phase 5: train_select_evaluate.py + model gates
              ├─ Phase 6: calibration/evaluation gates ←── standards/ (TRIPOD+AI)
              ├─ Phase 7-8: SHAP/fairness gates
              └─ Phase 9: publication_gate + self_critique_gate
                            │
                            ├─ evidence/ (JSON reports + HMAC audit chain)
                            └─ case-studies/peer-review-kb.json (citing review opinions)
```

### Four Audit Paths

| Path | Executor | Input | Output |
|------|----------|-------|--------|
| **A. Paper metadata review** | API agents (`agents/extractor.yaml` → `reviewer.yaml`) | Paper PDF (paper text treated as untrusted data, prompt-injection defended) | 12-dim score + Major/Minor/Questions |
| **B. 33-gate full pipeline** | Claude Code (`/mlgg`) | User data + code (optional `--cohort-spec` for inclusion/exclusion cascade) | evidence/ reports + Table 1 (TRIPOD+AI 13a) + compliance cert |
| **C. Static Lint scan** | Claude Code (`mlgg lint`) | Python source (.py/.ipynb) | R001-R028 leakage detection report |
| **D. Quick metrics audit** | `mlgg audit-metrics --metrics '{}'` | Paper Table 2 numbers (no data files needed) | TRIPOD+AI compliance gap report |

Packaging: two pip packages (`mlgg-lint` standalone, `ml-governance-guard` bundles the 28-subcommand CLI). `audit-metrics` is a subcommand under `mlgg`, not a separate package. Full subcommand inventory: see `SKILL.md` §"Quick Dispatch".

---

## Installation Guide

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-governance-guard.git
cd medical-ml-governance-guard
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# Optional: model backends + class-imbalance helpers + visualization
python3 -m pip install -r requirements-optional.txt

# Verify
python3 scripts/orchestration/mlgg.py doctor
```

**Requirements**: Python 3.10+, numpy, pandas, scikit-learn, scipy, joblib.

**Optional**: xgboost, catboost, lightgbm, tabpfn, optuna, shap, flask, cryptography, imbalanced-learn.

### Developers: local pre-commit hooks (recommended)

Same rule set as CI, ~3 second local feedback before push:

```bash
python3 -m pip install --user pre-commit
pre-commit install
```

Configured in `.pre-commit-config.yaml`:
- `ruff` — identical to `ci-unit.yml` (E/F/W, excluding ML-code-common E501/E741/etc)
- `mlgg-lint-selfcheck` — lints `mlgg-lint`'s own source with the 28 AST rules (dog-fooding)
- `docs-consistency` — when SKILL.md / README(_EN).md / agents/reviewer.yaml change, verifies the 12-dimension scoring weights stay in sync

A separate git-native **pre-push** hook (README stats drift + ruff + RAG smoke) is one command to enable: `make install-hooks`. See [CONTRIBUTING.md](./CONTRIBUTING.md#pre-push-hook-recommended) for details.

---

## Command Reference

| Goal | Command |
|:-----|:--------|
| Audit external project | `python3 scripts/reporting/generate_audit_report.py --project-dir /path` |
| Interactive exploration | `python3 scripts/orchestration/mlgg.py play` |
| Guided first run | `python3 scripts/orchestration/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes` |
| Publication-grade verdict | `python3 scripts/orchestration/mlgg.py workflow --request <project>/configs/request.json --strict` |
| Environment check | `python3 scripts/orchestration/mlgg.py doctor` |
| Initialize project | `python3 scripts/orchestration/mlgg.py init --project-root /tmp/project` |
| Safe data splitting | `python3 scripts/orchestration/mlgg.py split -- --input data.csv --patient-id-col id --target-col y` |
| Train model | `python3 scripts/orchestration/mlgg.py train --interactive` |
| Static Lint | `python3 -m mlgg_lint /path/to/code/` |
| Download datasets | `python3 examples/download_real_data.py heart` |
| DAG visualization | `python3 scripts/orchestration/run_dag_pipeline.py --show-dag` |
| Export review prompt | `python3 scripts/reporting/export_review_prompt.py` |
| Batch journal review | `python3 scripts/orchestration/mlgg.py batch-review --manifest manifest.json` |

---

## Literature Foundation

<details>
<summary><strong>Complete Literature Table by Phase (click to expand)</strong></summary>

### Phase 1: Sample Size & Cohort

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Riley triple criteria | Riley RD et al. *Stat Med.* 2019;38(7):1276-1296 | `riley_sample_size()` |
| Sample size tutorial | Riley RD et al. *BMJ.* 2020;368:m441 | Bound criteria report |
| EPV >= 10 (legacy) | Peduzzi P et al. *J Clin Epidemiol.* 1996;49(12):1373-1379 | Fallback check |

### Phase 2: Data Splitting

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Patient-level split | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.5 | MLGG-S01 |
| Temporal split | Futoma J et al. *Lancet Digit Health.* 2020;2(9):e489 | MLGG-S02 |

### Phase 3: Preprocessing

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Fit on train only | Kaufman S et al. *ACM TKDD.* 2012;6(4):1-21 | MLGG-P01/P03/P04 |
| Tiered missingness | Madley-Dowd P et al. *J Clin Epidemiol.* 2019;110:63-73 | MLGG-P06 |
| SMOTE harms calibration | van den Goorbergh RWM et al. *JAMIA.* 2022;29(9):1525-1534 | MLGG-P02 |

### Phase 4: Feature Selection

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Elastic Net | Zou H, Hastie T. *JRSS-B.* 2005;67(2):301-320 | alpha/C joint CV |
| Stability selection | Meinshausen N, Buhlmann P. *JRSS-B.* 2010;72(4):417-473 | 100 subsamples, threshold 0.6 |
| Group LASSO | Yuan M, Lin Y. *JRSS-B.* 2006;68(1):49-67 | OneHot grouping |
| No univariate screening | Heinze G et al. *Biometrical J.* 2018;60(3):431-449 | MLGG-F04 |

### Phase 5: Model Training

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Valid performance > gap | Yang Z et al. *KDD 2023* | MLGG-M04 |
| Optimism correction | Steyerberg EW. *Clinical Prediction Models.* 2019 Ch.17 | `bootstrap_optimism_correction()` |

### Phase 6: Evaluation

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| Calibration triple | Van Calster B et al. *BMC Med.* 2019;17:230 | `calibration_metrics()` |
| MCC over F1 | Chicco D, Jurman G. *BMC Genomics.* 2020;21:6 | MLGG-E02 |
| LR+/LR- for clinical decisions | Deeks JJ, Altman DG. *BMJ.* 2004;329:168-169 | MLGG-E02 |
| DCA | Vickers AJ, Elkin EB. *Med Decis Making.* 2006;26(6):565-574 | `calibration_dca_gate` |
| NRI / IDI | Pencina MJ et al. *Stat Med.* 2008;27(2):157-172 | `compute_nri_idi()` |
| 5-domain evaluation | Van Calster B et al. *BMC Med.* 2019;17:230 + Steyerberg EW. *Clinical Prediction Models.* 2019 | Framework coverage |

### Phase 7: Interpretability

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| SHAP theory | Lundberg SM, Lee SI. *NeurIPS 2017* | `shap_interpretability_gate` |
| TreeSHAP | Lundberg SM et al. *Nature MI.* 2020;2:56-67 | TreeExplainer |
| Proportional normalization | Ponce-Bobadilla AV et al. *CTS.* 2024;17(11):e70056 | L1 normalization |
| Rashomon effect | Breiman L. *Stat Sci.* 2001;16(3):199-231 | Multi-model ensemble |

### Phase 9: Reporting & Compliance

| Methodological Decision | Literature Source | MLGG Implementation |
|:------------------------|:-----------------|:--------------------|
| TRIPOD+AI 2024 | Collins GS et al. *BMJ.* 2024;385:e078378 | 27-item checklist |
| PROBAST+AI 2025 | Moons KGM et al. *BMJ.* 2025;388:e082505 | 4-domain ROB |
| Leakage taxonomy | Kapoor S, Narayanan A. *Patterns.* 2023;4(9):100804 | All 33 gates covered |

### Foundational Reviews

| Literature | Core Argument |
|:-----------|:-------------|
| Chekroud AM et al. *Science.* 2024;383:164-167 | "Illusory generalizability" &mdash; ML models accurate within training trial, random outside |
| Wynants L et al. *BMJ.* 2020;369:m1328 | COVID prediction models: 94% high ROB by PROBAST; systematic evidence of widespread bias |
| Collins GS, Dhiman P, Ma J, et al. *BMJ.* 2024;384:e074819 | Calibration-in-the-large, calibration slope, bootstrap internal validation; split-sample NOT recommended |

</details>

---

## Claude Code Integration

MLGG provides a Claude Code slash command `/mlgg`. When activated, Claude switches to Nature Methods / JAMA-level reviewer mode, guiding users through the 9-phase workflow with real-time methodology checking.

```bash
# In Claude Code terminal:
/mlgg
```

The AI will automatically:
- Proactively guide through all 9 phases
- Cite 154 NC+CM peer-review papers (817 structured review opinions) as evidence
- Automatically detect common leakage patterns in code
- Generate structured audit reports and fix recommendations

---

## CI/CD

| Pipeline | Trigger | Scope | Timeout |
|:---------|:--------|:------|:--------|
| **ci-unit** | Push / PR | Unit tests, Python 3.10-3.12 | 20 min |
| **ci-security** | Push / PR | Security tests, gate validation, knowledge base integrity, TRIPOD/PROBAST checks | 30 min |
| **ci-full** | Nightly (3am) | Full onboarding demo, publication benchmarks | 360 min |
| **ci-extended** | Weekly (Sunday 4am) | Extended observational benchmarks | 480 min |

---

## License & Citation

**PolyForm Noncommercial License 1.0.0** &mdash; See [LICENSE](./LICENSE).

### Academic Citation (Required)

```bibtex
@software{mlgg2026,
  title   = {ML Governance Guard (MLGG): Publication-Grade Integrity Standard
             for Medical Prediction Models},
  author  = {Weng, Can},
  year    = {2026},
  version = {1.0},
  url     = {https://github.com/Furinaaa-Cancan/medical-ml-governance-guard},
  note    = {33 fail-closed audit gates, 9-phase workflow,
             TRIPOD+AI 2024 / PROBAST+AI 2025 compliant}
}
```

### Usage Permissions

| Use Case | Permitted | Conditions |
|:---------|:---------:|:-----------|
| Personal learning & research | Allowed | No authorization needed |
| **All other uses below** | **Authorization required** | **Contact author first** |
| Using MLGG methodology in academic papers | Authorization required | Obtain written permission + must cite |
| Teaching/classroom/training | Authorization required | Contact author |
| Derivative projects (open or closed source) | Authorization required | Contact author |
| Enterprise/institutional internal use | Authorization required | Contact author |
| Commercial use | **Prohibited** | Requires separate commercial license |
| Unauthorized methodology reproduction | **Prohibited** | Constitutes academic misconduct |

**Except for personal learning and research, any form of use requires prior written authorization from the author.** Unauthorized use (including but not limited to academic publication, teaching citations, derivative development, institutional deployment) violates this license. Uncited methodology reproduction constitutes academic misconduct and will be reported to relevant journal editors.

Contact: via [GitHub Issues](https://github.com/Furinaaa-Cancan/medical-ml-governance-guard/issues) or the author's homepage.
