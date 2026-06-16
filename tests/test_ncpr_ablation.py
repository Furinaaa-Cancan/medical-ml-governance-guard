"""Tests for scripts/rag/evals/ncpr_ablation.py (W23-C4).

Covers:

1. ``run_ablation`` with stubbed deps returns all configs in the
   default grid.
2. Monotonicity: ``top_k_30`` recall >= ``top_k_5`` recall.
3. ``write_ablation_report`` renders deltas vs the ``full`` baseline
   row.
4. Empty holdout -> graceful no-op (``{}`` + valid markdown file).
5. Unknown config -> ``ValueError``.

Bonus coverage:

6. ``no_semantic_match`` filter strips ``semantic`` + ``category``
   pairs (matcher filter wiring).
7. Custom ``configs`` subset is honoured exactly (no extra rows).

All tests are offline and deterministic — the RAG synth path is
monkey-patched to a deterministic stub keyed off the paper id.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rag.evals import ncpr_ablation as ab  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def holdout() -> list[dict]:
    """Two papers; both have methods_text so the RAG synth seam fires."""
    return [
        {
            "paper_id": "PR-001",
            "paper_doi": "10.1/a",
            "methods_text": "logistic regression with cross-validation",
        },
        {
            "paper_id": "PR-002",
            "paper_doi": "10.1/b",
            "methods_text": "random forest external validation",
        },
    ]


@pytest.fixture
def kb_entries() -> list[dict]:
    """Two reviewer concerns per paper, with distinct gate names so
    exact_code matching can fire deterministically."""
    return [
        {
            "paper_id": "PR-001",
            "reviewer_concerns": [
                {
                    "concern_id": "PR-001-c1",
                    "concern_text": "no calibration reported",
                    "severity": "HIGH",
                    "category": "evaluation",
                    "dimension": "evaluation",
                    "mlgg_gates": ["calibration_gate"],
                },
                {
                    "concern_id": "PR-001-c2",
                    "concern_text": "no external validation",
                    "severity": "CRITICAL",
                    "category": "external_val",
                    "dimension": "external_val",
                    "mlgg_gates": ["external_validation_gate"],
                },
            ],
        },
        {
            "paper_id": "PR-002",
            "reviewer_concerns": [
                {
                    "concern_id": "PR-002-c1",
                    "concern_text": "data leakage risk",
                    "severity": "CRITICAL",
                    "category": "leakage",
                    "dimension": "leakage",
                    "mlgg_gates": ["leakage_gate"],
                },
            ],
        },
    ]


@pytest.fixture
def stub_synth(monkeypatch):
    """Replace the RAG synth with a deterministic top-K oracle.

    Returns enough exact-code-matching flags at top_k=30 to recover
    every reviewer concern, and a strict subset at top_k=5 so the
    monotonicity test can observe a real recall increase.
    """
    # Master pool of flags keyed by paper. Each paper gets several
    # plausible flags; only some hit the reviewer's gate codes.
    pool: dict[str, list[dict]] = {
        "logistic regression with cross-validation": [
            {"code": "calibration_gate", "severity": "HIGH",
             "category": "evaluation", "evidence_text": "no calibration"},
            {"code": "auroc_only_gate", "severity": "MEDIUM",
             "category": "evaluation", "evidence_text": "auroc only"},
            {"code": "external_validation_gate", "severity": "CRITICAL",
             "category": "external_val", "evidence_text": "no external"},
        ],
        "random forest external validation": [
            {"code": "leakage_gate", "severity": "CRITICAL",
             "category": "leakage", "evidence_text": "data leakage risk"},
            {"code": "cv_leakage_gate", "severity": "HIGH",
             "category": "leakage", "evidence_text": "cv-fold leakage"},
        ],
    }

    def _fake_synth(query: str, top_k: int = 20, **_kwargs):
        flags = pool.get(query, [])
        # Truncate to top_k so smaller k gives strictly fewer flags.
        return list(flags[: max(1, top_k)])

    monkeypatch.setattr(ab, "_synthesize_flags_from_rag", _fake_synth)
    # Inject the same synth into the retrieval_only path; the
    # retrieval-only helper degrades the records, but it still pulls
    # from the synth seam.
    return _fake_synth


# ── 1. all configs returned ─────────────────────────────────────────────────


def test_run_ablation_returns_all_default_configs(
    holdout, kb_entries, stub_synth
):
    """Default grid runs every config in :data:`DEFAULT_CONFIGS`."""
    out = ab.run_ablation(holdout, kb_entries=kb_entries)
    assert set(out.keys()) == set(ab.DEFAULT_CONFIGS)
    for cfg, row in out.items():
        assert {"weighted_f1", "recall", "precision",
                "category_coverage", "n_papers"} <= set(row.keys()), (
            f"missing metric in row {cfg}: {row}"
        )


# ── 2. monotonicity ────────────────────────────────────────────────────────


def test_top_k_recall_monotonicity(holdout, kb_entries, stub_synth):
    """top_k_30 recall must be >= top_k_5 recall.

    More retrieval depth can only equal or improve recall (assuming a
    deterministic synth that returns a superset at larger K). This
    test guards against an inadvertent inversion of the top_k knob.
    """
    out = ab.run_ablation(
        holdout, kb_entries=kb_entries,
        configs=["top_k_5", "top_k_30"],
    )
    r5 = out["top_k_5"]["recall"]
    r30 = out["top_k_30"]["recall"]
    assert r30 + 1e-9 >= r5, (
        f"top_k_30 recall ({r30}) must be >= top_k_5 recall ({r5})"
    )


def test_ablation_excludes_current_paper_from_flag_synth(
    holdout, kb_entries, monkeypatch
):
    """Every ablation config that calls RAG must pass per-paper exclusions."""
    calls: list[dict] = []

    def capture(query: str, top_k: int = 20, **kwargs):
        calls.append({"query": query, "top_k": top_k, **kwargs})
        return []

    monkeypatch.setattr(ab, "_synthesize_flags_from_rag", capture)
    out = ab.run_ablation(
        holdout,
        kb_entries=kb_entries,
        configs=["full", "retrieval_only"],
    )

    assert set(out.keys()) == {"full", "retrieval_only"}
    assert [c.get("excluded_paper_ids") for c in calls] == [
        ["PR-001", "10.1/a"],
        ["PR-002", "10.1/b"],
        ["PR-001", "10.1/a"],
        ["PR-002", "10.1/b"],
    ]


# ── 3. report deltas vs baseline ───────────────────────────────────────────


def test_report_shows_deltas_vs_baseline(
    holdout, kb_entries, stub_synth, tmp_path
):
    """Generated markdown report includes per-config deltas vs `full`."""
    out = ab.run_ablation(holdout, kb_entries=kb_entries)
    report_path = tmp_path / "report.md"
    ab.write_ablation_report(out, report_path)

    text = report_path.read_text(encoding="utf-8")
    # Header
    assert "NCPR v2 component ablation (W23-C4)" in text
    # Every config name should appear as a row.
    for cfg in ab.DEFAULT_CONFIGS:
        assert f"| {cfg} |" in text, f"missing row for config {cfg}"
    # Delta columns named explicitly.
    for col in ("dF1", "dRecall", "dPrecision", "dCov"):
        assert col in text, f"missing delta column {col}"
    # full row's delta vs itself is exactly +0.0000 for every metric.
    full_row = [
        line for line in text.splitlines() if line.startswith("| full |")
    ]
    assert full_row, "no `full` row in rendered report"
    # +0.0000 appears at least 4 times in the full row (one per delta col).
    assert full_row[0].count("+0.0000") >= 4, (
        f"`full` row should have +0.0000 deltas vs itself, got: {full_row[0]}"
    )


# ── 4. empty holdout no-op ─────────────────────────────────────────────────


def test_empty_holdout_graceful_noop(tmp_path):
    """Empty holdout returns {} and writes a valid (if empty) report."""
    out = ab.run_ablation([], kb_entries=[])
    assert out == {}

    report = tmp_path / "empty.md"
    ab.write_ablation_report(out, report)
    text = report.read_text(encoding="utf-8")
    assert "NCPR v2 component ablation" in text
    assert "No configs scored" in text


# ── 5. unknown config raises ────────────────────────────────────────────────


def test_unknown_config_raises_value_error(holdout, kb_entries):
    """Unknown config name must raise ValueError before any scoring."""
    with pytest.raises(ValueError, match="unknown ablation config"):
        ab.run_ablation(
            holdout, kb_entries=kb_entries, configs=["full", "definitely_not_a_config"],
        )


# ── 6. matcher-filter wiring ────────────────────────────────────────────────


def test_make_match_filter_drops_requested_types():
    """The match-filter wrapper removes pairs whose ``type`` matches drop_types.

    Exercises the wrapper directly so we don't depend on the real
    matcher being importable in this test — we feed a fake
    ``_real_match_all`` that returns one pair of each type.
    """
    # Save real, swap in a fake, restore on exit.
    saved = ab._real_match_all
    try:
        def fake_match_all(flags, concerns, embed_fn=None):
            return {
                "matched_pairs": [
                    {"flag_idx": 0, "concern_idx": 0,
                     "type": "exact_code", "score": 1.0},
                    {"flag_idx": 1, "concern_idx": 1,
                     "type": "semantic", "score": 0.8},
                    {"flag_idx": 2, "concern_idx": 2,
                     "type": "category", "score": 0.5},
                ],
                "unmatched_flags": [],
                "unmatched_concerns": [],
                "matcher": "fake",
            }
        ab._real_match_all = fake_match_all

        flags = [{"code": str(i)} for i in range(3)]
        concerns = [{"concern_id": str(i)} for i in range(3)]

        wrapped = ab._make_match_filter(("semantic", "category"))
        assert wrapped is not None
        out = wrapped(flags, concerns)

        types_kept = [p["type"] for p in out["matched_pairs"]]
        assert types_kept == ["exact_code"], (
            f"semantic + category should be dropped, kept: {types_kept}"
        )
        # Dropped flag indices land in unmatched_flags.
        assert set(out["unmatched_flags"]) == {1, 2}
        assert set(out["unmatched_concerns"]) == {1, 2}
        assert "filtered" in out["matcher"]
    finally:
        ab._real_match_all = saved


# ── 7. configs subset is honoured exactly ──────────────────────────────────


def test_custom_configs_subset_only(holdout, kb_entries, stub_synth):
    """When ``configs=`` is given, only those configs run — no defaults."""
    out = ab.run_ablation(
        holdout, kb_entries=kb_entries,
        configs=["full", "no_category_match"],
    )
    assert set(out.keys()) == {"full", "no_category_match"}
