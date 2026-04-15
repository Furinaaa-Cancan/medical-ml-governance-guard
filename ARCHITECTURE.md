# Architecture

## Directory Structure

```
ml-leakage-guard/
│
├── plugin/                          # Product A: mlgg-lint (independent package)
│   ├── pyproject.toml               #   pip install mlgg-lint
│   └── mlgg_lint/                   #   27 AST rules, zero external deps
│       └── rules/                   #   r001–r027
│
├── scripts/
│   ├── core/                        # Internal framework (shared by all gates)
│   │   ├── _gate_framework.py       #   Report envelope, severity, remediation registry
│   │   ├── _gate_registry.py        #   33-gate DAG registry + topological sort
│   │   ├── _gate_utils.py           #   Calibration, VIF, NRI/IDI, SHAP, DCA, bootstrap CI
│   │   ├── _security.py             #   Pickle validation, path traversal defense
│   │   ├── _audit_shared.py         #   Code pattern scanning
│   │   └── _peer_review_retrieval.py#   107-paper KB query engine
│   │
│   ├── gates/                       # 33 fail-closed gates (each a standalone CLI)
│   │   ├── request_contract_gate.py #   Input contract validator (DAG entry point)
│   │   ├── leakage_gate.py          #   Row/entity/temporal overlap
│   │   ├── calibration_dca_gate.py  #   Calibration + decision curve analysis
│   │   ├── publication_gate.py      #   TRIPOD+AI/PROBAST+AI aggregator (depends on all)
│   │   └── ...                      #   30 more gates
│   │
│   ├── training/                    # Model training and data preparation
│   │   ├── train_select_evaluate.py #   5-model CV + one-SE selection + 14-metric eval
│   │   ├── split_data.py            #   Stratified/temporal split with entity isolation
│   │   ├── init_project.py          #   Project scaffolding (configs/, data/, evidence/)
│   │   ├── schema_preflight.py      #   CSV schema validation
│   │   ├── generate_demo_medical_dataset.py
│   │   └── generate_execution_attestation.py
│   │
│   ├── reporting/                   # Reports, audits, and output generation
│   │   ├── audit_metrics.py         #   Product B: lightweight metrics checker (zero deps)
│   │   ├── audit_external_project.py#   10-dimension project audit
│   │   ├── generate_audit_report.py #   TRIPOD+AI/PROBAST+AI report
│   │   ├── render_user_summary.py   #   Human-readable summary from evidence/
│   │   ├── export_latex.py          #   Publication-ready LaTeX tables
│   │   └── ...                      #   8 more tools
│   │
│   ├── codebooks/                   # Data dictionary tools (NHANES, UK Biobank)
│   │   ├── nhanes_codebook_lookup.py#   60K variables, FTS5 search
│   │   ├── ukb_codebook_lookup.py   #   UK Biobank variable lookup
│   │   ├── build_nhanes_codebook_db.py
│   │   └── ...                      #   5 more tools
│   │
│   ├── review/                      # Paper analysis and peer review
│   │   ├── peer_review_lookup.py    #   107-paper reviewer concern database
│   │   ├── batch_journal_review.py  #   Multi-paper audit
│   │   ├── extract_paper_metadata.py#   PDF → structured metadata
│   │   └── ...
│   │
│   ├── diagnostics/                 # Environment and runtime tools
│   │   ├── env_doctor.py            #   Dependency health check
│   │   ├── init_guide.py            #   Interactive project guide
│   │   ├── mlgg_web.py              #   Flask web UI
│   │   └── ...
│   │
│   └── orchestration/               # Pipeline orchestration
│       ├── mlgg.py                  #   [ENTRY POINT] Unified CLI router
│       ├── mlgg_onboarding.py       #   Guided novice workflow (auto mode)
│       ├── run_dag_pipeline.py      #   DAG-based gate execution
│       ├── run_productized_workflow.py # doctor → preflight → DAG → summary
│       ├── mlgg_interactive.py      #   Interactive wizard
│       └── mlgg_pixel.py            #   Terminal pixel-art UI
│
├── tests/                           # 4000+ test functions
├── references/                      # Knowledge base (standards, case studies, protocols)
├── examples/                        # 16 medical datasets + downloaders
└── nhanes-codebook/                 # Companion: 60K NHANES variables (SQLite)
```

## Three Product Entry Points

```
Users encounter MLGG through three progressively deeper interfaces:

1. mlgg-lint          pip install mlgg-lint && mlgg-lint check code.py
                      Zero deps, 5 seconds, catches data leakage in existing code.

2. audit-metrics      python3 scripts/reporting/audit_metrics.py --metrics '{...}'
                      Zero deps, instant, checks publication readiness from Table 2 numbers.

3. mlgg onboarding    python3 -m scripts.orchestration.mlgg onboarding --input-csv data.csv
                      Full 33-gate pipeline, trains models, generates evidence directory.
```

## Call Graph

```
mlgg.py (CLI router)
  ├── onboarding ──→ mlgg_onboarding.py
  │   ├── env_doctor.py           (diagnostics/)
  │   ├── init_project.py         (training/)
  │   ├── split_data.py           (training/)
  │   ├── train_select_evaluate.py(training/)     ← largest file, 8500 LOC
  │   ├── generate_execution_attestation.py (training/)
  │   └── run_productized_workflow.py (orchestration/)
  │       ├── env_doctor.py
  │       ├── schema_preflight.py
  │       ├── run_dag_pipeline.py ──→ 33 gates (topological order)
  │       │   ├── request_contract_gate  (layer 0 — must pass first)
  │       │   ├── cohort_definition_gate (layer 0)
  │       │   ├── leakage_gate           (layer 1)
  │       │   ├── split_protocol_gate    (layer 1)
  │       │   ├── ...                    (layers 2-5)
  │       │   ├── publication_gate       (layer 6 — depends on all 30 gates)
  │       │   ├── security_audit_gate    (layer 7)
  │       │   └── self_critique_gate     (layer 7)
  │       └── render_user_summary.py
  │
  ├── train ──→ train_select_evaluate.py (direct)
  ├── lint ──→ plugin/mlgg_lint (independent package)
  ├── audit ──→ audit_external_project.py (reporting/)
  └── audit-metrics ──→ audit_metrics.py (reporting/)
```

## Gate Contract

Every gate follows the same CLI contract:

```
python3 scripts/gates/<gate>.py --report <output.json> [--strict] [gate-specific args]

Exit codes:
  0 = PASS (no failures; warnings allowed unless --strict)
  2 = FAIL (failures found, or warnings in --strict mode)
  1 = ERROR (unexpected crash)

Report envelope (v2.0.0):
  { status, failure_count, warning_count, failures[], warnings[],
    execution_time_seconds, envelope_version }
```

## Key Design Decisions

- **Subprocess isolation**: Gates and tools communicate via subprocess + JSON files,
  not Python imports. This prevents state leakage between pipeline stages.
- **Fail-closed**: Gates default to FAIL when evidence is missing or unparseable.
- **DAG ordering**: `_gate_registry.py` defines dependencies; `run_dag_pipeline.py`
  executes in topological order and stops at first failure (unless --continue-on-fail).
- **Two claim tiers**: `publication-grade` (requires external validation) and
  `leakage-audited` (relaxed, no external data needed).
