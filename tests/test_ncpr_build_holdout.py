"""Unit tests for ``scripts/rag/evals/ncpr_build_holdout.py`` (W22-X7).

All inputs are synthetic dict-literal KBs written to ``tmp_path`` so the
suite is offline, deterministic, and does not touch the real
``references/`` tree. Mirrors the T3 criteria pre-registered in
``references/benchmark/ncpr_v1_holdout_criteria.md``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.rag.evals.ncpr_build_holdout import (
    APPROVED_JOURNALS,
    HoldoutBuilderError,
    select_holdout,
)


# ----------------------------------------------------------------------
# Factory helpers
# ----------------------------------------------------------------------


def _concern(
    cid: str,
    *,
    category: str = "evaluation_metrics",
    severity: str = "HIGH",
) -> dict[str, Any]:
    return {
        "concern_id": cid,
        "category": category,
        "severity": severity,
        "concern_text": "synthetic",
    }


def _paper(
    pid: str,
    *,
    journal: str = "Nature Communications",
    year: int = 2024,
    n_concerns: int = 5,
    high_severity: bool = True,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Build a synthetic KB entry that passes the eligibility filter by default."""
    categories = categories or [
        "evaluation_metrics",
        "study_design",
        "reporting",
        "external_validation",
        "data_leakage",
    ]
    concerns: list[dict] = []
    for i in range(n_concerns):
        cat = categories[i % len(categories)]
        sev = "HIGH" if (high_severity and i == 0) else "MEDIUM"
        concerns.append(_concern(f"{pid}-C{i:02d}", category=cat, severity=sev))
    return {
        "id": pid,
        "journal": journal,
        "year": year,
        "reviewer_concerns": concerns,
        "methods_text": "synthetic methods",
    }


def _write_kb(tmp_path: Path, entries: list[dict]) -> Path:
    kb_path = tmp_path / "kb.json"
    kb_path.write_text(json.dumps({
        "contract_version": "test",
        "total_papers": len(entries),
        "total_concerns": sum(len(e.get("reviewer_concerns", [])) for e in entries),
        "entries": entries,
    }))
    return kb_path


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_select_holdout_with_50_papers_returns_30(tmp_path: Path) -> None:
    """50-paper synthetic KB across 3 approved journals → builder returns n=30."""
    entries: list[dict] = []
    # Spread across enough journals that the 40% cap (12 papers) is feasible
    journals = [
        "Nature Communications",
        "Communications Medicine",
        "Nature Medicine",
    ]
    for i in range(50):
        entries.append(_paper(f"PR-{i:03d}", journal=journals[i % 3]))

    kb_path = _write_kb(tmp_path, entries)
    selected = select_holdout(
        kb_path=kb_path,
        n=30,
        seed=42,
        existing_eval_sets=[],  # bypass real eval-set lookups
        publication_date_cutoff="2026-04-30",
    )
    assert len(selected) == 30
    # IDs are unique and all came from the synthetic pool
    sel_ids = {e["id"] for e in selected}
    assert len(sel_ids) == 30
    assert sel_ids.issubset({e["id"] for e in entries})


def test_select_holdout_raises_when_pool_smaller_than_n(tmp_path: Path) -> None:
    """10 eligible papers but n=30 → HoldoutBuilderError(insufficient_eligible)."""
    entries = [_paper(f"PR-{i:03d}") for i in range(10)]
    kb_path = _write_kb(tmp_path, entries)
    with pytest.raises(HoldoutBuilderError) as exc:
        select_holdout(
            kb_path=kb_path,
            n=30,
            seed=42,
            existing_eval_sets=[],
            publication_date_cutoff="2026-04-30",
        )
    assert exc.value.reason == "insufficient_eligible"


def test_stratification_journal_cap_redistributes_or_errors(tmp_path: Path) -> None:
    """KB skewed to one journal → builder enforces 40% cap by redistributing
    when another approved journal has capacity, else raises with a clear
    ``journal_cap_infeasible`` reason."""
    # 100 papers, ALL from a single approved journal — no redistribution
    # target exists, so the cap must raise.
    entries = [_paper(f"PR-{i:03d}", journal="Nature Communications") for i in range(100)]
    kb_path = _write_kb(tmp_path, entries)
    # With a single-journal pool the cap of 40% (=12 papers) cannot be
    # met for n=30 because there is nowhere to redistribute the surplus.
    with pytest.raises(HoldoutBuilderError) as exc:
        select_holdout(
            kb_path=kb_path,
            n=30,
            seed=42,
            existing_eval_sets=[],
            publication_date_cutoff="2026-04-30",
        )
    assert exc.value.reason == "journal_cap_infeasible"


def test_all_papers_in_eval_sets_zero_eligible_raises(tmp_path: Path) -> None:
    """All KB paper ids are referenced by an eval set → 0 eligible → raise."""
    entries = [_paper(f"PR-{i:03d}") for i in range(40)]
    kb_path = _write_kb(tmp_path, entries)
    # Synthetic eval set that names every paper via a concern_id
    eval_path = tmp_path / "scenarios.json"
    eval_path.write_text(json.dumps({
        "scenarios": [
            {"scenario_id": f"s{i}", "concern_ids": [f"{e['id']}-C00"]}
            for i, e in enumerate(entries)
        ],
    }))
    with pytest.raises(HoldoutBuilderError) as exc:
        select_holdout(
            kb_path=kb_path,
            n=30,
            seed=42,
            existing_eval_sets=[eval_path],
            publication_date_cutoff="2026-04-30",
        )
    assert exc.value.reason == "insufficient_eligible"


def test_seed_determinism_same_seed_same_selection(tmp_path: Path) -> None:
    """Same seed → same 30 papers, byte-for-byte. T3 §"Tie-breaking"."""
    entries = []
    for i in range(50):
        journal = "Nature Communications" if i % 2 == 0 else "Communications Medicine"
        entries.append(_paper(f"PR-{i:03d}", journal=journal))
    kb_path = _write_kb(tmp_path, entries)

    first = select_holdout(
        kb_path=kb_path,
        n=30,
        seed=2026,
        existing_eval_sets=[],
        publication_date_cutoff="2026-04-30",
    )
    second = select_holdout(
        kb_path=kb_path,
        n=30,
        seed=2026,
        existing_eval_sets=[],
        publication_date_cutoff="2026-04-30",
    )
    assert [e["id"] for e in first] == [e["id"] for e in second]


def test_year_cutoff_excludes_post_cutoff_papers(tmp_path: Path) -> None:
    """Papers with year > cutoff year are rejected by criterion 5."""
    entries: list[dict] = []
    journals = ["Nature Communications", "Communications Medicine", "Nature Medicine"]
    # 36 eligible (2024) — spread across 3 journals so journal cap is feasible
    for i in range(36):
        entries.append(_paper(f"PR-{i:03d}", journal=journals[i % 3], year=2024))
    # 50 post-cutoff (2027) — should all be filtered out
    for i in range(36, 86):
        entries.append(_paper(f"PR-{i:03d}", journal=journals[i % 3], year=2027))

    kb_path = _write_kb(tmp_path, entries)
    selected = select_holdout(
        kb_path=kb_path,
        n=30,
        seed=42,
        existing_eval_sets=[],
        publication_date_cutoff="2026-04-30",
    )
    assert len(selected) == 30
    for e in selected:
        assert e["year"] <= 2026


def test_severity_floor_requires_high_or_critical(tmp_path: Path) -> None:
    """Every selected paper must have >=1 CRITICAL/HIGH concern (T3 §strat)."""
    # 40 papers, all MEDIUM-only — severity floor must reject the whole pool.
    entries = [
        _paper(f"PR-{i:03d}", high_severity=False) for i in range(40)
    ]
    kb_path = _write_kb(tmp_path, entries)
    with pytest.raises(HoldoutBuilderError) as exc:
        select_holdout(
            kb_path=kb_path,
            n=30,
            seed=42,
            existing_eval_sets=[],
            publication_date_cutoff="2026-04-30",
        )
    assert exc.value.reason == "severity_floor_infeasible"


def test_approved_journals_constant_matches_spec() -> None:
    """Guard against accidental rename — T3 §criterion 2."""
    assert "nature_communications" in APPROVED_JOURNALS
    assert "communications_medicine" in APPROVED_JOURNALS
    assert "lancet_digital_health" in APPROVED_JOURNALS
    assert "jama" in APPROVED_JOURNALS
    assert "nature_medicine" in APPROVED_JOURNALS
    assert "npj_digital_medicine" in APPROVED_JOURNALS
