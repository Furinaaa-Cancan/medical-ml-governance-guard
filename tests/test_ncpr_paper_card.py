"""Tests for NCPR v2 per-paper score card (W23-C5).

Offline + deterministic — exercises pure formatting logic on synthetic
matcher / scorer output. No embedder, no network, no real PDFs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.rag.evals.ncpr_paper_card import (
    make_paper_card,
    write_card_set,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _paper_entry_basic() -> dict:
    """Two reviewer concerns: one CRITICAL (matched), one HIGH (missed)."""
    return {
        "title": "External validation of an ICU mortality model",
        "concerns": [
            {
                "concern_id": "c1",
                "concern_text": "No external validation reported.",
                "severity": "CRITICAL",
                "category": "external_val",
                "mlgg_gates": ["external_validation_gate"],
            },
            {
                "concern_id": "c2",
                "concern_text": "Calibration metrics omitted.",
                "severity": "HIGH",
                "category": "evaluation",
                "mlgg_gates": ["calibration_gate"],
            },
        ],
    }


def _flags_basic() -> list[dict]:
    return [
        {
            "code": "external_validation_missing",
            "severity": "CRITICAL",
            "category": "external_val",
            "evidence_text": "Train and test sourced from same cohort.",
        },
        {
            "code": "noisy_gate_unrelated",
            "severity": "LOW",
            "category": "design",
            "evidence_text": "Cohort enrolled 2010-2020.",
        },
    ]


def _matched_pairs_basic() -> list[dict]:
    # Only the first concern is matched; the second is a miss.
    return [
        {
            "flag_idx": 0,
            "concern_idx": 0,
            "type": "code_prefix",
            "score": 1.0,
        },
    ]


def _score_breakdown_basic() -> dict:
    return {
        "paper_id": "p1",
        "totals": {
            "wTP": 4.0,
            "wFN": 2.0,
            "wFP": 0.25,
            "wPrecision": 0.94,
            "wRecall": 0.67,
            "weighted_f1": 0.78,
        },
        "category_coverage": {"covered": 1, "total": 5},
    }


# ---------------------------------------------------------------------------
# 1. make_paper_card — happy path
# ---------------------------------------------------------------------------
class TestMakePaperCardHappyPath:
    def test_returns_markdown_string(self):
        md = make_paper_card(
            paper_id="p1",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=_flags_basic(),
            matched=_matched_pairs_basic(),
            score_breakdown=_score_breakdown_basic(),
        )
        assert isinstance(md, str)
        assert md.strip()

    def test_header_contains_title_and_scores(self):
        md = make_paper_card(
            paper_id="p1",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=_flags_basic(),
            matched=_matched_pairs_basic(),
            score_breakdown=_score_breakdown_basic(),
        )
        assert "# Paper p1:" in md
        assert "External validation of an ICU mortality model" in md
        assert "weighted_f1=0.78" in md
        assert "category_coverage=1/5" in md

    def test_matched_concern_renders_flag_code(self):
        md = make_paper_card(
            paper_id="p1",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=_flags_basic(),
            matched=_matched_pairs_basic(),
            score_breakdown=_score_breakdown_basic(),
        )
        assert "MATCHED" in md
        assert "external_validation_missing" in md
        assert "code_prefix" in md

    def test_missed_concern_renders_miss_marker(self):
        md = make_paper_card(
            paper_id="p1",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=_flags_basic(),
            matched=_matched_pairs_basic(),
            score_breakdown=_score_breakdown_basic(),
        )
        assert "MISSED" in md
        # The HIGH-severity calibration concern should appear as missed.
        assert "Calibration metrics omitted" in md
        assert "[HIGH]" in md

    def test_over_flagging_section_lists_unmatched_flag(self):
        md = make_paper_card(
            paper_id="p1",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=_flags_basic(),
            matched=_matched_pairs_basic(),
            score_breakdown=_score_breakdown_basic(),
        )
        assert "noisy_gate_unrelated" in md
        assert "MLGG over-flagging" in md

    def test_deterministic(self):
        # Reproducibility: same inputs → byte-identical output.
        a = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        b = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        assert a == b


# ---------------------------------------------------------------------------
# 2. Zero-flags edge case → explicit hypothesis
# ---------------------------------------------------------------------------
class TestMakePaperCardZeroFlags:
    def test_zero_flags_says_mlgg_no_flags(self):
        md = make_paper_card(
            paper_id="p_silent",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=[],
            matched=[],
            score_breakdown={
                "totals": {
                    "wTP": 0.0,
                    "wFN": 6.0,
                    "wFP": 0.0,
                    "wPrecision": 0.0,
                    "wRecall": 0.0,
                    "weighted_f1": 0.0,
                },
            },
        )
        assert "MLGG returned no flags" in md
        # Both concerns must appear as missed.
        assert md.count("MISSED") == 2

    def test_zero_flags_handles_no_over_flagging_section(self):
        md = make_paper_card(
            paper_id="p_silent",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=[],
            matched=[],
            score_breakdown={"totals": {"weighted_f1": 0.0}},
        )
        # Over-flagging section still rendered but with zero entries.
        assert "MLGG over-flagging (0 flags" in md

    def test_zero_concerns_returns_excluded_hypothesis(self):
        md = make_paper_card(
            paper_id="p_empty",
            paper_entry={"title": "Empty", "concerns": []},
            mlgg_flags=[],
            matched=[],
            score_breakdown={"totals": {"weighted_f1": 0.0}},
        )
        assert "no reviewer concerns" in md.lower()


# ---------------------------------------------------------------------------
# 3. write_card_set — file-per-paper
# ---------------------------------------------------------------------------
class TestWriteCardSet:
    def test_writes_one_file_per_paper(self, tmp_path: Path):
        cards = {
            "p1": "# Paper p1\nbody\n",
            "p2": "# Paper p2\nbody\n",
            "p3": "# Paper p3\nbody\n",
        }
        write_card_set(cards, tmp_path)
        produced = sorted(p.name for p in tmp_path.glob("card_*.md"))
        assert produced == ["card_p1.md", "card_p2.md", "card_p3.md"]

    def test_creates_missing_dir(self, tmp_path: Path):
        out = tmp_path / "nested" / "cards"
        write_card_set({"p1": "# x\n"}, out)
        assert (out / "card_p1.md").is_file()

    def test_round_trip_content_preserved(self, tmp_path: Path):
        body = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        write_card_set({"p1": body}, tmp_path)
        round_tripped = (tmp_path / "card_p1.md").read_text(encoding="utf-8")
        assert round_tripped == body

    def test_slugifies_unsafe_paper_id(self, tmp_path: Path):
        # Paths with separators must NOT escape the output dir.
        cards = {"foo/bar baz": "# x\n"}
        write_card_set(cards, tmp_path)
        files = list(tmp_path.glob("card_*.md"))
        assert len(files) == 1
        # Slugged: '/' and ' ' replaced with '_'.
        assert "/" not in files[0].name
        assert " " not in files[0].name

    def test_rejects_non_dict(self, tmp_path: Path):
        with pytest.raises(TypeError):
            write_card_set(["not", "a", "dict"], tmp_path)  # type: ignore[arg-type]

    def test_rejects_non_string_value(self, tmp_path: Path):
        # Common foot-gun: passing the raw score_breakdown dict by mistake.
        with pytest.raises(TypeError):
            write_card_set({"p1": {"weighted_f1": 0.5}}, tmp_path)  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# 4. Markdown structural completeness
# ---------------------------------------------------------------------------
class TestMarkdownStructure:
    def test_has_all_required_sections(self):
        md = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        # Spec interface: header + 3 sections.
        assert md.startswith("# Paper ")
        assert "## Real reviewer concerns" in md
        assert "## MLGG over-flagging" in md
        assert "## Failure mode hypothesis" in md

    def test_sections_appear_in_spec_order(self):
        md = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        idx_concerns = md.index("## Real reviewer concerns")
        idx_over = md.index("## MLGG over-flagging")
        idx_hyp = md.index("## Failure mode hypothesis")
        assert idx_concerns < idx_over < idx_hyp

    def test_failure_hypothesis_non_empty(self):
        md = make_paper_card(
            "p1",
            _paper_entry_basic(),
            _flags_basic(),
            _matched_pairs_basic(),
            _score_breakdown_basic(),
        )
        hyp_block = md.split("## Failure mode hypothesis", 1)[1].strip()
        assert hyp_block  # not empty
        # And it shouldn't be just whitespace.
        assert any(ch.isalpha() for ch in hyp_block)

    def test_critical_miss_hypothesis(self):
        # If a CRITICAL concern is missed, hypothesis must mention it.
        md = make_paper_card(
            paper_id="p_crit",
            paper_entry=_paper_entry_basic(),
            mlgg_flags=[
                {
                    "code": "irrelevant_gate",
                    "severity": "LOW",
                    "category": "design",
                    "evidence_text": "Cohort metadata only.",
                },
            ],
            matched=[],  # nothing matched — CRITICAL is missed
            score_breakdown={"totals": {"weighted_f1": 0.0}},
        )
        hyp = md.split("## Failure mode hypothesis", 1)[1].lower()
        assert "critical" in hyp
