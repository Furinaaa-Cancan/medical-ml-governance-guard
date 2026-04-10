"""
Core framework — shared infrastructure for all gates and tools.

Modules:
    _gate_framework.py      <- GateIssue, Severity, build_report_envelope, print_gate_summary
    _gate_utils.py          <- add_issue, load_json, write_json, try_parse_time, etc.
    _gate_registry.py       <- GATE_REGISTRY (name -> metadata for all 33 gates)
    _security.py            <- Path traversal, injection, and privilege checks
    _peer_review_retrieval.py <- NC peer review knowledge base retrieval
    _audit_shared.py        <- Shared audit utilities
"""
