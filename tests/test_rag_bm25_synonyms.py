"""Tests for BM25 tokenization + TAG_SYNONYMS coverage (H1 fixes for G8 finding).

Background (G8 / E1 Q4 diagnostic):

The BM25 path in ``scripts/rag/retrieval/bm25.py`` had two silent
class-of-failures bugs that together disconnected the documented
public interface (CLAUDE.md "不可协商规则" rule codes) from the
retrieval layer:

  1. ``_issue_code_keywords`` filtered tokens shorter than 3
     characters, which erased the ``ci`` token from gate-emitted codes
     like ``missing_ci`` and ``ci_matrix_not_passed``. This also
     erased ``r2``, ``hr``, ``or``, ``df``, ``ml``, ``ai``.
  2. The CLAUDE.md canonical rule codes (``MLGG-S01`` … ``MLGG-E02``)
     had no entries in ``TAG_SYNONYMS``, so passing them to
     ``retrieve_for_failure`` tokenized to noise (``mlgg``, ``e01``,
     …) and degenerated to severity-only fallback.

These tests pin both fixes in place.
"""

from __future__ import annotations

import pytest

# Module-level skip if KB or imports break (matches convention used
# elsewhere in the rag test suite).
pytest.importorskip("sentence_transformers")

from scripts.rag.retrieval.bm25 import (  # noqa: E402
    TAG_SYNONYMS,
    _issue_code_keywords,
    retrieve_for_failure,
)


# ─── Bug 1: short-token allow-list ────────────────────────────────


@pytest.mark.parametrize("short_token", ["ci", "r2", "ml", "ai", "df", "or", "hr"])
def test_short_token_preserved(short_token):
    """2-char clinical / stats abbreviations should survive tokenization.

    Without ``SHORT_TOKEN_ALLOWLIST`` the ``len(tok) >= 3`` filter would
    drop these, silently degrading BM25 ranking on every gate that emits
    them (ci_matrix_*, missing_ci_method, bootstrap_r2_*, hazard_ratio_*).
    """
    code = f"missing_{short_token}"
    tokens = _issue_code_keywords([code])
    assert short_token in tokens, (
        f"short token '{short_token}' was dropped from tokenization of "
        f"'{code}' (got {sorted(tokens)})"
    )


# ─── Bug 2: CLAUDE.md canonical rule codes ────────────────────────


@pytest.mark.parametrize(
    "canonical_code",
    [
        "MLGG-S01", "MLGG-P01", "MLGG-F01", "MLGG-F02",
        "MLGG-M01", "MLGG-E01", "MLGG-E02",
    ],
)
def test_canonical_rule_codes_in_synonyms(canonical_code):
    """CLAUDE.md canonical codes must be mappable to semantic tags.

    These are the public interface MLGG publishes in its
    "不可协商规则" table. If they are absent from ``TAG_SYNONYMS``,
    documented rule citations cannot reach the BM25 retrieval path.
    """
    assert canonical_code in TAG_SYNONYMS, (
        f"CLAUDE.md canonical rule code {canonical_code} missing from "
        f"TAG_SYNONYMS — BM25 will starve on this input."
    )


def test_ci_query_via_canonical_rule_codes():
    """E1 Q4 regression: querying with MLGG-E01 should surface CI concerns.

    Combined regression check: the canonical-code → synonym mapping
    must actually produce CI-related hits when fed through the public
    ``retrieve_for_failure`` entry point.
    """
    results = retrieve_for_failure(
        "evaluation_quality_gate",
        ["MLGG-E01", "MLGG-E02"],
        limit=10,
    )
    assert results, "expected hits for MLGG-E01/E02"
    ci_hit_count = sum(
        1 for r in results
        if "confidence interval" in r.get("concern_text", "").lower()
        or "95% ci" in r.get("concern_text", "").lower()
    )
    assert ci_hit_count >= 1, (
        f"expected at least 1 CI-related concern, got {ci_hit_count} out "
        f"of {len(results)}. _score range: "
        f"{[r.get('_score', 0) for r in results[:5]]}"
    )


# ─── Bug 3: ci-prefixed gate-code synonyms ────────────────────────


def test_ci_prefixed_gate_code_synonyms():
    """Gate-emitted ci-prefixed codes must map to confidence_interval.

    Codes verified via ``grep scripts/gates/``:
      - missing_ci, missing_ci_method
      - ci_matrix_not_passed
      - insufficient_ci_resamples
    """
    for code in [
        "missing_ci",
        "ci_matrix_not_passed",
        "insufficient_ci_resamples",
    ]:
        assert code in TAG_SYNONYMS, (
            f"gate-emitted code {code!r} missing from TAG_SYNONYMS"
        )
        synonyms = TAG_SYNONYMS[code]
        assert any("confidence" in s or "ci" in s for s in synonyms), (
            f"{code} synonyms {synonyms} should include CI semantics"
        )
