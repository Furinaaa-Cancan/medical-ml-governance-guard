# Architecture

## Repository Layout

```
ml-leakage-guard/
│
├── scripts/                         # ─── Core Code ───
│   ├── core/            (6 files)   # Framework internals shared by all gates
│   ├── gates/          (33 files)   # 33 fail-closed quality gates (each standalone CLI)
│   ├── training/        (6 files)   # Model training, data splitting, project init
│   ├── reporting/      (15 files)   # Reports, audits, exports, session recording
│   ├── codebooks/      (10 files)   # NHANES + UK Biobank data dictionaries + provenance helper
│   ├── review/          (7 files)   # Paper analysis, peer review lookup, KB migrations
│   ├── diagnostics/    (10 files)   # Environment checks, visualization, web UI, docs consistency
│   └── orchestration/  (10 files)   # CLI entry point, pipeline orchestration
│
├── plugin/                          # ─── Product A: mlgg-lint ───
│   ├── mlgg_lint/       (27 rules)  # pip install mlgg-lint (zero deps, standalone)
│   └── pyproject.toml               # Independent package
│
├── tests/             (123 files)   # ─── 4760+ test functions ───
│
├── references/                      # ─── Knowledge Base ───
│   ├── standards/                   # TRIPOD+AI 2024, PROBAST+AI 2025, STARD+AI
│   ├── methodology/                 # Leakage taxonomy, disease definitions
│   ├── case-studies/                # 107 NC papers × 375 reviewer concerns
│   ├── codebooks/                   # NHANES/UKB variable metadata + SQLite
│   ├── protocols/                   # 9-phase workflow specifications
│   ├── operations/                  # Error KB, gate matrix, scoring
│   └── templates/                   # JSON schema templates
│
├── examples/            (16 CSVs)   # ─── Medical Datasets ───
│   ├── heart_disease.csv            # UCI, 297 rows
│   ├── pima_diabetes.csv            # UCI, 768 rows
│   ├── framingham_heart.csv         # Framingham, 4240 rows
│   ├── support2.csv                 # Vanderbilt SUPPORT2, 9105 rows
│   ├── nhanes_diabetes.csv          # CDC NHANES, 15549 rows
│   ├── sepsis_survival.csv          # MIMIC-derived, 129K rows
│   └── ...                          # 10 more datasets (526K+ total rows)
│
├── experiments/                     # ─── Benchmarks & Test Results ───
│   ├── authority-e2e/               # 4-dataset adversarial benchmark suite
│   ├── support2-benchmark/          # SUPPORT2 (9105 rows, ROC-AUC 0.892)
│   ├── nhanes-benchmark/           # NHANES (15549 rows, ROC-AUC 0.810)
│   ├── rhc-benchmark/              # RHC ICU (5735 rows, ROC-AUC 0.750)
│   ├── ckd-benchmark/              # CKD (399 rows, ROC-AUC 0.999)
│   └── sepsis-benchmark/           # Sepsis (129K rows, ROC-AUC 0.689)
│
├── agents/              (2 YAMLs)   # API agent configs (paper extractor + reviewer)
│
├── ARCHITECTURE.md                  # This file
├── CLAUDE.md                        # Agent operating protocol
├── SKILL.md                         # /mlgg skill definition
├── README.md                        # Project documentation (中文)
├── README_EN.md                     # Project documentation (English)
└── pyproject.toml                   # Package metadata
```

## Three Product Entry Points

```
1. mlgg-lint          pip install mlgg-lint && mlgg-lint check code.py
                      Zero deps. 27 AST rules. Catches data leakage in 5 seconds.

2. audit-metrics      python3 scripts/reporting/audit_metrics.py --metrics '{...}'
                      Zero deps. Checks publication readiness from Table 2 numbers.

3. mlgg onboarding    python3 -m scripts.orchestration.mlgg onboarding --input-csv data.csv
                      Full pipeline: split → train → 33 gates → evidence report.
```

## Data Flow

```
User CSV
  │
  ├─ Feature Timing Review ──→ classify each column as:
  │   ├─ at_prediction (safe)
  │   ├─ after_prediction (auto-excluded by pattern + correlation)
  │   └─ unknown (flagged for user review)
  │
  ├─ Split ──→ train / valid / test (patient-disjoint, temporal ordering)
  │
  ├─ Train ──→ 5 model families, one-SE selection on valid, 14-metric eval on test
  │             produces: evidence/*.json (evaluation, model_selection, CI, robustness, ...)
  │
  └─ 33 Gate DAG ──→ validate all evidence artifacts
      ├─ Layer 0 (CONTRACT): request_contract, cohort_definition
      ├─ Layer 1 (MANIFEST): manifest_lock
      ├─ Layer 2 (ATTESTATION): execution_attestation
      ├─ Layer 3 (DATA_VALIDATION): leakage, split_protocol, covariate_shift, reporting_bias
      ├─ Layer 4 (POLICY_AUDIT): feature_lineage, definition_variable, imbalance, missingness, tuning
      ├─ Layer 5 (MODEL_AUDIT): model_selection, CI_matrix, SHAP, clinical_metrics, feature_engineering, metric_consistency
      ├─ Layer 6 (METRIC_VALIDATION): calibration_dca, fairness, external_validation, generalization_gap, distribution, permutation, prediction_replay, robustness, sample_size, seed_stability, evaluation_quality
      ├─ Layer 7 (AGGREGATION): publication_gate
      └─ Layer 8 (FINAL): security_audit, self_critique
```

## Gate Contract

```
python3 scripts/gates/<gate>.py --report <output.json> [--strict] [args]

Exit 0 = PASS    Exit 2 = FAIL    Exit 1 = ERROR

Report: { status, failure_count, warning_count, failures[], warnings[],
          execution_time_seconds, envelope_version: "2.0.0" }
```

## Key Design Decisions

- **Subprocess isolation**: Gates communicate via JSON files, not imports.
- **Fail-closed**: Missing or unparseable evidence = FAIL.
- **Continue-on-fail**: Onboarding runs all 33 gates even if some fail.
- **Feature timing**: Pre-training review classifies columns as at/after/unknown prediction time.
- **Two claim tiers**: `publication-grade` (requires external validation) vs `leakage-audited` (relaxed).
- **Categorical preservation**: String columns bypass numeric feature selection, encoded after selection.

## Tested Datasets

| Dataset | Rows | Features | Prevalence | ROC-AUC | PR-AUC | Calibration | Benchmark |
|---------|------|----------|-----------|---------|--------|-------------|-----------|
| **CKD** | **399** | **24** | 63% | **0.999** | **1.000** | slope=3.08 | `experiments/ckd-benchmark/` |
| Pima Diabetes | 768 | 8 | 35% | 0.845 | 0.789 | — | — |
| Framingham Heart | 4,240 | 15 | 15% | 0.737 | — | — | — |
| **RHC ICU** | **5,735** | **54** | 65% | **0.750** | **0.834** | slope=0.977 | `experiments/rhc-benchmark/` |
| **SUPPORT2** | **9,105** | **43** | 26% | **0.892** | **0.635** | slope=0.745 | `experiments/support2-benchmark/` |
| **NHANES** | **15,549** | **12** | 18% | **0.810** | **0.443** | — | `experiments/nhanes-benchmark/` |
| **Sepsis** | **129,392** | **3** | 9% | **0.689** | **0.159** | slope=0.804 | `experiments/sepsis-benchmark/` |

Feature counts exclude `patient_id`, `event_time`, `y` meta columns.
