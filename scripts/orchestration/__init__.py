"""
Orchestration layer — pipeline runners and CLI entry points.

Entry Point Hierarchy:
    mlgg.py               <- Primary CLI (pyproject.toml: mlgg = mlgg:cli_main)
    ├── mlgg_onboarding.py    <- Auto-onboarding workflow (mlgg onboarding)
    ├── mlgg_pixel.py         <- Interactive TUI mode (pyproject.toml: mlgg-pixel)
    └── mlgg_interactive.py   <- Guided interactive mode (mlgg play)

Pipeline Runners (called by orchestrator, not directly by users):
    run_dag_pipeline.py       <- DAG-based gate execution
    run_productized_workflow.py <- Thin wrapper for productized runs

Testing:
    run_endurance_test.py     <- Stress/endurance test harness (internal)
"""
