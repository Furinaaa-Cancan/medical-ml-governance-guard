# ML Leakage Guard (MLGG)

**Publication-grade integrity standard for medical prediction models.**

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20NC%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0/)
[![Tests](https://img.shields.io/badge/tests-4000%2B%20passed-brightgreen)]()
[![Gate Coverage](https://img.shields.io/badge/gate%20coverage-%E2%89%A586%25-blue)]()
[![MLGG Standard v1.0](https://img.shields.io/badge/MLGG%20Standard-v1.0-orange)]()
[![TRIPOD+AI 2024](https://img.shields.io/badge/TRIPOD%2BAI-2024-blue)](https://doi.org/10.1136/bmj-2023-078378)
[![PROBAST+AI 2025](https://img.shields.io/badge/PROBAST%2BAI-2025-blue)](https://doi.org/10.7326/M18-1376)

31 fail-closed gates. 14 real medical datasets (526K rows). 12-dimension scoring. Machine-verifiable conformance certificates.

> Medical ML data leakage causes inflated performance metrics and unsafe clinical decisions. MLGG provides a machine-verifiable standard to prevent, detect, and report these issues — from raw data to TRIPOD+AI compliant publication.

---

## What MLGG Does

```
Raw Data → 31 Audit Gates → Conformance Certificate → Publication-Ready Report
```

| Capability | Detail |
|------------|--------|
| **31 fail-closed gates** | DAG architecture covering leakage detection, fairness, sample size, calibration, robustness, TRIPOD+AI, PROBAST+AI, security audit |
| **12-dimension scoring** (0-100) | Data Integrity / Leakage Prevention / Pipeline Isolation / Model Selection / Statistical Validity / Generalization / Clinical Completeness / Reporting / Reproducibility / Security / Fairness / Sample Size |
| **3 conformance levels** | L1 (12 gates, leakage-audited) / L2 (25 gates, statistically valid) / L3 (31 gates, publication-grade) |
| **20 model families** | LR (L1/L2/ElasticNet) / SVM / RF / XGBoost / CatBoost / LightGBM / KNN / MLP / TabPFN + ensemble methods |
| **14 real medical datasets** | UCI / CDC / NCI / Vanderbilt — 297 to 129K rows, one-command download |
| **Compliance engines** | TRIPOD+AI 2024 (27 items) / PROBAST+AI 2025 (4 domains, 34 questions) / STARD-AI |
| **20 lint rules** | Static analysis detecting code-level data leakage anti-patterns (R001-R020) |
| **Security layer** | HMAC-SHA256 / AES-256-GCM / chained audit log / path traversal protection |

---

## Quick Start

### Audit any ML project (no setup needed)

```bash
python3 scripts/generate_audit_report.py --project-dir /path/to/your/project
```

Output: `audit-report.md` + `audit-report.json` with TRIPOD+AI coverage, PROBAST+AI assessment, error root causes, literature citations, and prioritized fixes.

### Run the full guided demo (~5 min)

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard
python3 -m pip install -r requirements.txt
python3 scripts/mlgg.py onboarding --project-root /tmp/mlgg_demo --mode guided --yes
```

### Interactive pixel-art terminal UI

```bash
python3 scripts/mlgg.py play
```

---

## The MLGG 9-Phase Workflow

MLGG enforces a strict 9-phase workflow for building publication-grade clinical prediction models. Each phase has checkpoints that must pass before proceeding.

```
Phase 1  Data Understanding      Define cohort, prediction time point, EPV
    ↓
Phase 2  Data Splitting          Patient-level + temporal split (60/20/20)
    ↓
Phase 3  Preprocessing           Semantic encoding + tiered missingness strategy
    ↓
Phase 4  Feature Selection       Elastic Net CV + Stability Selection + Ridge baseline
    ↓
Phase 5  Model Training          ≥3 families + bootstrap optimism correction
    ↓
Phase 6  Evaluation              Full metric panel + calibration + DCA
    ↓
Phase 7  Interpretability        SHAP + cross-model consistency
    ↓
Phase 8  Fairness                Subgroup analysis with CI
    ↓
Phase 9  Reporting               TRIPOD+AI checklist + limitations
```

### 31 Rules (abbreviated)

| ID | Severity | Rule |
|----|----------|------|
| C01 | CRITICAL | Define eligible cohort — exclude structurally impossible outcomes |
| S01 | CRITICAL | Split by patient ID — no patient overlap |
| S02 | CRITICAL | Test set time after training set |
| P01 | CRITICAL | Fit preprocessors on training set ONLY |
| P05 | CRITICAL | Nominal → OneHotEncoder; Ordinal → OrdinalEncoder with verified order |
| P06 | WARNING | Missingness by mechanism, not proportion (Madley-Dowd 2019) |
| F02 | CRITICAL | No future information in features |
| F05 | CRITICAL | Define prediction time point; compare admission vs discharge models |
| F06 | WARNING | Elastic Net + Stability Selection; compare vs Ridge baseline |
| M04 | CRITICAL | Model selection by validation performance, NOT by train-test gap |
| E01 | CRITICAL | 95% CI for all primary metrics (bootstrap ≥1000) |
| E02 | CRITICAL | Full metric panel: AUROC, AUPRC, MCC, LR+/LR-, calibration slope/intercept/O:E |
| E05 | WARNING | class_weight="balanced" requires post-hoc calibration |
| E06 | WARNING | Bootstrap optimism correction (Steyerberg 2019) |
| Q01 | WARNING | Subgroup analysis by sex, age, race |

Full rule table: see `~/.claude/commands/mlgg.md` or invoke `/mlgg` in Claude Code.

---

## Reference Implementation: 30-Day Readmission Prediction

`examples/medical_ml_demo/` contains a complete 9-phase analysis using the UCI Diabetes 130-US Hospitals dataset (99,330 encounters, 69,979 patients).

```
examples/medical_ml_demo/
├── config.py                          Global configuration
├── 00_database/                       Raw data (gitignored)
├── 01_exploration/scripts/explore.py  EPV, missingness, cohort exclusion
├── 02_splitting/scripts/split.py      Patient-level temporal split
├── 03_preprocessing/scripts/          5-type semantic encoding + tiered missingness
├── 04_feature_selection/scripts/      Elastic Net CV + Stability Selection
├── 05_modeling/scripts/               4 model families + bootstrap optimism
├── 06_evaluation/scripts/             Full metrics + Platt calibration + DCA
├── 07_interpretability/scripts/       SHAP for all models
├── 08_fairness/scripts/               Race/gender/age subgroup analysis
├── 09_reporting/scripts/              TRIPOD+AI checklist + Table 1-3
└── outputs/tables/                    Publication-ready tables
```

### Key findings from the reference implementation

| Metric | Value |
|--------|-------|
| Best model | LightGBM |
| Test AUROC (95% CI) | 0.647 (0.631 - 0.661) |
| MCC | 0.122 (near-random) |
| LR+ / LR- | 1.60 / 0.69 (not clinically useful) |
| Calibration slope | 1.06 (well calibrated after Platt) |
| ECE (calibrated) | 0.009 |
| Admission-time AUROC | 0.606 |
| Discharge-time AUROC | 0.647 (+0.034 from discharge info) |
| Stability Selection stable features | 3/32 groups (number_inpatient, number_diagnoses, age) |

**Honest conclusion**: AUROC 0.647 masks MCC 0.12. Model is well-calibrated but lacks discrimination for standalone clinical decisions. Consistent with literature — 30-day readmission is inherently difficult (published AUROC 0.60-0.72).

### Issues discovered and rules created during development

| Issue | Impact | New Rule |
|-------|--------|----------|
| Deceased patients in cohort | AUROC inflated +0.004 | MLGG-C01 |
| OrdinalEncoder on nominal variables | LR AUROC -0.02 | MLGG-P05 |
| 60% missing threshold without evidence | No literature support | MLGG-P06 |
| Train-test gap as selection criterion | Wrong per Yang KDD 2023 | MLGG-M04 |
| class_weight distorts probabilities | ECE 0.35→0.01 after Platt | MLGG-E05 |
| 66% features are discharge-time only | Undeclared prediction time | MLGG-F05 |
| Drug columns assumed ordinal | No monotonic order verified | MLGG-P05 |
| Meinshausen error bound formula bug | E[V]=0 (false) → E[V]=0.66 | Fixed in code |

---

## Installation

```bash
git clone https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard.git
cd medical-ml-leakage-guard
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

# Optional model backends
python3 -m pip install -r requirements-optional.txt

# Verify
python3 scripts/mlgg.py doctor
```

**Requirements**: Python 3.10+, `numpy`, `pandas`, `scikit-learn`, `scipy`, `joblib`. Optional: `xgboost`, `catboost`, `lightgbm`, `tabpfn`, `optuna`.

---

## Command Reference

| Goal | Command |
|------|---------|
| Audit external project | `python3 scripts/generate_audit_report.py --project-dir /path` |
| Interactive exploration | `python3 scripts/mlgg.py play` |
| Guided first run | `python3 scripts/mlgg.py onboarding --project-root /tmp/demo --mode guided --yes` |
| Publication-grade verdict | `python3 scripts/mlgg.py workflow --request <project>/configs/request.json --strict` |
| Environment check | `python3 scripts/mlgg.py doctor` |
| Initialize project | `python3 scripts/mlgg.py init --project-root /tmp/project` |
| Static lint scan | `python3 -m mlgg_lint /path/to/code/` |
| Download dataset | `python3 examples/download_real_data.py heart` |

### Choosing the right command

| Scenario | Use |
|----------|-----|
| First time, want to explore | `play` |
| Building a model for publication | `onboarding --mode guided` then `workflow --strict` |
| Reviewing someone else's code | `generate_audit_report.py` or `mlgg_lint` |
| Teaching / classroom | `play --strict-small-sample` |

---

## Datasets (14 real medical datasets)

```bash
# Large (>10K rows)
python3 examples/download_real_data.py diabetes130_full   # UCI 101K readmission
python3 examples/download_real_data.py sepsis_survival    # UCI 129K sepsis
python3 examples/download_real_data.py rhc                # Vanderbilt 5.7K ICU mortality
python3 examples/download_cdc_data.py brfss               # CDC 100K diabetes
python3 examples/download_cdc_data.py nhis                # CDC 28K diabetes
python3 examples/download_cdc_data.py covid               # CDC 100K hospitalization
python3 examples/download_nhanes.py --cycles both         # CDC 16K diabetes
python3 examples/download_nci_gdc.py                      # NCI 25K cancer survival

# Small UCI
python3 examples/download_real_data.py heart    # 297 rows
python3 examples/download_real_data.py breast   # 569 rows
python3 examples/download_real_data.py pima     # 768 rows
```

All datasets from official sources (CDC / UCI / NCI-NIH / Vanderbilt). No registration required. Total: 526K rows.

---

## Lint Rules (R001-R020)

| Category | Rules | Severity |
|----------|-------|----------|
| Data Leakage | R001 fit-before-split, R002 scaler-on-test, R003 SMOTE-on-test, R005 threshold-on-test, R006 feature-selection-full, R007 target-as-feature, R017 early-stop-on-test, R020 global-clean-before-split | ERROR |
| Split Issues | R004 split-without-group, R008 temporal-shuffle, R015 small-test-set | WARNING |
| Cross-Validation | R011 CV-internal-SMOTE, R012 accuracy-on-imbalanced | ERROR/WARNING |
| Evaluation | R010 train-metric-as-final, R013 hardcoded-threshold | WARNING |
| Preprocessing | R014 LabelEncoder-on-features, R018 scaling-before-trees | WARNING/INFO |
| Reproducibility | R016 no-random-state | INFO |
| Statistics | R009 no-CI, R019 multiple-comparison | INFO |

---

## Project Structure

```
scripts/              Gate scripts, training, orchestrator
tests/                pytest tests (4000+)
examples/             Dataset downloaders + reference implementation
experiments/          E2E benchmark experiments
references/           JSON templates, knowledge bases, standards
docs/                 Architecture documentation
plugin/               Plugin Lint (R001-R020)
.github/workflows/    CI/CD pipelines
```

### Key reference files

| File | Purpose |
|------|---------|
| `references/mlgg-standard-specification.json` | Full 31-gate standard definition |
| `references/missingness-policy.example.json` | Tiered missingness strategy v2.0 (9 literature references) |
| `references/project-structure-convention.md` | Standardized 00-09 directory layout |
| `references/literature-knowledge-base.json` | 58 literature entries for automated citation |
| `references/error-knowledge-base.json` | 99 error entries for root-cause diagnosis |
| `references/tripod-ai-official-checklist.json` | TRIPOD+AI 2024 machine-readable checklist |

---

## Literature Foundation

MLGG rules are grounded in peer-reviewed methodology. Key references:

| Topic | Reference |
|-------|-----------|
| Missingness strategy | Madley-Dowd 2019 (J Clin Epidemiol), Sperrin 2020, Groenwold 2012 (CMAJ) |
| Model selection | Yang et al. KDD 2023 — validation performance over generalization gap |
| Internal validation | Steyerberg 2019, Harrell 2015 — bootstrap optimism correction |
| Feature selection | Zou & Hastie 2005 (Elastic Net), Meinshausen & Bühlmann 2010 (Stability Selection), Heinze 2018 |
| Sample size | Riley 2019/2020 — modern criteria replacing EPV ≥ 10 |
| Calibration | Van Calster 2019 (BMC Medicine) — slope, intercept, O/E ratio |
| Metric panel | Chicco & Jurman 2020 — MCC over F1 for imbalanced data |
| Reporting | Collins et al. 2024 — TRIPOD+AI statement (BMJ) |
| Oversampling harm | van den Goorbergh 2022 (JAMIA) — SMOTE harms calibration |

---

## Claude Code Integration

MLGG provides a Claude Code slash command (`/mlgg`) that activates a Nature Methods / JAMA-grade ML reviewer. The reviewer guides users through the 9-phase workflow with proactive leak prevention and literature-backed standards.

```
# In Claude Code terminal:
/mlgg
```

The skill definition is at `~/.claude/commands/mlgg.md` and contains all 31 rules with severity levels and literature references.

---

## CI/CD

| Pipeline | Trigger | Scope |
|----------|---------|-------|
| Smoke | Push / PR | Core gate smoke tests |
| Full | Nightly | All 4000+ tests |
| Extended | Weekly | E2E benchmarks on all datasets |
| Security | Multi-Python | Dependency audit + security tests |

---

## License

PolyForm Noncommercial License 1.0.0 — free for research and education, commercial use requires a separate license.

---

## Citation

```
Machine Learning Leakage Guard (MLGG) Standard v1.0.
ml-leakage-guard project, 2026.
https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard
```

When citing in a manuscript, include the MLGG version number and conformance level achieved (e.g., "MLGG v1.0 L3-Publication-Grade").
