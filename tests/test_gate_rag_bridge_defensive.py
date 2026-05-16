"""W7-P8 follow-up: focused unit tests for defensive branches in
``scripts/core/gate_rag_bridge.py`` that were previously uncovered.

These all target narrow malformed-input / fallback guards that the
existing integration tests can't reach without contrived input:

* ``_is_weak_match``: non-numeric ``_final_score`` and string
  ``_match_reasons`` coercion.
* ``_is_low_confidence``: non-numeric ``_dense_score``.
* ``_synthesize_query``: gate-name-only fallback when both failure
  codes and query hint are empty.
* ``_format_reasons``: scalar (non-list) input branch.
* ``format_for_gate_report``: registry-lookup exception is swallowed
  (renders default placeholder rather than crashing the report).
"""
from __future__ import annotations

import pytest


def test_is_weak_match_handles_non_numeric_score() -> None:
    """A ``_final_score`` that won't coerce to float must NOT raise; the
    guard treats it as 'cannot confirm weak' → returns False.
    """
    from scripts.core.gate_rag_bridge import _is_weak_match

    concern = {
        "concern_id": "PR-BAD-SCORE-C01",
        "_final_score": "not-a-number",
        "_match_reasons": ["severity_fallback"],
    }
    assert _is_weak_match(concern) is False


def test_is_weak_match_coerces_string_reasons_to_list() -> None:
    """When ``_match_reasons`` is a bare string (legacy gates), the
    helper must coerce it to a one-element list and still classify by
    fallback markers — not raise.
    """
    from scripts.core.gate_rag_bridge import _is_weak_match

    concern = {
        "concern_id": "PR-STR-REASONS-C01",
        "_final_score": 0.01,  # below floor
        "_match_reasons": "severity_fallback",  # string, not list
    }
    assert _is_weak_match(concern) is True


def test_is_low_confidence_handles_non_numeric_dense_score() -> None:
    """Non-numeric ``_dense_score`` must return ``(False, 0.0)`` rather
    than raise — the bridge contract is 'can't signal off-scope
    without a usable cosine'.
    """
    from scripts.core.gate_rag_bridge import _is_low_confidence

    concern = {
        "concern_id": "PR-BAD-DENSE-C01",
        "_dense_score": "garbage",
    }
    flag, dense = _is_low_confidence(concern)
    assert flag is False
    assert dense == 0.0


def test_synthesize_query_falls_back_to_gate_name_when_empty() -> None:
    """The contract in ``rag_context_for_failure`` allows a bare gate
    filter with no codes and no hint. ``_synthesize_query`` must
    return the (de-snake-cased) gate name so hybrid_rank doesn't get
    an empty query.
    """
    from scripts.core.gate_rag_bridge import _synthesize_query

    out = _synthesize_query([], None, gate_name="leakage_gate")
    assert out == "leakage gate"


def test_synthesize_query_returns_empty_when_no_gate_either() -> None:
    """When EVERYTHING is empty (no codes, no hint, no gate), the
    function returns ``""`` — callers must surface this as a no-op
    rather than embedding model gibberish.
    """
    from scripts.core.gate_rag_bridge import _synthesize_query

    assert _synthesize_query([], None, gate_name=None) == ""
    assert _synthesize_query([], "", gate_name="") == ""


def test_format_reasons_handles_scalar_input() -> None:
    """Non-list, non-tuple reasons (e.g. a stray string from a legacy
    code path) must be stringified rather than joined — exercises the
    fall-through branch.
    """
    from scripts.core.gate_rag_bridge import _format_reasons

    assert _format_reasons("solo_reason") == "solo_reason"
    assert _format_reasons(42) == "42"
    assert _format_reasons(None) == "-"
    assert _format_reasons([]) == "-"


def test_format_for_gate_report_survives_registry_lookup_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``_gate_registry.get_gate_spec`` raises (transient import
    issue, registry corruption), the bridge must fall through to the
    default 'no concerns' placeholder rather than propagate the
    exception into report rendering.

    Exercises the bare ``except Exception:`` swallow at lines 443-444.
    """
    import sys
    import types

    from scripts.core import gate_rag_bridge

    # Inject a fake _gate_registry that raises on lookup.
    fake_mod = types.ModuleType("scripts.core._gate_registry")

    def _boom(_name: str):  # noqa: ANN202 — fixture
        raise RuntimeError("simulated registry corruption")

    fake_mod.get_gate_spec = _boom
    monkeypatch.setitem(sys.modules, "scripts.core._gate_registry", fake_mod)

    # Empty concerns + gate_name with a broken registry: must NOT raise.
    md = gate_rag_bridge.format_for_gate_report([], gate_name="leakage_gate")
    assert "No related peer-review concerns retrieved" in md
