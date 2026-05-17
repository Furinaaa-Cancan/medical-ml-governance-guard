"""Unit tests for the NCPR v1 ground-truth extractor (W22-X8).

Pure-stdlib, offline, deterministic.  Each test builds a tiny KB JSON
file in a pytest ``tmp_path`` so the real
``references/case-studies/peer-review-kb.json`` (335 entries, ~MB-scale)
is never touched -- this matters because parallel sessions in the same
worktree can mutate that file while tests are running (see MEMORY.md
note on "Parallel sessions active").
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from rag.evals.ncpr_extract_ground_truth import (
    MethodsTextNotFound,
    PaperNotFound,
    extract_for_holdout,
    extract_methods_text,
    extract_reviewer_concerns,
)


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _concern(cid: str, **overrides) -> dict:
    base = {
        "concern_id": cid,
        "reviewer": "Reviewer #1",
        "round": 1,
        "category": "study_design",
        "severity": "HIGH",
        "mlgg_dimension": 1,
        "mlgg_gates": ["cohort_definition_gate"],
        "mlgg_rules": ["MLGG-F02"],
        "concern_text": f"placeholder text for {cid}",
        "tags": [],
    }
    base.update(overrides)
    return base


def _entry(pid: str, journal: str = "Nature Communications", **overrides) -> dict:
    base = {
        "id": pid,
        "paper_doi": f"10.1038/test-{pid}",
        "paper_title": f"Title for {pid}",
        "journal": journal,
        "year": 2024,
        "reviewer_concerns": [
            _concern(f"{pid}-C01"),
            _concern(f"{pid}-C02", severity="MEDIUM",
                     category="evaluation_metrics",
                     mlgg_gates=["evaluation_quality_gate"]),
        ],
    }
    base.update(overrides)
    return base


def _write_kb(tmp_path: Path, entries: list[dict]) -> Path:
    kb_path = tmp_path / "peer-review-kb.json"
    kb_path.write_text(json.dumps({
        "contract_version": "peer_review_kb.v1.4",
        "entries": entries,
    }), encoding="utf-8")
    return kb_path


# ────────────────────────────────────────────────────────────────────────
# extract_reviewer_concerns
# ────────────────────────────────────────────────────────────────────────


def test_extract_reviewer_concerns_happy_path(tmp_path):
    kb_path = _write_kb(tmp_path, [_entry("PR-001")])

    concerns = extract_reviewer_concerns("PR-001", kb_path)

    assert len(concerns) == 2
    assert concerns[0] == {
        "concern_id": "PR-001-C01",
        "concern_text": "placeholder text for PR-001-C01",
        "severity": "HIGH",
        "category": "study_design",
        "mlgg_gates": ["cohort_definition_gate"],
    }
    # Verify projection -- raw KB keys like ``reviewer``, ``round``,
    # ``author_response`` must NOT leak through (they would inflate the
    # matcher's input size with no benefit and break match_all's
    # TypedDict contract).
    for c in concerns:
        assert set(c.keys()) == {"concern_id", "concern_text", "severity",
                                 "category", "mlgg_gates"}


def test_extract_reviewer_concerns_missing_paper_raises(tmp_path):
    kb_path = _write_kb(tmp_path, [_entry("PR-001"), _entry("PR-002")])

    with pytest.raises(PaperNotFound) as exc:
        extract_reviewer_concerns("PR-999", kb_path)
    # PaperNotFound subclasses KeyError, so KeyError-catching code keeps working.
    assert isinstance(exc.value, KeyError)
    assert "PR-999" in str(exc.value)


def test_extract_reviewer_concerns_filters_non_curated_status(tmp_path):
    # Concerns *without* status are curated by convention; concerns
    # whose status is explicitly something else are dropped.
    entry = _entry("PR-010")
    entry["reviewer_concerns"] = [
        _concern("PR-010-C01"),  # no status field -> curated
        _concern("PR-010-C02", status="curated"),
        _concern("PR-010-C03", status="draft"),
        _concern("PR-010-C04", status="retracted"),
    ]
    kb_path = _write_kb(tmp_path, [entry])

    concerns = extract_reviewer_concerns("PR-010", kb_path)
    ids = [c["concern_id"] for c in concerns]
    assert ids == ["PR-010-C01", "PR-010-C02"]


# ────────────────────────────────────────────────────────────────────────
# extract_methods_text
# ────────────────────────────────────────────────────────────────────────


def test_extract_methods_text_via_kb_field(tmp_path):
    entry = _entry("PR-001")
    entry["methods_text"] = "We trained a model with 5-fold CV ..."
    _write_kb(tmp_path, [entry])

    text = extract_methods_text("PR-001", tmp_path)
    assert text.startswith("We trained a model")


def test_extract_methods_text_via_methods_extract_field(tmp_path):
    entry = _entry("PR-002")
    entry["methods_extract"] = "Alternative field name supported."
    _write_kb(tmp_path, [entry])

    text = extract_methods_text("PR-002", tmp_path)
    assert text == "Alternative field name supported."


def test_extract_methods_text_via_filesystem_fallback(tmp_path):
    # No methods_text on the entry -> must walk the filesystem layout.
    _write_kb(tmp_path, [_entry("PR-050", journal="Nature Communications")])
    paper_dir = tmp_path / "nature_communications" / "PR-050"
    paper_dir.mkdir(parents=True)
    (paper_dir / "methods.txt").write_text("Methods from disk.", encoding="utf-8")

    text = extract_methods_text("PR-050", tmp_path)
    assert text == "Methods from disk."


def test_extract_methods_text_via_filesystem_prefixed_name(tmp_path):
    # <paper_id>_methods.md form (lower-precedence than methods.{txt,md}).
    _write_kb(tmp_path, [_entry("PR-060", journal="JAMA")])
    paper_dir = tmp_path / "jama" / "PR-060"
    paper_dir.mkdir(parents=True)
    (paper_dir / "PR-060_methods.md").write_text("# Methods\nbody",
                                                 encoding="utf-8")

    text = extract_methods_text("PR-060", tmp_path)
    assert "Methods" in text


def test_extract_methods_text_kb_field_wins_over_filesystem(tmp_path):
    # If both exist, the KB field is authoritative -- the methods.txt on
    # disk could be an older paste from a prior parse pass.
    entry = _entry("PR-070", journal="Nature Communications")
    entry["methods_text"] = "FROM_KB"
    _write_kb(tmp_path, [entry])
    paper_dir = tmp_path / "nature_communications" / "PR-070"
    paper_dir.mkdir(parents=True)
    (paper_dir / "methods.txt").write_text("FROM_DISK", encoding="utf-8")

    assert extract_methods_text("PR-070", tmp_path) == "FROM_KB"


def test_extract_methods_text_exhausted_raises(tmp_path):
    _write_kb(tmp_path, [_entry("PR-100", journal="Nature Communications")])
    # No methods_text on the entry, no methods.* file on disk.

    with pytest.raises(MethodsTextNotFound) as exc:
        extract_methods_text("PR-100", tmp_path)
    msg = str(exc.value)
    assert "PR-100" in msg
    # Error message should list what we tried (debuggability gate).
    assert "Filesystem candidates" in msg or "methods" in msg.lower()


def test_extract_methods_text_unknown_paper_raises_paper_not_found(tmp_path):
    _write_kb(tmp_path, [_entry("PR-001")])

    with pytest.raises(PaperNotFound):
        extract_methods_text("PR-999", tmp_path)


# ────────────────────────────────────────────────────────────────────────
# extract_for_holdout
# ────────────────────────────────────────────────────────────────────────


def test_extract_for_holdout_partial_failures_do_not_crash(tmp_path, caplog):
    # PR-001 has both concerns + methods_text -> success.
    # PR-002 has concerns but no methods anywhere -> per-paper skip.
    # PR-XXX is not in the KB at all -> per-paper skip.
    good = _entry("PR-001")
    good["methods_text"] = "ok"
    bad = _entry("PR-002")  # no methods_text, no fs file
    kb_path = _write_kb(tmp_path, [good, bad])

    with caplog.at_level(logging.WARNING):
        results = extract_for_holdout(["PR-001", "PR-002", "PR-XXX"], kb_path)

    assert set(results.keys()) == {"PR-001"}
    assert results["PR-001"]["methods_text"] == "ok"
    assert len(results["PR-001"]["concerns"]) == 2
    # Per-paper failures must surface in logs, not as exceptions.
    log_text = caplog.text
    assert "PR-002" in log_text
    assert "PR-XXX" in log_text


def test_extract_for_holdout_zero_success_raises(tmp_path):
    # All requested papers are missing from the KB -> degenerate run.
    kb_path = _write_kb(tmp_path, [_entry("PR-001")])

    with pytest.raises(RuntimeError) as exc:
        extract_for_holdout(["PR-998", "PR-999"], kb_path)
    assert "0 / 2" in str(exc.value)


def test_extract_for_holdout_all_success_no_failures_logged(tmp_path, caplog):
    e1 = _entry("PR-001"); e1["methods_text"] = "m1"
    e2 = _entry("PR-002"); e2["methods_text"] = "m2"
    kb_path = _write_kb(tmp_path, [e1, e2])

    with caplog.at_level(logging.WARNING):
        results = extract_for_holdout(["PR-001", "PR-002"], kb_path)
    assert set(results.keys()) == {"PR-001", "PR-002"}
    assert "skipped" not in caplog.text
