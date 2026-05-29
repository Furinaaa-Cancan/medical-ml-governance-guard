"""W14 R2 self-review follow-up: unit tests for ``curated_precedent_for``.

The W14 audit B band-aid (commit c8e651c) shipped 152 lines of fallback
logic in ``scripts/core/gate_rag_bridge.py`` with NO new tests. The
existing ``test_gate_rag_bridge_defensive.py`` predates that code and
cannot validate its behaviour. This module closes that gap.

rag-path-truth-fixes: the curated-precedent logic was PROMOTED from the
dead bridge into the torch-free ``scripts/rag/_enrich.py`` (wired into the
offline path ``scripts/rag/query.py``). The public name is now
``curated_precedent_for``; these tests import it aliased to the historical
``_curated_precedent_for`` so behaviour + assertions stay verbatim — only
the definition site moved.

Specifically tested:

* Code-based resolution: (MLGG-P01, split_protocol_gate) returns the
  canonical CRITICAL curated record.
* Code-based resolution: (MLGG-P01, feature_engineering_audit_gate)
  also resolves (same record, different gate key).
* P04 sister-rule resolution: (MLGG-P04, split_protocol_gate) shares
  the same curated record via the alias keys.
* Lexical free-text trigger: query containing both an op-token and an
  order-token returns the canonical record even without rule codes.
* Lexical trigger requires BOTH tokens: op-only or order-only returns
  None.
* MLGG_RAG_DISABLE_CURATED=1 escape hatch: env-var disables the entire
  path so regression eval can observe raw ranker output.
* Off-target gate / code: (MLGG-P01, sample_size_gate) returns None
  (the curated map is scoped, not a blanket override).
* Return value is a fresh dict, not a reference to the module-level
  template (so callers can mutate without polluting the source-of-truth).
"""
from __future__ import annotations


import pytest


def test_curated_resolves_p01_for_split_protocol_gate() -> None:
    """Primary trigger: (MLGG-P01, split_protocol_gate) returns the
    CRITICAL fit-before-split precedent."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=["MLGG-P01"],
        query="",
    )
    assert out is not None
    assert out["concern_id"] == "MLGG-CURATED-P01-fit_before_split"
    assert out["severity"] == "CRITICAL"
    assert out["_synthetic_curated"] is True
    assert out["_match_reasons"] == ["curated_fallback:MLGG-P01"]


def test_curated_resolves_p01_for_feature_engineering_audit_gate() -> None:
    """Sibling gate: feature_engineering_audit_gate also catches P01."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="feature_engineering_audit_gate",
        failure_codes=["MLGG-P01"],
        query="",
    )
    assert out is not None
    assert out["concern_id"] == "MLGG-CURATED-P01-fit_before_split"


def test_curated_resolves_p04_via_alias() -> None:
    """P04 (imputation-before-split) shares the P01 precedent record."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=["MLGG-P04"],
        query="",
    )
    assert out is not None
    assert out["concern_id"] == "MLGG-CURATED-P01-fit_before_split"


def test_curated_lexical_trigger_op_plus_order() -> None:
    """L27-style free-text query (op-token + order-token) → curated record
    even without an explicit rule code."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=[],
        query="standard scaler normalization fit on full dataset before split",
    )
    assert out is not None
    assert out["concern_id"] == "MLGG-CURATED-P01-fit_before_split"
    assert out["_synthetic_curated"] is True


def test_curated_lexical_requires_both_tokens_op_only() -> None:
    """Op-token alone (e.g. 'scaler') without an order-token returns None."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=[],
        query="how should I tune the standard scaler?",
    )
    assert out is None


def test_curated_lexical_requires_both_tokens_order_only() -> None:
    """Order-token alone (e.g. 'before split') without an op-token returns None."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=[],
        query="apply cohort filters before split",
    )
    assert out is None


def test_curated_disabled_by_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """MLGG_RAG_DISABLE_CURATED=1 is the regression-eval escape hatch:
    even a known-trigger input returns None when the var is set."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    monkeypatch.setenv("MLGG_RAG_DISABLE_CURATED", "1")
    out = _curated_precedent_for(
        gate_name="split_protocol_gate",
        failure_codes=["MLGG-P01"],
        query="",
    )
    assert out is None


def test_curated_no_match_for_unrelated_gate() -> None:
    """Curated map is scoped, not a blanket override. (MLGG-P01,
    sample_size_gate) returns None — the P01 precedent is tagged for
    split_protocol_gate / feature_engineering_audit_gate only."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    out = _curated_precedent_for(
        gate_name="sample_size_gate",
        failure_codes=["MLGG-P01"],
        query="",
    )
    assert out is None


def test_curated_returns_fresh_dict_not_reference() -> None:
    """Caller must be able to mutate the returned record without
    polluting the module-level template. _CURATED_PRECEDENT_BY_KEY's
    dict-comprehension copy guards this."""
    from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for

    a = _curated_precedent_for("split_protocol_gate", ["MLGG-P01"], "")
    b = _curated_precedent_for("split_protocol_gate", ["MLGG-P01"], "")
    assert a is not b, (
        "Each call must return an independent dict so caller mutation "
        "doesn't leak into the source-of-truth template."
    )
    a["concern_text"] = "MUTATED"
    assert b["concern_text"] != "MUTATED"
