# Gates Reference (33 Fail-Closed Gates)

> Authoritative reference for MLGG's 33 fail-closed gates. Each gate is a
> standalone Python module under `scripts/gates/`, exposes a `--report` CLI,
> exits `0` (pass) / `2` (fail) / `1` (usage error), and emits a structured
> JSON envelope with `failures`, `warnings`, `severity`, `gate_name`, and
> failure detail records.
>
> Source of truth: [`scripts/core/_gate_registry.py`](../../scripts/core/_gate_registry.py).
> This document is generated from the registry and the gate scripts; if they
> disagree, the registry wins.

## Quick links

- Back to README: [English](../../README_EN.md) | [Chinese](../../README.md)
- Architecture overview: [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
- RAG troubleshooting: [docs/RAG_TROUBLESHOOTING.md](../RAG_TROUBLESHOOTING.md)
- KB tag style: [docs/KB_TAG_STYLE_GUIDE.md](../KB_TAG_STYLE_GUIDE.md)
- Lint rules: [docs/reference/LINT_RULES.md](LINT_RULES.md) — static checks
  that complement these runtime gates.

---

## CLI contract (every gate)

Every gate honours the same surface so the DAG runner, `mlgg audit`, and
external CI all interoperate:

| Aspect | Contract |
|---|---|
| Entry point | `python -m scripts.gates.<gate_name> [args] --report <path>` |
| Report flag | `--report PATH` writes the JSON envelope; mandatory. |
| Strict flag | `--strict` upgrades warnings to failures (`severity` toggles). |
| Exit code | `0` pass, `2` fail (or strict warning), `1` usage / input error. |
| Stdout | Free-form human summary; not parsed downstream. |
| Stderr | Diagnostics only; never consumed for pass/fail decisions. |
| Determinism | Same inputs + same seed must yield byte-identical reports. |

The shared helpers live in [`scripts/core/_gate_framework.py`](../../scripts/core/_gate_framework.py)
(`finish()`, `to_float()`, report scaffolding) and
[`scripts/core/_gate_utils.py`](../../scripts/core/_gate_utils.py)
(I/O guards, numerical safety). Do not bypass them when adding a new gate.

### JSON envelope shape

```json
{
  "gate_name": "leakage_gate",
  "gate_version": "1.x.y",
  "severity": "ERROR",
  "passed": false,
  "failures": [ { "rule": "S01", "message": "...", "evidence": {...} } ],
  "warnings": [ { "rule": "F04", "message": "...", "evidence": {...} } ],
  "inputs": { "train": "sha256:...", "request": "sha256:..." },
  "elapsed_seconds": 1.42
}
```

Failure records always carry enough evidence (file path, row count, column
name, computed statistic) for a reviewer to reproduce the finding without
re-running the pipeline. Aggregation gates (`publication_gate`,
`self_critique_gate`) consume only the envelope, never gate internals.

---

## Canonical rule code mapping

Methodology rule IDs are defined in [`README_EN.md` "33 Methodology Rules"](../../README_EN.md#33-methodology-rules)
and in [`CLAUDE.md`](../../CLAUDE.md#不可协商规则违反--critical) ("Non-Negotiable
Rules"). Each rule is enforced at runtime by one or more gates listed below.
Static checks for the same rules live in [`LINT_RULES.md`](LINT_RULES.md).

| Rule | Severity | Enforcing gate(s) |
|---|---|---|
| **C01** define eligible cohort | CRITICAL | `cohort_definition_gate` |
| **S01** same patient never crosses splits | CRITICAL | `leakage_gate`, `split_protocol_gate` |
| **S02** test temporally later than train | CRITICAL | `split_protocol_gate`, `leakage_gate` |
| **P01** preprocessors fit only on train | CRITICAL | `feature_engineering_audit_gate`, `tuning_leakage_gate` |
| **P02** SMOTE only on train; warn on calibration | CRITICAL | `imbalance_policy_gate` |
| **P03** no global cleaning before split | CRITICAL | `split_protocol_gate`, `feature_engineering_audit_gate` |
| **P04** imputation statistics from train only | CRITICAL | `missingness_policy_gate` |
| **P05** correct categorical encoding | CRITICAL | `feature_engineering_audit_gate` |
| **P06** stratify missingness by mechanism | WARNING | `missingness_policy_gate` |
| **F01** target not a feature | CRITICAL | `leakage_gate`, `definition_variable_guard`, `cohort_definition_gate` |
| **F02** no post-index information | CRITICAL | `leakage_gate`, `feature_lineage_gate`, `definition_variable_guard` |
| **F03** feature selection only on train | CRITICAL | `feature_engineering_audit_gate` |
| **F04** no univariate screening | WARNING | `feature_engineering_audit_gate` |
| **F05** prediction time point declared | CRITICAL | `feature_lineage_gate`, `definition_variable_guard` |
| **F06** Elastic Net + stability selection | WARNING | `feature_engineering_audit_gate` |
| **M01** no tuning on test set | CRITICAL | `tuning_leakage_gate`, `model_selection_audit_gate` |
| **M02** threshold chosen on validation | CRITICAL | `clinical_metrics_gate`, `calibration_dca_gate` |
| **M03** >= 3 model families compared | WARNING | `model_selection_audit_gate` |
| **M04** selection by validation, not gap | CRITICAL | `model_selection_audit_gate`, `generalization_gap_gate` |
| **E01** 95% CI on primary metric | CRITICAL | `ci_matrix_gate`, `evaluation_quality_gate` |
| **E02** complete 14-metric panel | CRITICAL | `clinical_metrics_gate`, `calibration_dca_gate` |
| **E03** ECE < 0.06 | WARNING | `calibration_dca_gate` |
| **E04** gap is diagnostic, not selection | WARNING | `generalization_gap_gate`, `model_selection_audit_gate` |
| **E05** balanced class weight needs calibration | WARNING | `calibration_dca_gate`, `imbalance_policy_gate` |
| **E06** bootstrap optimism correction | WARNING | `evaluation_quality_gate`, `ci_matrix_gate` |
| **Z01** sample size (EPV >= 10, Riley) | WARNING | `sample_size_gate`, `cohort_definition_gate` |
| **R01** random_state set | INFO | `seed_stability_gate` |
| **R02** multi-seed stability | WARNING | `seed_stability_gate` |
| **T01** TRIPOD+AI compliance | WARNING | `reporting_bias_gate` |
| **Q01** subgroup analysis present | WARNING | `fairness_equity_gate`, `robustness_gate` |
| **Q02** subgroup metrics need CI | WARNING | `fairness_equity_gate` |

A single rule violation can surface in multiple gates; the registry preserves
this redundancy on purpose so a single gate failure cannot mask a methodology
breach.

---

## All 33 gates by layer

The 33 gates are arranged in a 9-layer DAG (`GateLayer.CONTRACT` ... `GateLayer.FINAL`).
Gates within the same layer can run in parallel; cross-layer order is fixed
by the `depends_on` graph in
[`scripts/core/_gate_registry.py`](../../scripts/core/_gate_registry.py).

Columns:

- **Module** — script under `scripts/gates/`.
- **Depends on** — direct dependencies (other gate reports consumed).
- **Report** — output basename written into `evidence_dir/`.
- **rag_optional** — `True` for infra/meta gates with no peer-review domain;
  the RAG bridge suppresses "no related concerns retrieved" placeholders.

### Layer 0 — `CONTRACT`

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `cohort_definition_gate` | [cohort_definition_gate.py](../../scripts/gates/cohort_definition_gate.py) | — | `cohort_definition_report.json` | False |
| `request_contract_gate` | [request_contract_gate.py](../../scripts/gates/request_contract_gate.py) | — | `request_contract_report.json` | True |

`cohort_definition_gate` checks EPV adequacy, Riley triple criteria, data
typing, missingness profile, and outcome-definition leakage (see
discharge-finalized ICD detector and the immortal-time regex in the source).
`request_contract_gate` normalizes the request JSON, validates schema, and
applies anti-downgrade protection on the publication strategy field.

### Layer 1 — `MANIFEST`

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `manifest_lock` | [manifest_lock.py](../../scripts/gates/manifest_lock.py) | `request_contract_gate` | `manifest.json` | True |

Computes SHA-256 fingerprints for every data file, config, evaluation
artifact, and gate script. Downstream gates re-verify these fingerprints; any
silent edit between layers is treated as tampering.

### Layer 2 — `ATTESTATION`

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `execution_attestation_gate` | [execution_attestation_gate.py](../../scripts/gates/execution_attestation_gate.py) | `manifest_lock` | `execution_attestation_report.json` | False |

Verifies detached signatures, the out-of-band `trusted_signers.json`
fingerprint allowlist (external trust anchor), `--max-age-hours` freshness
(default 168h anti-replay), bundle path sandbox (rejects symlink escape), and
witness arbitration. See `references/attestation/README.md` for the trust
model.

### Layer 3 — `DATA_VALIDATION` (4 parallel)

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `leakage_gate` | [leakage_gate.py](../../scripts/gates/leakage_gate.py) | `request_contract_gate` | `leakage_report.json` | False |
| `split_protocol_gate` | [split_protocol_gate.py](../../scripts/gates/split_protocol_gate.py) | `request_contract_gate` | `split_protocol_report.json` | False |
| `covariate_shift_gate` | [covariate_shift_gate.py](../../scripts/gates/covariate_shift_gate.py) | `request_contract_gate` | `covariate_shift_report.json` | False |
| `reporting_bias_gate` | [reporting_bias_gate.py](../../scripts/gates/reporting_bias_gate.py) | `request_contract_gate` | `reporting_bias_report.json` | False |

`leakage_gate` covers row-hash overlap, patient ID overlap, temporal boundary
violations, and a 7-category feature-name regex (target words, immortal time,
discharge-finalized ICD codes, etc.).
`split_protocol_gate` enforces patient-level disjoint splits, temporal
correctness, stratified prevalence, and minimum split sizes.
`covariate_shift_gate` computes per-feature Jensen-Shannon divergence,
prevalence drift, and missing-rate drift between splits.
`reporting_bias_gate` enforces TRIPOD+AI 2024 (17 items), PROBAST+AI 2025
(6 domains), and the STARD-AI checklist.

### Layer 4 — `POLICY_AUDIT` (5 parallel)

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `definition_variable_guard` | [definition_variable_guard.py](../../scripts/gates/definition_variable_guard.py) | `request_contract_gate`, `split_protocol_gate` | `definition_guard_report.json` | False |
| `feature_lineage_gate` | [feature_lineage_gate.py](../../scripts/gates/feature_lineage_gate.py) | `request_contract_gate`, `split_protocol_gate` | `lineage_report.json` | False |
| `imbalance_policy_gate` | [imbalance_policy_gate.py](../../scripts/gates/imbalance_policy_gate.py) | `request_contract_gate`, `split_protocol_gate` | `imbalance_policy_report.json` | False |
| `missingness_policy_gate` | [missingness_policy_gate.py](../../scripts/gates/missingness_policy_gate.py) | `request_contract_gate`, `split_protocol_gate` | `missingness_policy_report.json` | False |
| `tuning_leakage_gate` | [tuning_leakage_gate.py](../../scripts/gates/tuning_leakage_gate.py) | `request_contract_gate`, `split_protocol_gate` | `tuning_leakage_report.json` | False |

`definition_variable_guard` blocks outcome-definition variables as
predictors, plus circular-definition detection, time-window documentation,
and post-prediction feature leakage checks.
`feature_lineage_gate` blocks post-index-time derived features from training
based on the lineage spec.
`imbalance_policy_gate` validates the class-imbalance strategy (train-only
resampling, prevalence sanity).
`missingness_policy_gate` enforces the missingness policy: >5% triggers
mechanism testing, >40% triggers MNAR sensitivity analysis.
`tuning_leakage_gate` audits the hyperparameter tuning protocol (test
isolation, CV nesting, no overlap with selection).

### Layer 5 — `MODEL_AUDIT` (6 parallel)

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `model_selection_audit_gate` | [model_selection_audit_gate.py](../../scripts/gates/model_selection_audit_gate.py) | `request_contract_gate`, `split_protocol_gate` | `model_selection_audit_report.json` | False |
| `feature_engineering_audit_gate` | [feature_engineering_audit_gate.py](../../scripts/gates/feature_engineering_audit_gate.py) | `request_contract_gate`, `split_protocol_gate` | `feature_engineering_audit_report.json` | False |
| `clinical_metrics_gate` | [clinical_metrics_gate.py](../../scripts/gates/clinical_metrics_gate.py) | `request_contract_gate`, `split_protocol_gate` | `clinical_metrics_report.json` | False |
| `shap_interpretability_gate` | [shap_interpretability_gate.py](../../scripts/gates/shap_interpretability_gate.py) | `request_contract_gate`, `split_protocol_gate` | `shap_interpretability_report.json` | False |
| `ci_matrix_gate` | [ci_matrix_gate.py](../../scripts/gates/ci_matrix_gate.py) | `request_contract_gate`, `split_protocol_gate` | `ci_matrix_gate_report.json` | False |
| `metric_consistency_gate` | [metric_consistency_gate.py](../../scripts/gates/metric_consistency_gate.py) | `request_contract_gate` | `metric_consistency_report.json` | False |

`model_selection_audit_gate` replays the one-SE rule, enforces >= 3 candidate
families, requires a logistic-regression baseline, and verifies fingerprints.
`feature_engineering_audit_gate` audits feature-group provenance, training-set
scope, and stability evidence.
`clinical_metrics_gate` enforces the 14-metric panel, confusion-matrix
consistency, and clinical floor thresholds.
`shap_interpretability_gate` produces a multi-model SHAP ensemble with
Kendall tau consistency and four publication-grade CSVs.
`ci_matrix_gate` and `metric_consistency_gate` are functionally "Layer 6"
work but moved into `MODEL_AUDIT` to break an intra-layer dependency cycle
(they feed `evaluation_quality_gate` and `permutation_significance_gate`).

> Discrepancy note: `README_EN.md` predates the
> `ci_matrix_gate` / `metric_consistency_gate` layer move and still lists
> them under "Layer 6". The DAG enum is authoritative; the count and order
> here come from the registry.

### Layer 6 — `METRIC_VALIDATION` (11 parallel)

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `calibration_dca_gate` | [calibration_dca_gate.py](../../scripts/gates/calibration_dca_gate.py) | `request_contract_gate`, `split_protocol_gate` | `calibration_dca_report.json` | False |
| `distribution_generalization_gate` | [distribution_generalization_gate.py](../../scripts/gates/distribution_generalization_gate.py) | `request_contract_gate`, `split_protocol_gate` | `distribution_generalization_report.json` | False |
| `evaluation_quality_gate` | [evaluation_quality_gate.py](../../scripts/gates/evaluation_quality_gate.py) | `request_contract_gate`, `metric_consistency_gate`, `ci_matrix_gate` | `evaluation_quality_report.json` | False |
| `external_validation_gate` | [external_validation_gate.py](../../scripts/gates/external_validation_gate.py) | `request_contract_gate`, `split_protocol_gate` | `external_validation_gate_report.json` | False |
| `fairness_equity_gate` | [fairness_equity_gate.py](../../scripts/gates/fairness_equity_gate.py) | `request_contract_gate`, `split_protocol_gate` | `fairness_equity_report.json` | False |
| `generalization_gap_gate` | [generalization_gap_gate.py](../../scripts/gates/generalization_gap_gate.py) | `request_contract_gate`, `split_protocol_gate` | `generalization_gap_report.json` | False |
| `permutation_significance_gate` | [permutation_significance_gate.py](../../scripts/gates/permutation_significance_gate.py) | `request_contract_gate`, `metric_consistency_gate` | `permutation_report.json` | False |
| `prediction_replay_gate` | [prediction_replay_gate.py](../../scripts/gates/prediction_replay_gate.py) | `request_contract_gate`, `split_protocol_gate` | `prediction_replay_report.json` | False |
| `robustness_gate` | [robustness_gate.py](../../scripts/gates/robustness_gate.py) | `request_contract_gate`, `split_protocol_gate` | `robustness_gate_report.json` | False |
| `sample_size_gate` | [sample_size_gate.py](../../scripts/gates/sample_size_gate.py) | `request_contract_gate` | `sample_size_report.json` | False |
| `seed_stability_gate` | [seed_stability_gate.py](../../scripts/gates/seed_stability_gate.py) | `request_contract_gate`, `split_protocol_gate` | `seed_stability_report.json` | False |

Highlights:
- `calibration_dca_gate` validates ECE, slope/intercept, O:E ratio, CITL,
  DCA net benefit, and per-cohort calibration.
- `external_validation_gate` requires >= 100 events per external cohort; a
  missing external cohort caps the publication score at 85 and blocks L3.
- `fairness_equity_gate` covers equalized-odds gap, four-fifths disparate
  impact, subgroup performance floors, HEAL FPR/FNR, PPV fairness, and
  calibration fairness; subgroup CIs flag `n < 200` as unreliable.
- `sample_size_gate` requires EPV >= 10, shrinkage factor >= 0.90, and
  external >= 100 events (Riley 2019/2025).
- `seed_stability_gate` enforces PR-AUC std <= 0.03 across multi-seed runs;
  strict mode demands >= 5 seeds.

### Layer 7 — `AGGREGATION`

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `publication_gate` | [publication_gate.py](../../scripts/gates/publication_gate.py) | all gates with layer < 7 | `publication_gate_report.json` | False |

Aggregates every upstream report, computes the 12-dimension publication
score, compares fingerprints against the baseline, and applies the
fail-closed `disease_kb` reviewer requirement (W11-F2):
without an approved disease KB the gate refuses to grant L3 unless
`--allow-unreviewed-disease-kb` or `MLGG_ALLOW_UNREVIEWED_DISEASE_KB=1` is
explicitly passed (not recommended for publication).

### Layer 8 — `FINAL` (2 parallel)

| Gate | Module | Depends on | Report | rag_optional |
|---|---|---|---|---|
| `self_critique_gate` | [self_critique_gate.py](../../scripts/gates/self_critique_gate.py) | all gates except self | `self_critique_report.json` | True |
| `security_audit_gate` | [security_audit_gate.py](../../scripts/gates/security_audit_gate.py) | `publication_gate` | `security_audit_gate_report.json` | True |

`self_critique_gate` produces the 12-dimension quality score plus
actionable recommendations; it is a reflection layer with no peer-review
domain, hence `rag_optional`.
`security_audit_gate` re-verifies HMAC-SHA256 model signatures, evidence
integrity, dependency authenticity, and sensitive-data exposure on the final
bundle.

---

## Failure code conventions

Failure detail records use a free-form `rule` or `code` field. Convention:

- Methodology rule codes from `README_EN.md` § "33 Methodology Rules" —
  `S01`, `P01`, `F02`, `M04`, `E02`, `Z01`, `R02`, `T01`, `Q01`, etc. Used
  when a finding maps 1:1 to a documented rule.
- Gate-local codes prefixed by gate identifier (e.g.
  `LEAKAGE_ROW_HASH_OVERLAP`, `COHORT_EPV_INSUFFICIENT`) for findings that
  don't have a methodology-rule analogue.
- Aggregator codes (`PUBLICATION_FINGERPRINT_DRIFT`, `SELF_CRITIQUE_*`) for
  results computed only at Layer 7 / 8.

Severity values: `ERROR` (always fails), `WARNING` (fails only under
`--strict`), `INFO` (never fails, surfaced in the report for context).
The exact failure-code list per gate lives in each gate module; treat the
source files as authoritative (the registry intentionally does not duplicate
them to avoid drift).

---

## Aggregation and meta gates

`publication_gate` and `security_audit_gate` consume the upstream JSON
envelopes via the per-gate `aggregation_flag` declared in the registry
(e.g. `--leakage-report`, `--clinical-metrics-report`). The full mapping is
generated automatically by `scripts/orchestrator/run_dag.py` from
`GATE_REGISTRY` so adding a new gate only requires:

1. `_register(GateSpec(...))` in `_gate_registry.py`.
2. Implementing the gate module under `scripts/gates/<name>.py`.
3. Adding the gate's `aggregation_flag` to whichever aggregator must consume
   it (typically `publication_gate`).

The `rag_optional` flag controls one specific UX detail: when set, the
[`gate_rag_bridge`](../../scripts/core/gate_rag_bridge.py) suppresses the
"no related peer-review concerns retrieved" placeholder for an empty result
set. Silence is more honest than a placeholder that implies "we looked and
found nothing" when the reality is "this gate has no peer-review domain to
look in." Today this is set on:

- `request_contract_gate` (infra/contract validation)
- `manifest_lock` (integrity check)
- `self_critique_gate` (meta/reflection)
- `security_audit_gate` (security infra)

---

## Disease KB integration (W11-F2)

A separate diagnostic at
[`scripts/diagnostics/disease_kb_review_check.py`](../../scripts/diagnostics/disease_kb_review_check.py)
enforces clinician sign-off on the LLM-generated disease knowledge base. It
is intentionally NOT registered as a 34th gate, to keep the "33 gates"
contract referenced across 14 Markdown docs and 4 test assertions stable.
`publication_gate` calls into it as a fail-closed prerequisite for L3
publication eligibility; pre-publication callers can opt out with the
explicit override above.

---

## Running gates standalone

Every gate is independently executable. Examples:

```bash
# One-off leakage check, fail closed:
python -m scripts.gates.leakage_gate \
    --train data/train.csv --test data/test.csv \
    --id-cols patient_id --time-col index_time \
    --target-col outcome \
    --report out/leakage_report.json --strict

# Full pipeline via the DAG orchestrator (resolves dependencies, parallelizes):
python -m scripts.orchestrator.run_dag --request request.json --out-dir out/

# Re-run a single gate plus its transitive dependencies:
python -m scripts.orchestrator.run_dag --request request.json --out-dir out/ \
    --only calibration_dca_gate
```

Exit codes propagate; CI wraps the orchestrator and treats any `2` as a
release blocker.

---

## Related references

- [LINT_RULES.md](LINT_RULES.md) — 28 static analysis rules (R001-R028) that
  complement these runtime gates.
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) — overall system layout.
- [docs/RAG_TROUBLESHOOTING.md](../RAG_TROUBLESHOOTING.md) — RAG bridge ops.
- [docs/KB_TAG_STYLE_GUIDE.md](../KB_TAG_STYLE_GUIDE.md) — KB tag conventions.
- [README_EN.md § 9-Phase Workflow](../../README_EN.md#9-phase-workflow) —
  how gates fit into the end-to-end pipeline.
- [`scripts/core/_gate_registry.py`](../../scripts/core/_gate_registry.py) —
  the registry itself; always reconcile this document against the registry
  before publishing.
