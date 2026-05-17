"""Tests for scripts/export_review_prompt.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATE_SCRIPT = SCRIPTS_DIR / "reporting/export_review_prompt.py"

import export_review_prompt as erp


# ── helper ───────────────────────────────────────────────────────────────────

def _load_standard():
    return erp.load_json(erp.REVIEW_STANDARD_PATH)


# ── get_criteria_for_level ────────────────────────────────────────────────────

class TestGetCriteriaForLevel:
    def test_quick_subset_of_standard(self):
        standard = _load_standard()
        quick = erp.get_criteria_for_level(standard["dimensions"], "quick")
        standard_crits = erp.get_criteria_for_level(standard["dimensions"], "standard")
        # Quick must be a strict subset
        quick_ids = {c["criterion"]["id"] for c in quick}
        standard_ids = {c["criterion"]["id"] for c in standard_crits}
        assert quick_ids.issubset(standard_ids)

    def test_standard_subset_of_comprehensive(self):
        standard = _load_standard()
        std = erp.get_criteria_for_level(standard["dimensions"], "standard")
        comp = erp.get_criteria_for_level(standard["dimensions"], "comprehensive")
        std_ids = {c["criterion"]["id"] for c in std}
        comp_ids = {c["criterion"]["id"] for c in comp}
        assert std_ids.issubset(comp_ids)

    def test_quick_has_criteria(self):
        standard = _load_standard()
        quick = erp.get_criteria_for_level(standard["dimensions"], "quick")
        assert len(quick) > 0

    def test_comprehensive_max_criteria(self):
        standard = _load_standard()
        comp = erp.get_criteria_for_level(standard["dimensions"], "comprehensive")
        # comprehensive must have the most
        quick = erp.get_criteria_for_level(standard["dimensions"], "quick")
        assert len(comp) >= len(quick)


# ── render_markdown_prompt ────────────────────────────────────────────────────

class TestRenderMarkdownPrompt:
    def test_returns_string(self):
        standard = _load_standard()
        result = erp.render_markdown_prompt(
            standard=standard,
            level="quick",
            journal_data=None,
            journal_name=None,
            include_literature=False,
            lit_kb=None,
        )
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_criteria_heading(self):
        standard = _load_standard()
        result = erp.render_markdown_prompt(
            standard=standard, level="standard",
            journal_data=None, journal_name=None,
            include_literature=False, lit_kb=None,
        )
        assert "## Criteria" in result or "##" in result

    def test_contains_role_section(self):
        standard = _load_standard()
        result = erp.render_markdown_prompt(
            standard=standard, level="quick",
            journal_data=None, journal_name=None,
            include_literature=False, lit_kb=None,
        )
        assert "Your Role" in result or "peer reviewer" in result.lower()

    def test_journal_section_included(self):
        standard = _load_standard()
        journal_standards = erp.load_json(erp.JOURNAL_STANDARDS_PATH)
        journal_data = journal_standards.get("journals", {}).get("nature_medicine")
        result = erp.render_markdown_prompt(
            standard=standard, level="comprehensive",
            journal_data=journal_data, journal_name="nature_medicine",
            include_literature=False, lit_kb=None,
        )
        assert "Nature Medicine" in result or "nature_medicine" in result.lower()

    def test_literature_section_included(self):
        standard = _load_standard()
        lit_kb = erp.load_json(erp.LITERATURE_KB_PATH)
        result = erp.render_markdown_prompt(
            standard=standard, level="standard",
            journal_data=None, journal_name=None,
            include_literature=True, lit_kb=lit_kb,
        )
        assert "Literature" in result or "References" in result

    def test_literature_not_included_by_default(self):
        standard = _load_standard()
        result = erp.render_markdown_prompt(
            standard=standard, level="quick",
            journal_data=None, journal_name=None,
            include_literature=False, lit_kb=None,
        )
        assert "Key Literature References" not in result


# ── render_json_prompt ────────────────────────────────────────────────────────

class TestRenderJsonPrompt:
    def test_returns_valid_json(self):
        standard = _load_standard()
        result = erp.render_json_prompt(
            standard=standard, level="standard",
            journal_data=None, journal_name=None,
        )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_has_required_keys(self):
        standard = _load_standard()
        result = erp.render_json_prompt(
            standard=standard, level="quick",
            journal_data=None, journal_name=None,
        )
        parsed = json.loads(result)
        assert "criteria" in parsed
        assert "review_level" in parsed
        assert "total_criteria" in parsed

    def test_criteria_count_matches(self):
        standard = _load_standard()
        criteria_flat = erp.get_criteria_for_level(standard["dimensions"], "standard")
        result = erp.render_json_prompt(
            standard=standard, level="standard",
            journal_data=None, journal_name=None,
        )
        parsed = json.loads(result)
        assert parsed["total_criteria"] == len(criteria_flat)

    def test_journal_section_in_json(self):
        standard = _load_standard()
        journal_standards = erp.load_json(erp.JOURNAL_STANDARDS_PATH)
        journal_data = journal_standards.get("journals", {}).get("jama")
        result = erp.render_json_prompt(
            standard=standard, level="quick",
            journal_data=journal_data, journal_name="jama",
        )
        parsed = json.loads(result)
        assert "target_journal" in parsed


# ── CLI integration ───────────────────────────────────────────────────────────

def _run_cli(*args):
    cmd = [sys.executable, str(GATE_SCRIPT)] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))


# ── literature sorting (audit finding m7) ─────────────────────────────────────


def _make_lit_entry(
    idx: int,
    year: int,
    impact_factor,
    gates=None,
    dims=None,
    title: str | None = None,
):
    return {
        "id": f"LIT-{idx:03d}",
        "title": title or f"Mock literature entry number {idx} for sort-key testing",
        "journal": "MockJournal",
        "year": year,
        "impact_factor": impact_factor,
        "gates_implementing": list(gates or []),
        "dimensions_affected": list(dims or []),
    }


class TestLitRelevanceKey:
    def test_context_gate_overlap_beats_year(self):
        # Older paper that matches the context gate must outrank a newer
        # off-topic paper.
        on_topic = _make_lit_entry(1, year=2018, impact_factor=20.0,
                                   gates=["leakage_gate"])
        off_topic = _make_lit_entry(2, year=2025, impact_factor=80.0,
                                    gates=["unrelated_gate"])
        ctx_gates = {"leakage_gate"}
        ranked = sorted(
            [off_topic, on_topic],
            key=lambda e: erp._lit_relevance_key(e, ctx_gates, set()),
            reverse=True,
        )
        assert ranked[0]["id"] == on_topic["id"]

    def test_year_breaks_tie_when_relevance_equal(self):
        a = _make_lit_entry(1, year=2024, impact_factor=10.0,
                            gates=["leakage_gate"])
        b = _make_lit_entry(2, year=2018, impact_factor=10.0,
                            gates=["leakage_gate"])
        ranked = sorted(
            [b, a],
            key=lambda e: erp._lit_relevance_key(e, {"leakage_gate"}, set()),
            reverse=True,
        )
        assert ranked[0]["id"] == a["id"]

    def test_impact_factor_breaks_tie_when_year_equal(self):
        a = _make_lit_entry(1, year=2024, impact_factor=80.0)
        b = _make_lit_entry(2, year=2024, impact_factor=5.0)
        ranked = sorted([b, a], key=erp._lit_relevance_key, reverse=True)
        assert ranked[0]["id"] == a["id"]

    def test_missing_impact_factor_treated_as_zero(self):
        a = _make_lit_entry(1, year=2024, impact_factor=None)
        b = _make_lit_entry(2, year=2024, impact_factor=15.0)
        ranked = sorted([a, b], key=erp._lit_relevance_key, reverse=True)
        assert ranked[0]["id"] == b["id"]

    def test_dimension_overlap_fallback(self):
        # If no gate match, dimension overlap should still beat no overlap.
        dim_match = _make_lit_entry(1, year=2010, impact_factor=5.0, dims=[3])
        no_match = _make_lit_entry(2, year=2020, impact_factor=5.0, dims=[99])
        ranked = sorted(
            [no_match, dim_match],
            key=lambda e: erp._lit_relevance_key(e, set(), {3}),
            reverse=True,
        )
        assert ranked[0]["id"] == dim_match["id"]


class TestLiteratureTopTwenty:
    """Audit finding m7: top-20 must be relevance-sorted, not file-order."""

    def _build_kb(self):
        """25 entries: low-relevance first (so file-order would lose info)."""
        entries = []
        # 1-15: off-topic, old, low IF (would dominate under the old bug)
        for i in range(1, 16):
            entries.append(_make_lit_entry(
                i, year=2005 + (i % 5), impact_factor=2.0 + i * 0.1,
                gates=["unrelated_gate"], dims=[99],
                title=f"Off-topic legacy paper {i}",
            ))
        # 16-22: highly relevant (gate match), recent, high IF
        for i in range(16, 23):
            entries.append(_make_lit_entry(
                i, year=2023 + (i % 3), impact_factor=50.0 + i,
                gates=["leakage_gate"], dims=[2],
                title=f"On-topic flagship paper {i}",
            ))
        # 23-25: dimension match only, mid IF
        for i in range(23, 26):
            entries.append(_make_lit_entry(
                i, year=2022, impact_factor=30.0,
                gates=["other_gate"], dims=[2],
                title=f"Dimension-match paper {i}",
            ))
        return {"entries": entries}

    def test_top_twenty_prefers_relevant_entries(self, tmp_path):
        standard = _load_standard()
        lit_kb = self._build_kb()
        # Render with literature included; standard level pulls D2 criteria
        # (which reference leakage_gate), so on-topic entries should win.
        out = erp.render_markdown_prompt(
            standard=standard,
            level="standard",
            journal_data=None,
            journal_name=None,
            include_literature=True,
            lit_kb=lit_kb,
        )
        # All seven gate-match entries must appear in the top-20 slice.
        for i in range(16, 23):
            assert f"LIT-{i:03d}" in out, f"missing gate-match LIT-{i:03d}"
        # All three dimension-match entries must also appear.
        for i in range(23, 26):
            assert f"LIT-{i:03d}" in out, f"missing dim-match LIT-{i:03d}"
        # On-topic entries must rank above any off-topic ones that survived
        # the cut. Pick the worst-ranked off-topic entry that did make it in.
        off_topic_present = [
            i for i in range(1, 16) if f"LIT-{i:03d}" in out
        ]
        assert off_topic_present, "expected some off-topic fillers in top-20"
        idx_top_match = out.index("LIT-022")
        idx_first_off = min(out.index(f"LIT-{i:03d}") for i in off_topic_present)
        assert idx_top_match < idx_first_off, (
            "on-topic LIT-022 should rank above all off-topic entries"
        )

        # Persist artifact for audit trail.
        artifact = tmp_path / "rendered.md"
        artifact.write_text(out, encoding="utf-8")
        assert artifact.stat().st_size > 0

    def test_pre_fix_bug_no_longer_reproduces(self, tmp_path):
        """Old code took entries[:20] in file order, so LIT-021..LIT-025
        (gate matches and dim matches living at indexes 20-24) would never
        appear. After the fix they must appear."""
        standard = _load_standard()
        lit_kb = self._build_kb()
        out = erp.render_markdown_prompt(
            standard=standard, level="standard",
            journal_data=None, journal_name=None,
            include_literature=True, lit_kb=lit_kb,
        )
        for late_id in ("LIT-021", "LIT-022"):
            assert late_id in out, (
                f"{late_id} (high-relevance, late file order) missing — "
                "pre-fix bug reproduced"
            )
        # Write artifact so tmp_path is exercised per project standard.
        (tmp_path / "post_fix.md").write_text(out, encoding="utf-8")


class TestCLI:
    def test_quick_stdout(self):
        result = _run_cli("--level", "quick")
        assert result.returncode == 0
        assert len(result.stdout) > 100

    def test_standard_stdout(self):
        result = _run_cli("--level", "standard")
        assert result.returncode == 0
        assert "Criteria" in result.stdout or "criteria" in result.stdout.lower()

    def test_comprehensive_stdout(self):
        result = _run_cli("--level", "comprehensive")
        assert result.returncode == 0
        assert len(result.stdout) > len(_run_cli("--level", "quick").stdout)

    def test_json_format(self):
        result = _run_cli("--level", "quick", "--format", "json")
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert "criteria" in parsed

    def test_output_to_file(self, tmp_path):
        out = tmp_path / "prompt.md"
        result = _run_cli("--level", "quick", "--output", str(out))
        assert result.returncode == 0
        assert out.exists()
        assert out.stat().st_size > 0

    def test_journal_flag(self):
        result = _run_cli("--level", "standard", "--journal", "nature_medicine")
        assert result.returncode == 0
        assert "Nature Medicine" in result.stdout

    def test_include_literature(self):
        result = _run_cli("--level", "quick", "--include-literature")
        assert result.returncode == 0
        assert "Literature" in result.stdout or "References" in result.stdout

    def test_json_with_journal(self):
        result = _run_cli("--level", "quick", "--format", "json", "--journal", "jama")
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert "target_journal" in parsed
