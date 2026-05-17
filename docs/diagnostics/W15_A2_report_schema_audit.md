# W15-A2 — `--report` JSON Schema Audit

**Scope:** 33 gates in `scripts/gates/`. **Probed at runtime:** 15 invocations, 10 envelopes written.

## Verdict: **PASS**

All 33 gates import `build_report_envelope` from `scripts/core/_gate_framework.py` (`REPORT_ENVELOPE_VERSION = "2.0.0"`); envelope shape is structurally enforced.

## Canonical envelope

Required (11): `envelope_version, gate_name, gate_version, status, strict_mode, execution_timestamp_utc, execution_time_seconds, failure_count, warning_count, failures, warnings`.
Optional (4): `summary, input_files, peer_review_context, peer_review_status`.
Per-issue: `code, severity, message, details, remediation`.

Task prompt listed `severity` top-level — actually per-issue. Top-level severity = `status` ∈ {pass, fail, error}.

## Runtime conformity (10/10 gates)

All conform: `calibration_dca_gate, ci_matrix_gate, clinical_metrics_gate, evaluation_quality_gate, fairness_equity_gate, manifest_lock, publication_gate, sample_size_gate, security_audit_gate, self_critique_gate`. Zero missing required keys, zero type errors. Per-issue `severity` present on every `failures[]`/`warnings[]` item. Only one extras finding: `sample_size_gate` adds `info`, `thresholds` (item 1 below).

5 gates rejected argparse pre-`--report` (missing fixtures, not defects): `cohort_definition_gate, leakage_gate, feature_engineering_audit_gate, reporting_bias_gate, metric_consistency_gate`.

## Top-5 schema drift

1. `sample_size_gate` — top-level `info`, `thresholds` via undocumented `extra` channel.
2. `covariate_shift_gate` — top-level `top_shift_features`, `top_missingness_shift_features`.
3. `request_contract_gate` — top-level `normalized_request`.
4. Task templates list `severity` top-level; should source from `_gate_framework.REPORT_ENVELOPE_VERSION`.
5. **Naming collision**: non-gate artifacts share `*_report.json` suffix (`evaluation_report.json` from `train_select_evaluate.py`, plus `feature_engineering_/phase2_split_/dag_pipeline_report.json`). Upstream pipeline outputs with intentionally different schema; downstream RAG/aggregation risks false positives if it blind-globs.

## Wave-N+ recommendations

- Add `scripts/validation/validate_gate_envelope.py` sourcing required-key set from `_gate_framework.py` (single source of truth).
- CI gate: validate every `*_report.json` emitted by `scripts/gates/`; fail PR on drift.
- Rename non-gate artifacts to `*_artifact.json` or move to `evidence/artifacts/`.
- Promote `sample_size_gate.info/thresholds` into `summary`, or document `extra` per gate.

Probes: `/tmp/W15_A2_*.json`.
