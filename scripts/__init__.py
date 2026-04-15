"""
ml-governance-guard (MLGG) — Publication-grade medical ML governance framework.

Package layout:
    scripts/
    ├── core/           <- Framework internals (gate base, utils, security)
    ├── gates/          <- 33 fail-closed governance gates
    ├── tools/          <- Training, data, reporting, RAG tools
    └── orchestration/  <- CLI entry points and pipeline runners

Import convention:
    Gates and tools are designed as standalone CLI scripts. They use a
    sys.path hack to import from core/ at the module level. For library
    usage (tests, orchestration), import via the package:

        from scripts.gates.leakage_gate import main
        from scripts.training.train_select_evaluate import metric_panel

    For pytest, tests/conftest.py sets up sys.path globally.
"""
