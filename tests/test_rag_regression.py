"""Regression tests for RAG-layer ship-stopper bugs.

Each test corresponds to a documented bug from the 5-agent strict-eval:
  - test_no_circular_import_from_bridge                          (fixed: 251003b)
  - test_rag_context_for_failure_gate_only                       (fixed: 251003b)
  - test_top_k_above_50_returns_more                             (fixed: 830ce4a)
  - test_free_text_marks_bm25_inactive                           (fixed: 830ce4a)
  - test_format_for_rag_optional_gate                            (fixed: 830ce4a)
  - test_public_api_surface                                      (always)
  - test_all_33_gates_have_rag_coverage_or_are_rag_optional      (slow; E5+G1)

If an xfail test starts passing, that's the fix landing — remove the
marker.
"""

import subprocess
import sys

import pytest

# Module-level skip if sentence_transformers missing (matches existing
# test_rag_components.py convention).
pytest.importorskip("sentence_transformers")


def test_no_circular_import_from_bridge() -> None:
    """Regression: importing rag_context_for_failure crashed pre-251003b
    due to scripts/rag/__init__.py re-exporting it (circular import)."""
    # Subprocess for fresh interpreter (no module cache).
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.core.gate_rag_bridge import rag_context_for_failure; print('ok')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"circular import regression: stderr={result.stderr}\n"
        f"stdout={result.stdout}"
    )
    assert "ok" in result.stdout


def test_rag_context_for_failure_gate_only() -> None:
    """Regression: rag_context_for_failure with empty failure_codes raised
    ValueError pre-251003b. Docstring promises gate-filter-only mode works."""
    from scripts.core.gate_rag_bridge import rag_context_for_failure

    results = rag_context_for_failure("leakage_gate", failure_codes=[], top_k=3)
    assert isinstance(results, list), f"expected list, got {type(results)}"
    # Don't assert len > 0 — gate may legitimately have 0 concerns in some configs.
    # The bug was an EXCEPTION; absence of exception is the regression check.


def test_top_k_above_50_returns_more() -> None:
    """E3 finding: top_k > 50 silently capped at DEFAULT_MAX_CANDIDATES_BEFORE_RERANK.

    Fixed by F1 (commit 830ce4a): dense_top_k = max(50, top_k).
    Hard regression — must never re-cap silently.
    """
    from scripts.rag import rag_query

    results = rag_query("calibration", top_k=200)
    assert len(results) > 50, (
        f"top_k uncap regression: asked for 200, got {len(results)}"
    )


def test_free_text_marks_bm25_inactive() -> None:
    """E2 finding: free-text path doesn't fire BM25, but doesn't tell the user.

    Fixed by F1 (commit 830ce4a): results carry a _match_reasons sentinel
    when BM25 is skipped due to missing gate/codes. Hard regression.
    """
    from scripts.rag import rag_query

    results = rag_query("calibration", top_k=5)
    assert results, "expected at least one result for 'calibration'"
    reasons = results[0].get("_match_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    assert any(
        "bm25" in r.lower() and "inactive" in r.lower() for r in reasons
    ), f"expected bm25_inactive marker, got reasons={reasons!r}"


def test_format_for_rag_optional_gate() -> None:
    """E5 finding: format_for_gate_report renders 'no concerns' placeholder
    even for infra gates with no peer-review domain.

    Fixed by F2 (commit 830ce4a, merged with F1): GateSpec.rag_optional=True
    on the 4 infra gates suppresses the placeholder. Hard regression.
    """
    from scripts.core.gate_rag_bridge import format_for_gate_report

    out = format_for_gate_report([], gate_name="manifest_lock")
    assert out == "", f"expected empty string for rag_optional gate, got {out!r}"


def test_public_api_surface() -> None:
    """Smoke: documented public imports work."""
    code = (
        "from scripts.rag import rag_query\n"
        "from scripts.core.gate_rag_bridge import "
        "rag_context_for_failure, format_for_gate_report\n"
        "print('all imports ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"surface broken: stderr={result.stderr}"
    assert "all imports ok" in result.stdout


@pytest.mark.slow
def test_all_33_gates_have_rag_coverage_or_are_rag_optional() -> None:
    """E5 strict-eval contract: every gate either returns >=1 concern
    from ``rag_context_for_failure`` or is flagged ``rag_optional=True``
    in the registry. No silent empty gates.

    Slow marker: this calls the RAG bridge once per gate (33 hybrid
    rank calls), each warming the dense-retrieval model on first use.
    Excluded from the default ``-m "not slow"`` ci-unit run; included
    in nightly / on-demand sweeps.
    """
    # _gate_registry has no public ``all_gates()`` / ``iter_gates()``
    # helper — the canonical enumeration surface is the module-level
    # ``GATE_REGISTRY: Dict[str, GateSpec]`` (every other internal
    # accessor in the file, e.g. ``topological_sort``, iterates the
    # same dict). Pulling specs directly from ``GATE_REGISTRY.values()``
    # is the documented inference; if a public list-style API ever
    # lands, swap the import below.
    from scripts.core._gate_registry import GATE_REGISTRY
    from scripts.core.gate_rag_bridge import rag_context_for_failure

    specs = list(GATE_REGISTRY.values())
    assert len(specs) == 33, (
        f"expected 33 gates, registry has {len(specs)} — coverage "
        f"contract is anchored to the 33-gate count documented across "
        f"14 markdown files + 4 test assertions; bump-or-justify."
    )

    empty_but_not_optional: list[tuple[str, str]] = []
    for spec in specs:
        if getattr(spec, "rag_optional", False):
            continue  # honest empty by design (infra/meta gates)
        try:
            results = rag_context_for_failure(
                spec.name, failure_codes=[], top_k=5
            )
        except Exception as exc:  # noqa: BLE001 — surface any bridge crash
            empty_but_not_optional.append(
                (spec.name, f"raised {type(exc).__name__}: {exc}")
            )
            continue
        if len(results) == 0:
            empty_but_not_optional.append((spec.name, "returned 0 concerns"))

    assert not empty_but_not_optional, (
        f"{len(empty_but_not_optional)} gate(s) have empty RAG coverage "
        f"but are not flagged rag_optional. Either add concerns to "
        f"references/case-studies/peer-review-kb.json (and tag them with "
        f"the gate name) or mark the gate rag_optional=True in "
        f"scripts/core/_gate_registry.py:\n  "
        + "\n  ".join(f"{n}: {r}" for n, r in empty_but_not_optional)
    )


def test_format_for_gate_report_hedges_weak_match_concerns() -> None:
    """H19 finding: weak-match concerns (low score + fallback-only reasons)
    should be marked in the markdown so synthesis-LLMs don't cite them
    as precedent."""
    from scripts.core.gate_rag_bridge import format_for_gate_report

    weak = {
        "concern_id": "PR-WEAK-C01",
        "concern_text": "Some loosely related concern",
        "severity": "MEDIUM",
        "_final_score": 0.02,
        "_match_reasons": ["severity_fallback"],
    }
    md = format_for_gate_report([weak], gate_name="leakage_gate")
    assert "weak match" in md.lower() or "do not cite" in md.lower(), (
        f"weak-match hedge missing from rendered markdown:\n{md}"
    )


def test_format_for_gate_report_does_not_hedge_strong_match() -> None:
    """A genuine strong-match concern should NOT carry the weak-match hedge."""
    from scripts.core.gate_rag_bridge import format_for_gate_report

    strong = {
        "concern_id": "PR-STRONG-C01",
        "concern_text": "A clearly relevant concern",
        "severity": "HIGH",
        "_final_score": 0.55,
        "_match_reasons": ["dense_top_1"],
    }
    md = format_for_gate_report([strong], gate_name="leakage_gate")
    assert "weak match" not in md.lower() and "do not cite" not in md.lower(), (
        f"strong concern incorrectly hedged:\n{md}"
    )


def test_low_confidence_hedge_fires_on_off_mlgg_scope_queries() -> None:
    """Wave 4 finding: BGE-small gives plausible-looking dense cosine
    (0.68–0.73) for queries fully off MLGG's modality scope (omics,
    imaging, NLP, survival). The fused ``_final_score`` (0.49–0.53)
    sits well above the strong-hedge floor of 0.05, so the legacy
    weak-match hedge does NOT fire. The new low-confidence hedge —
    keyed on raw ``_dense_score`` < 0.72 — must trigger so synthesis-
    LLMs see an off-scope warning before treating the row as
    peer-review precedent.

    Picks a query from W4's hunt that is known to score in the off-
    scope band but has BGE matches in the KB (so retrieval is non-
    empty).  Test skips if the index hasn't been built locally.
    """
    from scripts.core.gate_rag_bridge import format_for_gate_report
    from scripts.rag import rag_query

    results = rag_query(
        "single-cell RNAseq batch effect correction", top_k=3
    )
    if not results:
        pytest.skip("query returned no results — index not built locally")

    top_dense = results[0].get("_dense_score")
    if top_dense is None or top_dense >= 0.72:
        # Index/embedding model changed since W4 measurement; the off-
        # scope hedge contract is unchanged but this particular query
        # no longer exercises it. Skip rather than silently pass.
        pytest.skip(
            f"top dense_score {top_dense!r} no longer in off-scope band; "
            f"refresh the off-scope query from a current W4 sweep"
        )

    md = format_for_gate_report(results, gate_name="leakage_gate")
    assert "low semantic confidence" in md.lower(), (
        f"off-scope query (dense top-1={top_dense:.3f}) but no low-"
        f"confidence hedge in markdown:\n{md}"
    )


def test_low_confidence_hedge_skips_strong_in_scope_matches() -> None:
    """Inverse of the off-scope test: a concern with dense_score above
    the floor must NOT carry the low-confidence hedge.  Guards against
    a future bump to the floor accidentally hedging legitimate hits.
    """
    from scripts.core.gate_rag_bridge import format_for_gate_report

    strong = {
        "concern_id": "PR-IN-SCOPE-C01",
        "concern_text": "A clearly relevant in-scope concern",
        "severity": "HIGH",
        "_final_score": 0.62,
        "_dense_score": 0.84,  # well above 0.72 floor
        "_match_reasons": ["dense top-1 score=0.84"],
    }
    md = format_for_gate_report([strong], gate_name="leakage_gate")
    assert "low semantic confidence" not in md.lower(), (
        f"in-scope strong match incorrectly carries low-confidence "
        f"hedge:\n{md}"
    )


def test_low_confidence_hedge_independent_of_weak_match_hedge() -> None:
    """Both hedges can fire on the same concern: a fallback-padded row
    with a low dense score gets BOTH lines. Test the orthogonality so
    a future refactor doesn't collapse them into one mutually-exclusive
    code path.
    """
    from scripts.core.gate_rag_bridge import format_for_gate_report

    both = {
        "concern_id": "PR-BOTH-C01",
        "concern_text": "Padding row with low semantic similarity",
        "severity": "MEDIUM",
        "_final_score": 0.02,  # below 0.05 weak-match floor
        "_dense_score": 0.30,  # below 0.72 low-confidence floor
        "_match_reasons": ["severity_fallback"],
    }
    md = format_for_gate_report([both], gate_name="leakage_gate")
    md_lower = md.lower()
    assert "weak match" in md_lower or "do not cite" in md_lower, (
        f"strong weak-match hedge missing:\n{md}"
    )
    assert "low semantic confidence" in md_lower, (
        f"low-confidence hedge missing:\n{md}"
    )


def test_format_for_gate_report_marks_same_paper_concerns() -> None:
    """H19 W5: when 2+ concerns share paper_id, each should carry a
    visual marker noting siblings — prevents LLM-side conflation."""
    from scripts.core.gate_rag_bridge import format_for_gate_report

    concerns = [
        {
            "concern_id": "PR-X-C01",
            "paper_id": "PR-X",
            "concern_text": "concern 1",
            "severity": "HIGH",
        },
        {
            "concern_id": "PR-X-C02",
            "paper_id": "PR-X",
            "concern_text": "concern 2",
            "severity": "HIGH",
        },
        {
            "concern_id": "PR-Y-C03",
            "paper_id": "PR-Y",
            "concern_text": "concern 3",
            "severity": "MEDIUM",
        },
    ]
    md = format_for_gate_report(concerns, gate_name="leakage_gate")
    # Both PR-X concerns should reference their sibling
    assert (
        "same paper" in md.lower()
        or "sibling" in md.lower()
        or "independent" in md.lower()
    ), f"same-paper marker missing:\n{md}"
    # PR-Y unique — should NOT have the marker
    pr_y_section = md.split("PR-Y-C03")[1] if "PR-Y-C03" in md else ""
    assert "same paper" not in pr_y_section.lower(), (
        f"PR-Y-C03 incorrectly marked as same-paper:\n{pr_y_section}"
    )
