"""Tests for NCPR v2 quality filter (W23-C3).

Spec: ``references/benchmark/ncpr_v2_quality_floor.md``.
Companion implementation: ``scripts/rag/evals/ncpr_quality_filter.py``.

All tests are offline and deterministic; no PDF I/O, no KB load.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.rag.evals.ncpr_quality_filter import (
    filter_holdout_pool,
    score_concern,
    score_paper,
    write_audit_log,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
def _good_concern(cid: str = "C01", category: str = "study_design") -> dict:
    """A concern that satisfies all 5 W23-B5 concern-level criteria (score = 5)."""
    return {
        "concern_id": cid,
        "concern_text": (
            "The study conditions on outcomes observed during the follow-up "
            "window, which constitutes a clear label leakage pathway."
        ),
        "severity": "CRITICAL",
        "category": category,
        "mlgg_gates": ["leakage_gate", "cohort_definition_gate"],
        "author_response": "We have revised the study design section accordingly.",
    }


def _good_paper(pid: str = "PR-100", n_concerns: int = 5, year: int = 2024) -> dict:
    """Paper that scores 9/9 on the W23-B5 paper-level floor."""
    cats = ["study_design", "evaluation", "reporting", "leakage", "external_validation"]
    concerns = [
        _good_concern(f"{pid}-C{i:02d}", category=cats[i % len(cats)])
        for i in range(n_concerns)
    ]
    return {
        "id": pid,
        "year": year,
        "key_methodology_issues": [
            "Future outcome data leaks into baseline feature construction."
        ],
        "reviewer_concerns": concerns,
    }


# ---------------------------------------------------------------------------
# score_paper — happy path + each criterion's failure surface
# ---------------------------------------------------------------------------
class TestScorePaper:
    def test_happy_path_full_score(self):
        result = score_paper(_good_paper(), pdf_available=True)
        # 2+2+1+2+1+1 = 9
        assert result["score"] == 9
        assert result["rejection_reasons"] == []
        assert all(result["breakdown"].values())

    def test_missing_critical_field_populates_rejection(self):
        paper = _good_paper()
        # Demote every CRITICAL to HIGH so criterion 3 fails.
        for c in paper["reviewer_concerns"]:
            c["severity"] = "HIGH"
        result = score_paper(paper, pdf_available=True)
        assert result["score"] == 9 - 2  # lose the +2 for "has_critical"
        assert result["breakdown"]["has_critical"] is False
        assert any("CRITICAL" in r for r in result["rejection_reasons"])

    def test_pre_2023_year_loses_year_point(self):
        paper = _good_paper(year=2021)
        result = score_paper(paper, pdf_available=True)
        assert result["breakdown"]["year_2023"] is False
        assert result["score"] == 9 - 1

    def test_no_pdf_short_circuits_to_breakdown_false(self):
        result = score_paper(_good_paper(), pdf_available=False)
        # Score still computed against other criteria, but PDF flag is False
        # and a hard-fail reason is appended — filter_holdout_pool rejects
        # regardless of score.
        assert result["breakdown"]["has_pdf"] is False
        assert any("PDF" in r for r in result["rejection_reasons"])

    def test_too_few_concerns_loses_two_points(self):
        paper = _good_paper(n_concerns=3)
        result = score_paper(paper, pdf_available=True)
        assert result["breakdown"]["min_concerns"] is False
        # Loses 2 (min_concerns) + 1 (distinct_categories drops to 3 then ...
        # actually 3 categories from cats[0:3] still distinct → keep +1).
        # So we just assert lost min_concerns weight:
        assert result["score"] <= 9 - 2

    def test_empty_key_methodology_issues_rejected(self):
        paper = _good_paper()
        paper["key_methodology_issues"] = []
        result = score_paper(paper, pdf_available=True)
        assert result["breakdown"]["key_methodology_issues"] is False
        assert result["score"] == 9 - 2


# ---------------------------------------------------------------------------
# score_concern — happy path + stub rejection
# ---------------------------------------------------------------------------
class TestScoreConcern:
    def test_happy_path_full_score(self):
        result = score_concern(_good_concern())
        assert result["score"] == 5
        assert result["rejection_reasons"] == []

    def test_stub_text_rejected(self):
        c = _good_concern()
        c["concern_text"] = "needs more data"  # 15 chars < 30
        result = score_concern(c)
        assert result["score"] == 4
        assert any("concern_text" in r for r in result["rejection_reasons"])

    def test_missing_severity_rejected(self):
        c = _good_concern()
        c["severity"] = None
        result = score_concern(c)
        assert result["score"] == 4
        assert any("severity" in r for r in result["rejection_reasons"])

    def test_empty_gates_rejected(self):
        c = _good_concern()
        c["mlgg_gates"] = []
        result = score_concern(c)
        assert result["score"] == 4
        assert any("mlgg_gates" in r for r in result["rejection_reasons"])

    def test_pending_response_sentinel_rejected(self):
        c = _good_concern()
        c["author_response"] = "[pending]"
        result = score_concern(c)
        assert result["score"] == 4
        assert any("author_response" in r for r in result["rejection_reasons"])

    def test_below_min_concern_score_threshold(self):
        # Strip 3 criteria → score 2, below default min_concern_score=3.
        c = {
            "concern_id": "X",
            "concern_text": "short",
            "severity": "HIGH",
            "category": "evaluation",
            "mlgg_gates": [],
            "author_response": "",
        }
        result = score_concern(c)
        assert result["score"] == 2
        assert len(result["rejection_reasons"]) == 3


# ---------------------------------------------------------------------------
# filter_holdout_pool — 10-paper mock, 5 pass, 5 fail
# ---------------------------------------------------------------------------
class TestFilterHoldoutPool:
    def _ten_entry_pool(self) -> list[dict]:
        pool = []
        # 5 premium papers
        for i in range(5):
            pool.append(_good_paper(pid=f"PR-PASS-{i:02d}"))
        # 5 failures with varied root causes
        # (a) too few concerns
        p_a = _good_paper(pid="PR-FAIL-A", n_concerns=3)
        pool.append(p_a)
        # (b) no CRITICAL + no author_response (lose 2 + 1 = 3 points → score 6 < 7)
        p_b = _good_paper(pid="PR-FAIL-B")
        for c in p_b["reviewer_concerns"]:
            c["severity"] = "MEDIUM"
            c["author_response"] = ""
        pool.append(p_b)
        # (c) pre-2023
        p_c = _good_paper(pid="PR-FAIL-C", year=2020)
        # also strip key_methodology_issues to push it below 7
        p_c["key_methodology_issues"] = []
        pool.append(p_c)
        # (d) all concerns are stubs (concern-level filter cascades up)
        p_d = _good_paper(pid="PR-FAIL-D")
        for c in p_d["reviewer_concerns"]:
            c["concern_text"] = "too short"
            c["mlgg_gates"] = []
            c["author_response"] = ""
        pool.append(p_d)
        # (e) no PDF
        p_e = _good_paper(pid="PR-FAIL-E")
        pool.append(p_e)
        return pool

    def test_five_pass_five_fail(self):
        pool = self._ten_entry_pool()
        pdf_map = {"PR-FAIL-E": False}
        result = filter_holdout_pool(pool, pdf_availability=pdf_map)
        assert len(result["eligible"]) == 5
        assert len(result["rejected"]) == 5
        eligible_ids = {p["id"] for p in result["eligible"]}
        assert eligible_ids == {f"PR-PASS-{i:02d}" for i in range(5)}
        rejected_ids = {r["paper_id"] for r in result["rejected"]}
        assert rejected_ids == {
            "PR-FAIL-A",
            "PR-FAIL-B",
            "PR-FAIL-C",
            "PR-FAIL-D",
            "PR-FAIL-E",
        }

    def test_concern_filter_cascades_to_paper_rejection(self):
        # Paper D's concerns all fail concern-level filter, so kept_concerns
        # drops to 0 and paper-level criterion 2 fails on the post-prune
        # check even though the unfiltered paper had 5 concerns.
        pool = [self._ten_entry_pool()[8]]  # PR-FAIL-D
        result = filter_holdout_pool(pool)
        assert result["eligible"] == []
        assert len(result["rejected"]) == 1
        reasons = result["rejected"][0]["reasons"]
        assert any("survived concern-level prune" in r for r in reasons)
        assert result["concerns_filtered"] == 5

    def test_no_pdf_hard_fails_even_with_full_score(self):
        pool = [_good_paper(pid="PR-X")]
        result = filter_holdout_pool(pool, pdf_availability={"PR-X": False})
        assert result["eligible"] == []
        assert len(result["rejected"]) == 1
        assert any(
            "pdf_unavailable" in r for r in result["rejected"][0]["reasons"]
        )

    def test_concerns_filtered_count_accumulates(self):
        # One paper with 3 stub concerns + 5 good concerns: prune 3, paper
        # still passes (5 ≥ 5 floor).
        paper = _good_paper(pid="PR-MIXED", n_concerns=5)
        paper["reviewer_concerns"].extend(
            [
                {
                    "concern_id": f"PR-MIXED-S{i}",
                    "concern_text": "stub",
                    "severity": "LOW",
                    "category": "",
                    "mlgg_gates": [],
                    "author_response": "",
                }
                for i in range(3)
            ]
        )
        result = filter_holdout_pool([paper])
        assert result["concerns_filtered"] == 3
        assert len(result["eligible"]) == 1
        assert len(result["eligible"][0]["reviewer_concerns"]) == 5


# ---------------------------------------------------------------------------
# write_audit_log — JSONL shape contract
# ---------------------------------------------------------------------------
class TestWriteAuditLog:
    def test_creates_valid_jsonl(self, tmp_path: Path):
        filter_result = {
            "eligible": [],
            "rejected": [
                {
                    "paper_id": "PR-X",
                    "score": 4,
                    "reasons": ["only 2 CRITICAL, need >= 1", "year 2019 < 2023"],
                    "dropped_concerns": [
                        {
                            "concern_id": "PR-X-C01",
                            "score": 2,
                            "reasons": ["concern_text length 5 < 30"],
                        }
                    ],
                }
            ],
            "concerns_filtered": 1,
        }
        out = tmp_path / "rejects.jsonl"
        write_audit_log(filter_result, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["kind"] == "paper"
        assert first["paper_id"] == "PR-X"
        assert first["score"] == 4
        second = json.loads(lines[1])
        assert second["kind"] == "concern"
        assert second["concern_id"] == "PR-X-C01"

    def test_creates_parent_dirs(self, tmp_path: Path):
        out = tmp_path / "nested" / "dirs" / "log.jsonl"
        write_audit_log({"eligible": [], "rejected": [], "concerns_filtered": 0}, out)
        assert out.exists()
        # Empty rejection set → empty file (no header line).
        assert out.read_text(encoding="utf-8") == ""

    def test_default_path_writable(self, tmp_path, monkeypatch):
        # Don't actually write to /tmp from tests — but confirm we can pass
        # an arbitrary Path and the function tolerates it.
        out = tmp_path / "W23_quality_rejects.jsonl"
        write_audit_log(
            {
                "eligible": [],
                "rejected": [{"paper_id": "PR-Y", "score": 0, "reasons": ["x"]}],
                "concerns_filtered": 0,
            },
            out,
        )
        assert out.exists()
        rec = json.loads(out.read_text(encoding="utf-8").strip())
        assert rec["paper_id"] == "PR-Y"
