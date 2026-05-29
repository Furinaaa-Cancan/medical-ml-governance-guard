"""W7-P8 follow-up: focused unit tests for defensive branches that were
previously uncovered.

rag-path-truth-fixes update: the orphan value in
``scripts/core/gate_rag_bridge.py`` was promoted into the torch-free
``scripts/rag/_enrich.py`` (wired into the offline path
``scripts/rag/query.py``), and the dead markdown-render surface was deleted.
This file was repointed accordingly:

Surviving (repointed to ``scripts.rag._enrich.synthesize_query``):
* ``synthesize_query``: gate-name-only fallback when both failure codes
  and query hint are empty; empty-everything returns ``""``.

Removed (tested now-deleted dead render code, no offline equivalent):
* ``_is_weak_match`` (non-numeric score / string-reason coercion),
* ``_is_low_confidence`` (non-numeric dense score),
* ``_format_reasons`` (scalar input branch),
* ``format_for_gate_report`` registry-lookup exception swallow.
These only produced per-row / per-block hedge lines for the deleted
markdown renderer; with no offline consumer the malformed-input guards
defend nothing, so there is no surviving intent to preserve.
"""
from __future__ import annotations


# REMOVED: test_is_weak_match_handles_non_numeric_score,
# test_is_weak_match_coerces_string_reasons_to_list,
# test_is_low_confidence_handles_non_numeric_dense_score.
# _is_weak_match / _is_low_confidence only produced per-row hedge lines for
# the deleted markdown renderer; no offline consumer, so the malformed-input
# guards defend nothing. No surviving intent.


def test_synthesize_query_falls_back_to_gate_name_when_empty() -> None:
    """A bare gate filter with no codes and no hint must still yield a
    non-empty query: ``synthesize_query`` returns the (de-snake-cased)
    gate name so hybrid_rank doesn't get an empty query.
    """
    from scripts.rag._enrich import synthesize_query

    out = synthesize_query([], None, gate_name="leakage_gate")
    assert out == "leakage gate"


def test_synthesize_query_returns_empty_when_no_gate_either() -> None:
    """When EVERYTHING is empty (no codes, no hint, no gate), the
    function returns ``""`` — callers must surface this as a no-op
    rather than embedding model gibberish.
    """
    from scripts.rag._enrich import synthesize_query

    assert synthesize_query([], None, gate_name=None) == ""
    assert synthesize_query([], "", gate_name="") == ""


# REMOVED: test_format_reasons_handles_scalar_input and
# test_format_for_gate_report_survives_registry_lookup_exception.
# _format_reasons and the rag_optional registry-guard lived entirely inside
# the deleted format_for_gate_report renderer. The "honest silence for
# rag_optional gates" intent is moot once nothing renders gate markdown.
