"""Enforces ONE canonical scenarios.json schema after H11 reconciliation.

H10 created scripts/rag/evals/scenarios.json before discovering
references/retrieval_eval/scenarios.json already existed with a different
schema (consumed by scripts/rag/evals/harness.py). H11 reconciled the
drift by merging H10's additive fields (query_text, baseline_p5_e1,
expected_relevant_tags, failure_codes_hint, known_weakness) into the
canonical file at references/retrieval_eval/scenarios.json and removing
the H10 copy.

This test fails fast if the duplication ever returns.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
DEPRECATED = REPO_ROOT / "scripts" / "rag" / "evals" / "scenarios.json"


def test_only_one_canonical_scenarios_file() -> None:
    """Exactly ONE scenarios.json (per H11 decision) — not both."""
    candidates = [CANONICAL, DEPRECATED]
    existing = [p for p in candidates if p.exists()]
    assert existing == [CANONICAL], (
        f"Schema drift: scenarios.json present at unexpected path(s). "
        f"After H11 reconciliation, only {CANONICAL.relative_to(REPO_ROOT)} "
        f"should exist. Found:\n  "
        + "\n  ".join(str(p.relative_to(REPO_ROOT)) for p in existing)
        + "\nIf adding a new fixture path, update this test's canonical "
        "list AND verify harness.py consumes the right one."
    )


def test_canonical_file_loads_and_has_required_schema() -> None:
    """Canonical file is well-formed and exposes the fields harness.py reads."""
    assert CANONICAL.exists(), f"Canonical scenarios file missing: {CANONICAL}"
    data = json.loads(CANONICAL.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Top-level must be an object"
    assert "scenarios" in data and isinstance(data["scenarios"], list), (
        "Must have a 'scenarios' array (harness.py reads scenarios_data['scenarios'])"
    )
    assert data["scenarios"], "Scenarios list must not be empty"

    # Fields harness.evaluate_scenario() requires on every scenario:
    required = {"scenario_id", "gate_name"}
    # And reads (with .get default) — these should be present for meaningful eval:
    expected = {"failure_codes", "expected_categories", "expected_tags"}
    for s in data["scenarios"]:
        missing = required - set(s.keys())
        assert not missing, (
            f"Scenario {s.get('scenario_id', '<unknown>')} missing required "
            f"harness fields: {missing}"
        )
        absent = expected - set(s.keys())
        assert not absent, (
            f"Scenario {s['scenario_id']} missing harness-consumed fields: "
            f"{absent}"
        )


def test_harness_module_imports_without_error() -> None:
    """harness.py should import cleanly — sanity check that consumer is intact."""
    from scripts.rag.evals import harness

    assert harness.DEFAULT_SCENARIOS == CANONICAL, (
        f"harness.DEFAULT_SCENARIOS ({harness.DEFAULT_SCENARIOS}) drifted from "
        f"canonical path ({CANONICAL}). Update one or the other."
    )


def test_h10_additive_fields_preserved_on_matched_scenarios() -> None:
    """H11 merged H10's E1-derived fields onto matching canonical scenarios."""
    data = json.loads(CANONICAL.read_text(encoding="utf-8"))
    matched = [s for s in data["scenarios"] if "h10_legacy_id" in s]
    assert matched, (
        "Expected H11 to have merged H10 fields onto at least one canonical "
        "scenario (look for 'h10_legacy_id' marker)."
    )
    for s in matched:
        for field in (
            "query_text",
            "baseline_p5_e1",
            "expected_relevant_tags",
            "failure_codes_hint",
        ):
            assert field in s, (
                f"Scenario {s['scenario_id']} marked as H10-merged but "
                f"missing additive field {field!r}"
            )
