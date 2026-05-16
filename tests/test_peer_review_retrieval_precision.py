"""Regression tests for the 2026-04-17 RAG retrieval precision fix.

Covers two bugs:

1. Warning-only gates (strict-mode-upgrade pattern) previously got 0
   peer_review_context. `_gate_framework.build_report_envelope` now
   triggers retrieval for both failures AND warnings.

2. `retrieve_by_gate(gate_name)` filtered by mlgg_gates then sorted by
   severity, giving ~20% precision — CRITICAL-severity topically-unrelated
   concerns bubbled above lower-severity on-target ones.
   `retrieve_for_failure(gate_name, issue_codes)` re-ranks by issue-code
   keyword overlap with concern tags/text.

These tests lock in behavior so the regression on failure-specific
relevance doesn't silently return.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "core"))

from _peer_review_retrieval import (  # noqa: E402
    _issue_code_keywords,
    retrieve_by_gate,
    retrieve_for_failure,
)


def test_issue_code_keywords_extract_meaningful_tokens() -> None:
    codes = ["clinical_floor_sensitivity_not_met", "clinical_floor_ppv_not_met"]
    kws = _issue_code_keywords(codes)
    # 'clinical', 'floor', 'sensitivity', 'ppv' expected; 'not', 'met'
    # filtered as stopwords.
    assert kws == {"clinical", "floor", "sensitivity", "ppv"}


def test_issue_code_keywords_filters_short_and_stopwords() -> None:
    codes = ["baseline_improvement_insufficient", "cv_strategy_required"]
    kws = _issue_code_keywords(codes)
    assert "baseline" in kws
    assert "improvement" in kws
    assert "strategy" in kws
    # 'cv' is 2 chars → dropped; 'required' / 'insufficient' are stopwords.
    assert "cv" not in kws
    assert "required" not in kws
    assert "insufficient" not in kws


def test_issue_code_keywords_handles_empty_and_malformed_input() -> None:
    assert _issue_code_keywords([]) == set()
    assert _issue_code_keywords([None, 42, ""]) == set()  # type: ignore[list-item]


def test_retrieve_for_failure_surfaces_failure_specific_concern() -> None:
    """Gate: clinical_metrics_gate. Failure: PPV-related.
    Expect at least one PPV-tagged concern in the top 5 results (there
    are 13 ppv-tagged concerns mapped to clinical_metrics_gate in the KB).
    """
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        ["clinical_floor_ppv_not_met", "clinical_floor_sensitivity_not_met"],
        limit=5,
    )
    assert results, "Retrieval returned no concerns for clinical_metrics_gate"
    # Semantic check: a "clinical_floor_*_not_met" failure should surface
    # a concern about that performance dimension. As KB grows, equivalent
    # tags ("clinical_metrics_gap", "metric_panel_incomplete",
    # "false_positive_rate_high", "clinically_critical_metric_missing",
    # "low_precision", "specificity_emphasis") may legitimately out-rank
    # the literal "ppv"/"sensitivity" tokens. Accept any equivalent.
    SEMANTIC_TOKENS = (
        "ppv", "sensitivity", "specificity", "low_precision",
        "clinically_critical_metric", "metric_panel_incomplete",
        "false_positive_rate", "clinical_metrics_gap",
        "very_major_error_rate",
    )
    def _has_clinical_metric_concern(c: dict) -> bool:
        tags = " ".join(str(t).lower() for t in (c.get("tags") or []))
        text = (c.get("concern_text") or "").lower()
        haystack = tags + " " + text[:500]
        return any(tok in haystack for tok in SEMANTIC_TOKENS)

    assert any(_has_clinical_metric_concern(c) for c in results), (
        "Expected at least one clinical-metric-tagged concern in top 5 after "
        "re-ranking. Got tags: "
        f"{[c.get('tags') for c in results]}"
    )


def test_retrieve_for_failure_surfaces_baseline_concern() -> None:
    """Gate: evaluation_quality_gate. Failure: baseline_improvement_insufficient.
    KB has 3 concerns mapped to evaluation_quality_gate with 'baseline'-related
    tags. Before the fix, retrieve_by_gate returned them only if CRITICAL.
    """
    results = retrieve_for_failure(
        "evaluation_quality_gate",
        ["baseline_improvement_insufficient"],
        limit=5,
    )
    assert results

    # Semantic check: a "baseline_improvement_insufficient" failure should
    # surface concerns about insufficient improvement over baseline. Either:
    #   (a) literal "baseline" token in tags or first 500 chars, OR
    #   (b) semantically equivalent — "marginal_improvement",
    #       "incremental_value", "improvement" critique tokens.
    # KB extraction-wave-2026-05-13 added many "marginal_improvement"-tagged
    # concerns that semantically address this failure more precisely than
    # the older literal "baseline" tags; the retrieval correctly prefers
    # them, so the test broadens to accept both forms.
    SEMANTIC_TOKENS = ("baseline", "marginal_improvement", "incremental_value",
                       "improvement_vs", "improvement_insufficient")
    def _has_baseline_or_improvement(c: dict) -> bool:
        tags = " ".join(str(t).lower() for t in (c.get("tags") or []))
        text = (c.get("concern_text") or "").lower()
        haystack = tags + " " + text[:500]
        return any(tok in haystack for tok in SEMANTIC_TOKENS)

    assert any(_has_baseline_or_improvement(c) for c in results), (
        f"No baseline-or-improvement-related concern in top 5 for "
        f"evaluation_quality_gate + baseline_improvement_insufficient. Tags: "
        f"{[c.get('tags') for c in results]}"
    )


def test_retrieve_for_failure_falls_back_when_no_keyword_match() -> None:
    """Even when keywords miss the KB entirely, retrieval should still return
    top-N severity-ranked concerns (never empty if the gate has any mapped
    concerns). Ensures we don't create a "silent zero-hit" regression."""
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        # Intentionally garbage codes that won't match any tag/text keyword.
        ["zzz_nonexistent_yyy_xxx"],
        limit=5,
    )
    assert len(results) > 0, "Fallback must not return empty when gate has mapped concerns"


def test_retrieve_for_failure_matches_old_retrieve_by_gate_when_codes_empty() -> None:
    """With no issue codes, behavior should match retrieve_by_gate (severity-only)."""
    old = retrieve_by_gate("clinical_metrics_gate", limit=5)
    new = retrieve_for_failure("clinical_metrics_gate", [], limit=5)
    assert [c.get("concern_id") for c in new] == [c.get("concern_id") for c in old]


# ─── 2026-04-18 precision hardening (P0 + P2) ──────────────────────────────


def test_retrieve_for_failure_no_substring_false_positive_on_short_tokens() -> None:
    """A 3-char keyword like 'idi' must NOT substring-match tags that happen
    to contain it as part of a longer word (`comorbidity`, `validity`,
    `bidirectional`). Before 2026-04-18 the scoring used `kw in tags_joined`
    which promoted `confounding_by_comorbidity` to top-1 for `idi_not_reported`
    — a semantically unrelated concern.
    """
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        ["idi_not_reported"],
        limit=5,
    )
    # The known false-positive PR-048-C01 (tag: confounding_by_comorbidity)
    # must no longer appear in the top 5 for `idi` alone.
    false_positive_ids = {"PR-048-C01"}
    returned_ids = {c.get("concern_id") for c in results}
    assert not (returned_ids & false_positive_ids), (
        f"Substring false-positive regressed: {returned_ids & false_positive_ids} "
        "appeared in top-5 for `idi_not_reported`. After tokenization, `idi` "
        "should only match concerns where 'idi' is an actual token, not a "
        "substring of 'comorbidity'/'validity'/'bidirectional'."
    )


def test_retrieve_for_failure_ppv_top_rank_is_actually_ppv_tagged() -> None:
    """Stronger than the existing 'at least one' assertion: for a PPV-specific
    failure, the top-1 result should be explicitly PPV-tagged. Before the
    substring fix, CRITICAL-severity non-PPV concerns could ride the
    3×tag-overlap signal via spurious matches."""
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        ["clinical_floor_ppv_not_met"],
        limit=5,
    )
    assert results
    top = results[0]
    top_tokens = set()
    for t in top.get("tags") or []:
        top_tokens |= {tok for tok in str(t).lower().replace("-", "_").split("_") if tok}
    assert "ppv" in top_tokens, (
        f"Top-1 concern for `clinical_floor_ppv_not_met` is "
        f"{top.get('concern_id')} with tags {top.get('tags')} — expected "
        "`ppv` as an actual token in tags."
    )


def test_gate_framework_prefers_failure_codes_over_warning_codes() -> None:
    """Reproduce the 2026-04-18 fix in build_report_envelope: when a gate has
    BOTH failures and warnings, the issue-code pool used for RAG re-ranking
    must contain only the failure codes. Otherwise warnings' keywords
    dilute precision when a gate emits many warnings + one failure.
    """
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts" / "core"))

    from _gate_framework import (  # noqa: E402
        GateIssue,
        Severity,
        build_report_envelope,
        register_remediations,
    )

    # Register remediations so GateIssue.code can be looked up.
    register_remediations({
        "clinical_floor_ppv_not_met": "Report PPV alongside sensitivity.",
        "baseline_improvement_insufficient": "Compare against a published baseline.",
    })

    failure = GateIssue(code="clinical_floor_ppv_not_met",
                       severity=Severity.CRITICAL,
                       message="PPV below clinical floor.")
    warnings = [
        GateIssue(code="baseline_improvement_insufficient",
                  severity=Severity.WARNING,
                  message="Weak baseline.")
        for _ in range(10)
    ]

    env = build_report_envelope(
        gate_name="clinical_metrics_gate",
        status="fail",
        strict_mode=False,
        failures=[failure],
        warnings=warnings,
    )
    peer = env.get("peer_review_context", [])
    assert peer, "peer_review_context should be populated"
    # Top result should reflect the PPV failure, not the baseline warnings.
    top = peer[0]
    top_tokens = set()
    for t in top.get("tags") or []:
        top_tokens |= {tok for tok in str(t).lower().replace("-", "_").split("_") if tok}
    assert "ppv" in top_tokens or "ppv" in (top.get("concern") or "").lower(), (
        f"Failure-first routing broken: with failure=PPV + 10 baseline warnings, "
        f"top result is {top.get('concern_id')} with tags {top.get('tags')} "
        "(expected PPV-relevant, not baseline-relevant)."
    )


def test_envelope_and_format_gate_peer_context_agree_on_ranking() -> None:
    """Interface-unification regression: the JSON envelope's
    `peer_review_context` and the terminal-print `format_gate_peer_context`
    must surface the same top concerns for the same (gate, issue_codes)
    pair. Before 2026-04-18, the terminal path used severity-only
    `retrieve_by_gate` while the envelope used `retrieve_for_failure`,
    so the two paths could disagree for the same gate failure."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts" / "core"))

    from _peer_review_retrieval import (  # noqa: E402
        format_gate_peer_context,
        retrieve_for_failure,
    )

    codes = ["clinical_floor_ppv_not_met"]
    envelope_results = retrieve_for_failure("clinical_metrics_gate", codes, limit=10)
    envelope_ids = [c.get("concern_id") for c in envelope_results][:3]

    # format_gate_peer_context renders a string; extract concern IDs from it.
    rendered = format_gate_peer_context("clinical_metrics_gate", issue_codes=codes)
    import re as _re
    rendered_ids = _re.findall(r"(PR-\d+-C\d+)", rendered)[:3]

    assert rendered_ids == envelope_ids, (
        f"format_gate_peer_context ({rendered_ids}) disagrees with the "
        f"envelope ranking ({envelope_ids}) for the same gate + issue codes. "
        "Both paths must route through retrieve_for_failure so reports and "
        "terminal output cite the same peer review evidence."
    )


def test_retrieve_for_failure_tags_results_with_retrieval_mode() -> None:
    """Every concern returned by retrieve_for_failure must carry a
    `_retrieval_mode` indicator so consumers can tell keyword matches
    apart from severity-only fallbacks. Without this, an audit reading
    `peer_review_context` cannot judge how strongly to rely on a cited
    concern."""
    kw_match = retrieve_for_failure(
        "clinical_metrics_gate",
        ["clinical_floor_ppv_not_met"],
        limit=5,
    )
    assert kw_match
    for c in kw_match:
        assert c.get("_retrieval_mode") == "keyword_match", (
            f"Expected keyword_match, got {c.get('_retrieval_mode')} "
            f"on {c.get('concern_id')}"
        )

    fb = retrieve_for_failure(
        "clinical_metrics_gate",
        ["xxqqzz_aaabbb_ccdd_ffgghh"],
        limit=5,
    )
    assert fb
    for c in fb:
        assert c.get("_retrieval_mode") == "severity_fallback"


def test_envelope_emits_peer_review_status() -> None:
    """build_report_envelope must expose an explicit peer_review_status
    alongside peer_review_context so a consumer can differentiate five
    cases: keyword_match / severity_fallback / no_mapped_concerns /
    kb_unavailable / skipped_no_issues."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts" / "core"))

    from _gate_framework import (  # noqa: E402
        GateIssue,
        Severity,
        build_report_envelope,
        register_remediations,
    )
    register_remediations({
        "clinical_floor_ppv_not_met": "Report PPV.",
        "xxqqzz_aaabbb_ccddee": "Diagnostic.",
        "any_code": "Diagnostic.",
    })

    env = build_report_envelope("clinical_metrics_gate", "pass", False, [], [])
    assert env["peer_review_status"] == "skipped_no_issues"
    assert env["peer_review_context"] == []

    failure = GateIssue("clinical_floor_ppv_not_met", Severity.CRITICAL, "msg")
    env = build_report_envelope(
        "clinical_metrics_gate", "fail", False, [failure], []
    )
    assert env["peer_review_status"] == "keyword_match"
    assert env["peer_review_context"]

    miss = GateIssue("xxqqzz_aaabbb_ccddee", Severity.CRITICAL, "msg")
    env = build_report_envelope(
        "clinical_metrics_gate", "fail", False, [miss], []
    )
    assert env["peer_review_status"] == "severity_fallback"
    assert env["peer_review_context"]

    # manifest_lock has no KB coverage — emits no_mapped_concerns.
    miss2 = GateIssue("any_code", Severity.CRITICAL, "msg")
    env = build_report_envelope(
        "manifest_lock", "fail", False, [miss2], []
    )
    assert env["peer_review_status"] == "no_mapped_concerns"
    assert env["peer_review_context"] == []


def test_envelope_retries_failure_plus_warning_when_stage1_falls_back() -> None:
    """2-stage retry contract: if failures-only retrieval lands in
    severity_fallback (no keyword match), augment with warning codes
    and retry. A vocabulary-poor failure should borrow signal from its
    warning codes — without letting warnings dominate when failures
    already match."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts" / "core"))

    from _gate_framework import (  # noqa: E402
        GateIssue,
        Severity,
        build_report_envelope,
        register_remediations,
    )
    register_remediations({
        "vague_fail": "Diagnostic.",
        "clinical_floor_ppv_not_met": "Report PPV.",
    })

    failure = GateIssue("vague_fail", Severity.CRITICAL, "msg")
    warning = GateIssue("clinical_floor_ppv_not_met", Severity.WARNING, "msg")
    env = build_report_envelope(
        "clinical_metrics_gate", "fail", False, [failure], [warning]
    )
    assert env["peer_review_status"] == "keyword_match", (
        f"2-stage retry didn't promote: status={env['peer_review_status']}"
    )
    top = env["peer_review_context"][0]
    top_tokens = set()
    for t in top.get("tags") or []:
        top_tokens |= {
            tok
            for tok in str(t).lower().replace("-", "_").split("_")
            if tok
        }
    assert "ppv" in top_tokens, (
        f"Retry top={top.get('concern_id')} not PPV-tagged; tags={top.get('tags')}"
    )


def test_retrieve_by_text_min_match_ratio_uses_ceil() -> None:
    """math.ceil floor: a 3-term query with ratio=0.4 must require ≥2 hits
    (67% ≥ 40%), not 1 hit (33% < 40%). The previous int() truncation
    silently admitted matches below the declared ratio floor."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts" / "core"))

    from _peer_review_retrieval import retrieve_by_text  # noqa: E402

    # A query with 3 unique terms; ratio 0.4 should demand ≥ ceil(1.2) = 2.
    results = retrieve_by_text(
        "calibration missing plot",
        limit=50,
        min_match_ratio=0.4,
    )
    for c in results:
        ratio = c.get("_match_ratio", 0)
        assert ratio >= 2 / 3 - 1e-9, (
            f"Concern {c.get('concern_id')} returned with match_ratio={ratio:.3f}, "
            "below the 2/3 floor enforced by math.ceil(3 * 0.4)."
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
