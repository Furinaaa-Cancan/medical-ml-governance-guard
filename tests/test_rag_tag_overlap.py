"""Regression tests for the canonical-pattern tag-overlap bonus.

Covers ``scripts.rag.retrieval.hybrid._tag_overlap_scores`` and the
``scripts.rag.config.TAG_OVERLAP_MIN_SHARED`` constant.

History: W7-P0 (post W6-W2 architectural finding). The original implementation
hard-coded a ``>=2`` shared-tag requirement, which was satisfied by only
23 / 12,747 within-CP pairs (0.2%) in the production KB — effectively
turning the corroboration signal off. The threshold is now configurable
(default 1) so the signal actually fires for the canonical reuse pattern
of one shared root tag plus paper-specific narrowings.

See ``/tmp/W7P0_tag_overlap_arch.md`` for the measurement that drove the
default. Do not raise the default above 1 without re-running
``scripts/rag/evals/run_eval.py --mode hybrid`` and checking
``mean_top1_score`` does not regress.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concern(
    cid: str,
    *,
    cp: str = "CP-008",
    tags: list[str] | None = None,
) -> dict:
    """Build a minimal concern record sufficient for ``_tag_overlap_scores``."""
    return {
        "concern_id": cid,
        "canonical_pattern_id": cp,
        "tags": list(tags or []),
    }


# ---------------------------------------------------------------------------
# Config sanity
# ---------------------------------------------------------------------------


class TestTagOverlapConfig:
    """Pin the default and contract of ``TAG_OVERLAP_MIN_SHARED``."""

    def test_min_shared_default_is_one(self) -> None:
        """Default must remain ``1`` -- the W6-W2 / W7-P0 architectural fix.

        Raising this back to 2 silently kills the corroboration signal on
        ~99% of within-CP pairs in the production KB. If a future change
        needs to raise it, re-baseline ``mean_top1_score`` via
        ``run_eval.py --mode hybrid`` first.
        """
        config = pytest.importorskip("scripts.rag.config")
        assert config.TAG_OVERLAP_MIN_SHARED == 1, (
            "TAG_OVERLAP_MIN_SHARED must stay at 1 (W7-P0); raising it "
            "re-introduces the dead-signal regression W6-W2 documented."
        )

    def test_min_shared_is_positive_int(self) -> None:
        """A non-positive threshold would make every pair qualify."""
        config = pytest.importorskip("scripts.rag.config")
        assert isinstance(config.TAG_OVERLAP_MIN_SHARED, int)
        assert config.TAG_OVERLAP_MIN_SHARED >= 1


# ---------------------------------------------------------------------------
# Behaviour under default threshold (1)
# ---------------------------------------------------------------------------


class TestTagOverlapScores:
    """Direct unit tests on ``_tag_overlap_scores``."""

    def test_threshold_at_one_fires_on_single_shared_tag(self) -> None:
        """The headline W7-P0 case: two concerns share exactly one tag.

        Under the old ``>=2`` rule this returned ``{}``. Under the
        default ``TAG_OVERLAP_MIN_SHARED=1`` it must produce a positive
        bonus for both concerns.
        """
        hybrid = pytest.importorskip("scripts.rag.retrieval.hybrid")
        cands = [
            _concern(
                "A",
                tags=[
                    "no_external_validation",
                    "no_external_validation_for_combined",
                ],
            ),
            _concern(
                "B",
                tags=[
                    "no_external_validation",
                    "single_external_center",
                ],
            ),
        ]
        out = hybrid._tag_overlap_scores(cands)
        assert out.get("A", 0.0) > 0.0
        assert out.get("B", 0.0) > 0.0

    def test_no_shared_tags_produces_no_bonus(self) -> None:
        """Two same-CP concerns with disjoint tags must not corroborate."""
        hybrid = pytest.importorskip("scripts.rag.retrieval.hybrid")
        cands = [
            _concern("A", tags=["alpha"]),
            _concern("B", tags=["beta"]),
        ]
        out = hybrid._tag_overlap_scores(cands)
        assert out == {}

    def test_different_canonical_patterns_do_not_corroborate(self) -> None:
        """Cross-CP overlap stays out of the bonus by design.

        The corroboration argument is *within* a pattern: same-tag,
        different-pattern concerns are not evidence of the same failure.
        """
        hybrid = pytest.importorskip("scripts.rag.retrieval.hybrid")
        cands = [
            _concern("A", cp="CP-001", tags=["shared", "x"]),
            _concern("B", cp="CP-008", tags=["shared", "y"]),
        ]
        out = hybrid._tag_overlap_scores(cands)
        assert out == {}

    def test_bonus_scales_with_partner_count(self) -> None:
        """``score = min(1.0, 0.3 * partners)`` is the cap contract."""
        hybrid = pytest.importorskip("scripts.rag.retrieval.hybrid")
        cands = [
            _concern("A", tags=["shared"]),
            _concern("B", tags=["shared"]),
            _concern("C", tags=["shared"]),
        ]
        out = hybrid._tag_overlap_scores(cands)
        # A has two partners (B, C) -> 0.6; same for B and C.
        assert out["A"] == pytest.approx(0.6)
        assert out["B"] == pytest.approx(0.6)
        assert out["C"] == pytest.approx(0.6)

    def test_missing_concern_id_is_skipped(self) -> None:
        """Records without a ``concern_id`` cannot be keyed; skip silently."""
        hybrid = pytest.importorskip("scripts.rag.retrieval.hybrid")
        cands = [
            {"canonical_pattern_id": "CP-008", "tags": ["t1"]},
            _concern("B", tags=["t1"]),
        ]
        out = hybrid._tag_overlap_scores(cands)
        # B has no qualifying partner (A is unkeyed), so out is empty.
        # The contract is "no crash, no spurious key".
        assert "B" not in out or out["B"] == 0.0
        assert None not in out
