"""Unit tests for the NCPR v1 matcher (W22-X1).

All tests are offline and deterministic: the semantic step is exercised
via a hand-rolled ``embed_fn`` that returns fixed vectors keyed on
known phrases.
"""
from __future__ import annotations

import numpy as np
import pytest

from rag.evals.ncpr_matcher import (
    SEMANTIC_THRESHOLD,
    match_all,
    match_flag_to_concern,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


def _flag(code="x_gate_code", severity="HIGH", category="evaluation",
          evidence_text=""):
    return {
        "code": code,
        "severity": severity,
        "category": category,
        "evidence_text": evidence_text,
    }


def _concern(concern_id="c1", concern_text="", severity="HIGH",
             category="evaluation", mlgg_gates=None):
    return {
        "concern_id": concern_id,
        "concern_text": concern_text,
        "severity": severity,
        "category": category,
        "mlgg_gates": mlgg_gates or [],
    }


def _embed_factory(table: dict[str, list[float]]):
    """Return an embed_fn that looks up normalized text -> fixed vector.

    Unknown text gets an orthogonal vector so cosine drops to ~0.
    """
    def embed_fn(text: str) -> np.ndarray:
        # Matcher pre-normalizes (lowercase + collapse ws), so the lookup
        # table must use those normalized forms as keys.
        return np.asarray(table.get(text, [0.0, 0.0, 1.0]), dtype=float)
    return embed_fn


# ────────────────────────────────────────────────────────────────────────
# Single-pair matcher
# ────────────────────────────────────────────────────────────────────────


def test_exact_code_match_positive():
    flag = _flag(code="clinical_metrics_gate")
    concern = _concern(mlgg_gates=["clinical_metrics_gate"])
    assert match_flag_to_concern(flag, concern) == ("exact_code", 1.0)


def test_code_prefix_match_positive():
    """Reviewer tagged ``clinical_metrics_gate``; MLGG emitted a more
    specific sub-code. Should match via code_prefix (gate suffix
    stripped before prefix comparison)."""
    flag = _flag(code="clinical_metrics_ppv_too_low")
    concern = _concern(mlgg_gates=["clinical_metrics_gate"])
    match_type, score = match_flag_to_concern(flag, concern)
    assert match_type == "code_prefix"
    assert score == 1.0


def test_code_prefix_does_not_overreach():
    """``clinical_metrics`` must not match an unrelated code that merely
    shares an initial substring without a ``_`` boundary."""
    flag = _flag(code="clinical_metricsfoo")  # no underscore boundary
    concern = _concern(mlgg_gates=["clinical_metrics_gate"])
    # Falls through code/prefix; categories also disagree by default? They
    # match (both "evaluation"), so we expect category, not code_prefix.
    match_type, _ = match_flag_to_concern(flag, concern)
    assert match_type == "category"


def test_semantic_match_above_threshold():
    """Cosine 0.85 between flag.evidence_text and concern.concern_text
    using mocked embeddings -> semantic match."""
    flag = _flag(
        code="unrelated_code",
        category="design",  # different from concern.category
        evidence_text="ROC AUC reported without confidence interval",
    )
    concern = _concern(
        category="evaluation",
        concern_text="discrimination metric lacks 95 percent CI",
    )
    # Build two unit-ish vectors whose cosine ≈ 0.85.
    # cos(θ) = 0.85 → take v1=[1,0], v2=[0.85, sqrt(1-0.85²)] ≈ [0.85, 0.527]
    table = {
        "roc auc reported without confidence interval": [1.0, 0.0],
        "discrimination metric lacks 95 percent ci": [0.85, 0.5268],
    }
    embed_fn = _embed_factory(table)
    match_type, score = match_flag_to_concern(flag, concern, embed_fn=embed_fn)
    assert match_type == "semantic"
    assert 0.84 <= score <= 0.86
    assert score >= SEMANTIC_THRESHOLD


def test_semantic_below_threshold_falls_through():
    """Cosine 0.60 -> below 0.70 threshold -> no semantic; fall through
    to category match (which also disagrees here) -> none."""
    flag = _flag(
        code="unrelated_code",
        category="design",
        evidence_text="ROC AUC reported without confidence interval",
    )
    concern = _concern(
        category="evaluation",
        concern_text="discrimination metric lacks 95 percent CI",
    )
    # cos = 0.60: v1=[1,0], v2=[0.6, sqrt(1-0.36)] ≈ [0.6, 0.8]
    table = {
        "roc auc reported without confidence interval": [1.0, 0.0],
        "discrimination metric lacks 95 percent ci": [0.6, 0.8],
    }
    embed_fn = _embed_factory(table)
    match_type, _ = match_flag_to_concern(flag, concern, embed_fn=embed_fn)
    assert match_type == "none"


def test_category_fallback_positive():
    """No code overlap, no embed_fn, but categories agree -> category."""
    flag = _flag(code="aaa", category="evaluation")
    concern = _concern(category="evaluation", mlgg_gates=["bbb_gate"])
    match_type, score = match_flag_to_concern(flag, concern)
    assert match_type == "category"
    assert score == 0.5


def test_exact_beats_semantic_precedence():
    """When both exact and semantic would fire, exact_code wins."""
    flag = _flag(
        code="clinical_metrics_gate",
        evidence_text="some text",
    )
    concern = _concern(
        concern_text="some text",
        mlgg_gates=["clinical_metrics_gate"],
    )
    # Even with a high-cosine embed_fn, exact must win.
    embed_fn = _embed_factory({"some text": [1.0, 0.0]})
    match_type, _ = match_flag_to_concern(flag, concern, embed_fn=embed_fn)
    assert match_type == "exact_code"


def test_no_embed_fn_skips_semantic():
    flag = _flag(
        code="aaa",
        category="design",
        evidence_text="some descriptive text",
    )
    concern = _concern(
        category="evaluation",
        concern_text="some descriptive text",
    )
    # Identical text would yield cosine 1.0 if embedded, but with no
    # embed_fn we must skip type 3 and fall through; categories disagree
    # so result is none.
    match_type, _ = match_flag_to_concern(flag, concern, embed_fn=None)
    assert match_type == "none"


# ────────────────────────────────────────────────────────────────────────
# Bulk matcher
# ────────────────────────────────────────────────────────────────────────


def test_match_all_empty_flags():
    concerns = [_concern("c1"), _concern("c2")]
    result = match_all([], concerns)
    assert result["matched_pairs"] == []
    assert result["unmatched_flags"] == []
    assert result["unmatched_concerns"] == [0, 1]


def test_match_all_empty_concerns():
    flags = [_flag(code="a_gate"), _flag(code="b_gate")]
    result = match_all(flags, [])
    assert result["matched_pairs"] == []
    assert result["unmatched_flags"] == [0, 1]
    assert result["unmatched_concerns"] == []


def test_match_all_both_empty():
    result = match_all([], [])
    assert result == {
        "matched_pairs": [],
        "unmatched_flags": [],
        "unmatched_concerns": [],
    }


def test_match_all_dedup_three_flags_one_concern():
    """Three flags all target the same concern via exact_code.

    Per the design choice (flag-to-1-concern, concern-keeps-best-flag):
    one flag wins the concern, the other two are reported as unmatched.
    """
    flags = [
        _flag(code="clinical_metrics_gate", evidence_text="flag a"),
        _flag(code="clinical_metrics_gate", evidence_text="flag b"),
        _flag(code="clinical_metrics_gate", evidence_text="flag c"),
    ]
    concerns = [_concern("c1", mlgg_gates=["clinical_metrics_gate"])]
    result = match_all(flags, concerns)
    assert len(result["matched_pairs"]) == 1
    assert result["matched_pairs"][0]["concern_idx"] == 0
    assert result["matched_pairs"][0]["type"] == "exact_code"
    assert len(result["unmatched_flags"]) == 2
    assert result["unmatched_concerns"] == []


def test_match_all_precedence_across_concerns():
    """One flag is a candidate for two concerns: exact_code for one and
    category for the other. The flag must pick the exact_code concern."""
    flag = _flag(code="leakage_gate", category="evaluation",
                 evidence_text="leak in train/test split")
    concerns = [
        _concern("c_weak", category="evaluation", mlgg_gates=[]),
        _concern("c_strong", category="design", mlgg_gates=["leakage_gate"]),
    ]
    result = match_all([flag], concerns)
    assert len(result["matched_pairs"]) == 1
    pair = result["matched_pairs"][0]
    assert pair["concern_idx"] == 1
    assert pair["type"] == "exact_code"
    # c_weak was not picked
    assert 0 in result["unmatched_concerns"]


def test_match_all_two_flags_two_concerns_clean():
    flags = [
        _flag(code="leakage_gate"),
        _flag(code="calibration_gate"),
    ]
    concerns = [
        _concern("c1", mlgg_gates=["leakage_gate"]),
        _concern("c2", mlgg_gates=["calibration_gate"]),
    ]
    result = match_all(flags, concerns)
    assert len(result["matched_pairs"]) == 2
    assert result["unmatched_flags"] == []
    assert result["unmatched_concerns"] == []
    # ordering on concern_idx
    assert [p["concern_idx"] for p in result["matched_pairs"]] == [0, 1]


def test_empty_evidence_text_skips_semantic_only():
    """Flag with empty evidence_text — types 1 and 2 still apply."""
    flag = _flag(code="leakage_gate", evidence_text="")
    concern = _concern(mlgg_gates=["leakage_gate"],
                       concern_text="something descriptive")
    match_type, _ = match_flag_to_concern(flag, concern,
                                          embed_fn=_embed_factory({}))
    assert match_type == "exact_code"


def test_empty_mlgg_gates_skips_exact_and_prefix():
    """Concern with empty mlgg_gates — type 3 may still fire."""
    flag = _flag(code="x_gate", evidence_text="same text", category="design")
    concern = _concern(concern_text="same text", category="evaluation",
                       mlgg_gates=[])
    embed_fn = _embed_factory({"same text": [1.0, 0.0]})  # cos(v,v)=1.0
    match_type, score = match_flag_to_concern(flag, concern, embed_fn=embed_fn)
    assert match_type == "semantic"
    assert score == pytest.approx(1.0)
