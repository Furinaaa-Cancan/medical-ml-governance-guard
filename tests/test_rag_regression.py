"""Regression tests for RAG-layer ship-stopper bugs.

Each test corresponds to a documented bug from the 5-agent strict-eval:
  - test_no_circular_import_from_bridge       (fixed: 251003b)
  - test_rag_context_for_failure_gate_only    (fixed: 251003b)
  - test_top_k_above_50_returns_more          (awaiting F1)
  - test_free_text_marks_bm25_inactive        (awaiting F1)
  - test_format_for_rag_optional_gate         (awaiting F2)
  - test_public_api_surface                   (always)

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
