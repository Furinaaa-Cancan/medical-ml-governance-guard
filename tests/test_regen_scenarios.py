"""Tests for scripts/rag/evals/regen_scenarios.py — the AST collector
and the dry-run regen pipeline.

Closes W17-C4 / W9-C1 ghost-finding loop.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

# scripts/rag/evals/ is not on the global conftest sys.path list,
# so add it here. Single-line hack, isolated to this test file.
_EVALS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "rag" / "evals"
if str(_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVALS_DIR))

from regen_scenarios import (
    collect_codes_from_source,
    collect_codes_per_gate,
    rank_seed_candidates,
    regen_scenario,
)


# ──────────────────────────────────────────────────────────────────────
# AST collector
# ──────────────────────────────────────────────────────────────────────


def test_collect_codes_finds_add_issue_literals() -> None:
    """``add_issue(bucket, "<code>", …)`` second-arg literals are
    collected; bare variable codes are skipped (cannot be statically
    resolved without dataflow analysis)."""
    source = textwrap.dedent(
        """
        from _gate_utils import add_issue

        def run(failures, warnings):
            add_issue(failures, "row_overlap", "msg", {})
            add_issue(warnings, "column_mismatch", "msg", {"k": 1})
            # bare-variable code; must NOT appear in the collected set
            dynamic_code = "patient_id_overlap"
            add_issue(failures, dynamic_code, "msg", {})
        """
    )
    codes = collect_codes_from_source(source)
    assert "row_overlap" in codes
    assert "column_mismatch" in codes
    assert "patient_id_overlap" not in codes  # var-resolved, not literal


def test_collect_codes_finds_register_remediations_dict() -> None:
    """``register_remediations({"code": "hint", …})`` dict keys are
    collected as declared codes."""
    source = textwrap.dedent(
        """
        from _gate_framework import register_remediations

        register_remediations({
            "io_error": "Verify file exists.",
            "suspicious_feature_names": "Rename leaky columns.",
        })
        """
    )
    codes = collect_codes_from_source(source)
    assert codes == {"io_error", "suspicious_feature_names"}


def test_collect_codes_handles_syntax_error_gracefully() -> None:
    """A broken gate module must not blow up the whole regen pass."""
    bad_source = "def broken( :\n  pass\n"
    assert collect_codes_from_source(bad_source) == set()


def test_collect_codes_per_gate_on_fixture(tmp_path: Path) -> None:
    """Drop two synthetic gate files into a tmp dir and confirm the
    walker picks both up under their stem keys."""
    (tmp_path / "fake_alpha_gate.py").write_text(
        textwrap.dedent(
            """
            from _gate_utils import add_issue
            from _gate_framework import register_remediations

            register_remediations({"alpha_code_1": "hint1"})

            def run(failures):
                add_issue(failures, "alpha_code_2", "msg", {})
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "fake_beta_gate.py").write_text(
        textwrap.dedent(
            """
            from _gate_utils import add_issue
            def run(failures):
                add_issue(failures, "beta_only", "msg", {})
            """
        ),
        encoding="utf-8",
    )
    # also drop a dunder file that MUST be ignored
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    per_gate = collect_codes_per_gate(tmp_path)
    assert set(per_gate.keys()) == {"fake_alpha_gate", "fake_beta_gate"}
    assert per_gate["fake_alpha_gate"] == {"alpha_code_1", "alpha_code_2"}
    assert per_gate["fake_beta_gate"] == {"beta_only"}


# ──────────────────────────────────────────────────────────────────────
# regen_scenario behavior
# ──────────────────────────────────────────────────────────────────────


def test_regen_scenario_keeps_valid_drops_ghosts() -> None:
    source_codes = {"my_gate": {"good_a", "good_b", "good_c"}}
    harvest_codes: dict = {}
    sc = {
        "scenario_id": "x",
        "gate_name": "my_gate",
        "failure_codes": ["good_a", "ghost_x", "good_b"],
    }
    new, kept, removed, added = regen_scenario(sc, source_codes, harvest_codes)
    assert kept == ["good_a", "good_b"]
    assert removed == ["ghost_x"]
    assert added == []
    assert new["failure_codes"] == ["good_a", "good_b"]


def test_regen_scenario_seeds_when_all_pruned() -> None:
    """If pruning leaves nothing, top-1 harvest-frequent codes seed."""
    source_codes = {"my_gate": {"src_a", "src_b"}}
    harvest_codes = {"my_gate": {"hot_code": 17, "cool_code": 1}}
    sc = {
        "scenario_id": "x",
        "gate_name": "my_gate",
        "failure_codes": ["ghost_only"],
    }
    new, kept, removed, added = regen_scenario(sc, source_codes, harvest_codes)
    assert kept == []
    assert removed == ["ghost_only"]
    # harvest-frequent first, then a source code to fill to 2
    assert added[0] == "hot_code"
    assert len(added) == 2
    assert new["failure_codes"] == sorted(added)


def test_regen_scenario_free_text_probe_unchanged() -> None:
    """Probe scenarios have no gate; pass through untouched."""
    sc = {
        "scenario_id": "probe",
        "gate_name": "free_text_probe",
        "failure_codes": [],
    }
    new, kept, removed, added = regen_scenario(sc, {}, {})
    assert removed == [] and added == []
    assert new == sc


def test_rank_seed_candidates_prefers_harvest_frequency() -> None:
    src = {"my_gate": {"src_a", "src_b", "src_c"}}
    harvest = {"my_gate": {"medium": 3, "popular": 10, "rare": 1}}
    seeds = rank_seed_candidates("my_gate", src, harvest)
    assert seeds == ["popular", "medium"]


def test_rank_seed_candidates_falls_back_to_source_lex_sorted() -> None:
    src = {"my_gate": {"z_code", "a_code", "m_code"}}
    seeds = rank_seed_candidates("my_gate", src, {})
    assert seeds == ["a_code", "m_code"]


# ──────────────────────────────────────────────────────────────────────
# Real-repo smoke: the script runs end-to-end and writes /tmp artifacts
# ──────────────────────────────────────────────────────────────────────


def test_main_dry_run_writes_artifacts(tmp_path: Path) -> None:
    """End-to-end: pointed at the real repo, the script must produce
    valid JSON + a non-empty markdown diff, and MUST NOT touch
    references/ (we don't pass anything that could)."""
    from regen_scenarios import main

    out_json = tmp_path / "v2.json"
    out_diff = tmp_path / "v2.md"
    rc = main(
        [
            "--out-json",
            str(out_json),
            "--out-diff",
            str(out_diff),
        ]
    )
    assert rc == 0
    assert out_json.exists() and out_diff.exists()
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert "scenarios" in doc and isinstance(doc["scenarios"], list)
    assert "regeneration_note" in doc
    assert "DRY RUN" in out_diff.read_text(encoding="utf-8")


@pytest.mark.parametrize("missing_field", ["gate_name", "failure_codes"])
def test_regen_scenario_tolerates_missing_fields(missing_field: str) -> None:
    """Don't crash on partial scenario dicts (defensive)."""
    sc = {"scenario_id": "incomplete"}
    if missing_field != "gate_name":
        sc["gate_name"] = "my_gate"
    if missing_field != "failure_codes":
        sc["failure_codes"] = ["x"]
    new, kept, removed, added = regen_scenario(sc, {"my_gate": {"x"}}, {})
    assert isinstance(new, dict)
