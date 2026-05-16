"""Manifest-driven TAG_SYNONYMS coverage (H12 / Wave-2 follow-up to H1).

Wave-1 H1 added 38 missing TAG_SYNONYMS entries for the BM25 retriever.
Wave-1 H2 noted that TAG_OVERLAYS substring matching will rot too.
H1/H2/H3 all flagged the same root cause: hand-maintained lookup tables
in ``scripts/rag/retrieval/bm25.py`` decay silently when a new gate code
ships without a paired synonym entry.

This test fixes the decay loop: every CLAUDE.md canonical rule code
plus every grep-harvested ci-prefixed gate failure code MUST have a
``TAG_SYNONYMS`` entry. Adding a new code in this curated public-
interface set without updating ``TAG_SYNONYMS`` will fail CI loudly,
with an error message pointing the change author at the right file.

Scope: the curated **public-interface subset** (23 codes — 7 MLGG-*
canonical rule codes + 16 ci_* family), not the full 748-code superset
harvested from ``scripts/gates/`` (see
``/tmp/H12_emitted_codes_audit.md``). Extending coverage to the full
superset is left for a future agent — it would create high false-
positive churn on every gate-code addition without a clear value
delta for retrieval quality.

Maintainer note: when you add a new failure code to a gate AND it is
part of the documented public interface (cited in CLAUDE.md, agent
prompts, or downstream tooling), also add it to ``EMITTED_GATE_CODES``
below + add a ``TAG_SYNONYMS`` entry in
``scripts/rag/retrieval/bm25.py``.
"""

from __future__ import annotations

import pytest

# Module-level skip if BM25 module not importable (mirrors the
# convention in tests/test_rag_bm25_synonyms.py — the dense half of
# the retriever pulls sentence_transformers transitively).
pytest.importorskip("sentence_transformers")

from scripts.rag.retrieval.bm25 import TAG_SYNONYMS  # noqa: E402


# ─── Single source of truth ───────────────────────────────────────
# Every code MLGG documents on its public interface (CLAUDE.md
# canonical rule codes) OR emits via the ci_* family of gates that
# downstream tooling tokenizes against the BM25 retriever.
EMITTED_GATE_CODES = frozenset([
    # ─── CLAUDE.md canonical rule codes (unchallengeable rules) ───
    "MLGG-S01", "MLGG-P01", "MLGG-F01", "MLGG-F02",
    "MLGG-M01", "MLGG-E01", "MLGG-E02",
    # NOTE on bare forms (`S01`..`E02`): the H12 grep audit (748-code
    # harvest of scripts/gates/) confirmed no gate emits the bare
    # uppercase form, only the `MLGG-` prefixed form. The lowercase
    # `s01..e02` keys exist in TAG_SYNONYMS to catch informal text-
    # citation cases via the `code.lower().replace("-", "_")` normalisation
    # path in ``_issue_code_keywords``. Adding bare uppercase to this
    # set would be a false positive — gates would never trigger it.

    # ─── ci_* family (E01 / E02 territory, grep-harvested from
    #     scripts/gates/ci_matrix_gate.py and friends) ───
    "missing_ci", "missing_ci_method", "missing_ci_matrix_report",
    "ci_matrix_not_passed", "ci_matrix_reference_mismatch",
    "ci_matrix_threshold_unstable", "ci_matrix_single_class",
    "insufficient_ci_resamples", "ci_resamples_insufficient",
    "ci_metric_mismatch", "ci_width_exceeds_threshold",
    "ci_width_exceeds_max", "ci_width_excessive",
    "ci_coverage_below_threshold", "primary_metric_outside_ci",
    "missing_primary_metric_ci",
    # Extend as gates add publicly-cited codes — the test failure
    # message tells you which code is missing.
])


def test_every_emitted_code_has_synonym_entry():
    """Every gate-emitted failure code must map to semantic tags in
    ``TAG_SYNONYMS``, so BM25 retrieval works on the documented public
    interface."""
    missing = sorted(c for c in EMITTED_GATE_CODES if c not in TAG_SYNONYMS)
    assert not missing, (
        f"{len(missing)} gate failure codes lack TAG_SYNONYMS entries.\n"
        f"Add them in scripts/rag/retrieval/bm25.py:\n  "
        + "\n  ".join(missing)
        + "\n\nWithout these, BM25 retrieval starves silently on the "
        "documented public interface (CLAUDE.md MLGG-* rule codes + "
        "gate-emitted ci_* codes)."
    )


def test_synonym_values_are_non_empty_lists():
    """Each ``TAG_SYNONYMS`` value must be a non-empty list of tags."""
    bad = {
        k: v
        for k, v in TAG_SYNONYMS.items()
        if not isinstance(v, (list, tuple, frozenset, set)) or not v
    }
    assert not bad, (
        f"{len(bad)} entries malformed: {dict(list(bad.items())[:5])}"
    )


def test_emitted_codes_set_is_reasonable_size():
    """Sanity: this set should grow as gates evolve, not shrink mysteriously."""
    # Baseline at H12 time: 7 MLGG-* canonical + 16 ci_* family = 23.
    # If a future change drops below this, investigate — codes shouldn't
    # disappear, only be added.
    assert len(EMITTED_GATE_CODES) >= 23, (
        f"EMITTED_GATE_CODES shrank to {len(EMITTED_GATE_CODES)}; "
        "did someone delete entries instead of adding new ones?"
    )
