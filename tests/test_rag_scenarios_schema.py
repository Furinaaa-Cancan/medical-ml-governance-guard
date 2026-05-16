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


def test_weak_zero_scenarios_declare_required_fields() -> None:
    """W4-added WEAK/ZERO scenarios must declare the audit-facing contract.

    H19 LLM-loop audits filter scenarios by ``expected_difficulty`` to test
    hedge/honesty behavior on low-information retrievals. If a WEAK or ZERO
    scenario lands here without the threshold fields, the audit cannot
    assert correctness — so this test fences the schema explicitly.
    """
    data = json.loads(CANONICAL.read_text(encoding="utf-8"))
    flagged = [
        s for s in data["scenarios"]
        if s.get("expected_difficulty") in {"WEAK", "ZERO"}
    ]
    assert flagged, (
        "Expected at least one WEAK or ZERO scenario for H19-style audits "
        "(see W4 task: real off-domain queries replacing synthesized "
        "nonsense-code probes)."
    )
    for s in flagged:
        assert "query_text" in s and s["query_text"], (
            f"Scenario {s['scenario_id']} flagged as "
            f"{s['expected_difficulty']} but has no query_text — audits "
            "cannot reproduce the retrieval."
        )
        for field in ("expected_n_hits_lt", "expected_top1_score_lt"):
            assert field in s, (
                f"Scenario {s['scenario_id']} flagged as "
                f"{s['expected_difficulty']} missing {field!r} threshold."
            )


def test_weak_scenarios_actually_weak() -> None:
    """W4-added WEAK scenarios should genuinely retrieve weakly today.

    If a future KB curation makes one strong (top-1 >= 0.5), the scenario
    should be re-classified or the WEAK example replaced. This test is the
    canary for that drift. Skipped if the RAG stack can't load (e.g. CI
    environment without sentence-transformers).
    """
    data = json.loads(CANONICAL.read_text(encoding="utf-8"))
    weak = [
        s for s in data["scenarios"]
        if s.get("expected_difficulty") == "WEAK"
    ]
    if not weak:
        import pytest
        pytest.skip("no WEAK scenarios in fixture")

    try:
        from scripts.rag import rag_query
    except ImportError:
        import pytest
        pytest.skip("RAG stack unavailable")

    failures = []
    for s in weak:
        results = rag_query(s["query_text"], top_k=5)
        top1 = results[0].get("_final_score", 0.0) if results else 0.0
        # Generous ceiling: WEAK shouldn't be above 0.5. If we cross it,
        # the KB has grown to cover the topic and the scenario is stale.
        if top1 >= 0.5:
            failures.append(
                f"{s['scenario_id']}: top1={top1:.3f} (no longer WEAK; "
                f"reclassify or replace)"
            )
    assert not failures, (
        "WEAK scenarios have strengthened — re-classify or replace: "
        + "; ".join(failures)
    )


def test_zero_scenarios_actually_zero() -> None:
    """W4-added ZERO scenarios should retrieve nothing (or near-nothing).

    rag_query() returns [] for empty/whitespace queries by contract; this
    test guards against an accidental relaxation of that sentinel.
    """
    data = json.loads(CANONICAL.read_text(encoding="utf-8"))
    zero = [
        s for s in data["scenarios"]
        if s.get("expected_difficulty") == "ZERO"
    ]
    if not zero:
        import pytest
        pytest.skip("no ZERO scenarios in fixture")

    try:
        from scripts.rag import rag_query
    except ImportError:
        import pytest
        pytest.skip("RAG stack unavailable")

    failures = []
    for s in zero:
        results = rag_query(s["query_text"], top_k=5)
        if results:
            top1 = results[0].get("_final_score", 0.0)
            # Generous: ZERO can tolerate stray near-zero hits. Real failure
            # is "we got back semantically-scored content where none was
            # expected".
            if top1 >= 0.1:
                failures.append(
                    f"{s['scenario_id']}: n={len(results)} top1={top1:.3f} "
                    "(no longer ZERO)"
                )
    assert not failures, (
        "ZERO scenarios are returning content — re-examine: "
        + "; ".join(failures)
    )
