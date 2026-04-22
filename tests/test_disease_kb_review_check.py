"""Tests for scripts/diagnostics/disease_kb_review_check.py and
scripts/diagnostics/generate_disease_kb_review_sheets.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "scripts" / "diagnostics" / "disease_kb_review_check.py"
GEN = REPO_ROOT / "scripts" / "diagnostics" / "generate_disease_kb_review_sheets.py"


def _write_kb(path: Path, diseases: dict, *, version: str = "1.0") -> None:
    kb = {"version": version, "diseases": diseases}
    path.write_text(json.dumps(kb), encoding="utf-8")


def _run_check(kb_path: Path, report_path: Path, *, strict: bool = False):
    cmd = [sys.executable, str(CHECK),
           "--kb", str(kb_path),
           "--report", str(report_path)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ── Gate — missing / invalid KB ───────────────────────────────────────

class TestGateIOGuards:
    def test_missing_kb_fails(self, tmp_path: Path):
        report = tmp_path / "r.json"
        r = _run_check(tmp_path / "nope.json", report)
        assert r.returncode == 2
        out = json.loads(report.read_text())
        assert "kb_not_found" in [f["code"] for f in out["failures"]]

    def test_invalid_json_fails(self, tmp_path: Path):
        kb = tmp_path / "bad.json"
        kb.write_text("{bad", encoding="utf-8")
        report = tmp_path / "r.json"
        r = _run_check(kb, report)
        assert r.returncode == 2
        out = json.loads(report.read_text())
        assert "kb_invalid_json" in [f["code"] for f in out["failures"]]

    def test_empty_diseases_block_fails(self, tmp_path: Path):
        kb = tmp_path / "empty.json"
        _write_kb(kb, {})
        report = tmp_path / "r.json"
        r = _run_check(kb, report)
        assert r.returncode == 2
        out = json.loads(report.read_text())
        assert "kb_missing_diseases_block" in [f["code"] for f in out["failures"]]


# ── Gate — review-status semantics ────────────────────────────────────

class TestReviewStatus:
    def test_all_pending_passes_lenient_fails_strict(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "d1": {"name": "D1",
                   "provenance": {"source": "llm_compiled",
                                  "clinician_review_status": "pending"}},
            "d2": {"name": "D2",
                   "provenance": {"source": "llm_compiled",
                                  "clinician_review_status": "pending"}},
        })
        report = tmp_path / "r.json"

        # lenient: warnings but pass
        r = _run_check(kb, report, strict=False)
        assert r.returncode == 0
        out = json.loads(report.read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert codes.count("clinician_review_pending") == 2
        assert out["summary"]["pending_count"] == 2
        assert out["summary"]["approved_count"] == 0

        # strict: same warnings, but exit 2
        r = _run_check(kb, report, strict=True)
        assert r.returncode == 2

    def test_all_approved_passes_strict(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "d1": {"name": "D1",
                   "provenance": {"source": "clinician_reviewed",
                                  "clinician_review_status": "clinician_reviewed",
                                  "reviewer": "Dr. A",
                                  "last_reviewed": "2026-04-21",
                                  "reviewed_against": ["ADA 2024"]}},
        })
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 0
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 1
        assert out["summary"]["pending_count"] == 0

    def test_missing_provenance_is_warning(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "d1": {"name": "D1"},   # no provenance block at all
        })
        r = _run_check(kb, tmp_path / "r.json", strict=False)
        assert r.returncode == 0   # lenient
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "clinician_review_provenance_missing" in codes
        assert out["summary"]["missing_provenance_count"] == 1

    def test_alternate_approved_statuses_recognised(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "d1": {"name": "D1",
                   "provenance": {"source": "llm_compiled",
                                  "clinician_review_status": "approved"}},
            "d2": {"name": "D2",
                   "provenance": {"source": "signed_off"}},
            "d3": {"name": "D3",
                   "provenance": {"source": "llm_compiled",
                                  "clinician_review_status": "specialist_reviewed"}},
        })
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 0
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 3

    def test_pending_status_overrides_stale_approved_source(self, tmp_path: Path):
        """Regression: OR-logic bug let 'source: clinician_reviewed' mask an
        in-flight 'status: pending'. Status must win when explicitly pending.
        """
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "d1": {"name": "D1",
                   "provenance": {"source": "clinician_reviewed",
                                  "clinician_review_status": "pending"}},
            "d2": {"name": "D2",
                   "provenance": {"source": "signed_off",
                                  "clinician_review_status": "under_review"}},
        })
        r = _run_check(kb, tmp_path / "r.json", strict=False)
        assert r.returncode == 0
        s = json.loads((tmp_path / "r.json").read_text())["summary"]
        assert s["approved_count"] == 0, \
            "source=clinician_reviewed with status=pending must NOT count as approved"
        assert s["pending_count"] == 2
        # Strict mode must fail on pending.
        r = _run_check(kb, tmp_path / "r2.json", strict=True)
        assert r.returncode == 2

    def test_mixed_state_reports_counts(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "good": {"name": "G",
                     "provenance": {"source": "clinician_reviewed"}},
            "bad": {"name": "B",
                    "provenance": {"source": "llm_compiled",
                                   "clinician_review_status": "pending"}},
            "ugly": {"name": "U"},   # missing provenance
        })
        r = _run_check(kb, tmp_path / "r.json", strict=False)
        assert r.returncode == 0
        s = json.loads((tmp_path / "r.json").read_text())["summary"]
        assert s["approved_count"] == 1
        assert s["pending_count"] == 1
        assert s["missing_provenance_count"] == 1
        assert s["approved_diseases"] == ["good"]
        assert s["pending_diseases"] == ["bad"]


# ── Gate — real KB smoke test ─────────────────────────────────────────

class TestRealKB:
    """Shipping KB should have all 11 diseases pending today; this test
    pins that baseline so a future clinician sign-off flips it."""

    KB_PATH = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"

    @pytest.mark.skipif(not KB_PATH.exists(), reason="Production KB missing")
    def test_current_kb_has_all_pending(self, tmp_path: Path):
        r = _run_check(self.KB_PATH, tmp_path / "r.json", strict=False)
        assert r.returncode == 0   # lenient passes
        s = json.loads((tmp_path / "r.json").read_text())["summary"]
        assert s["total_diseases"] == 11
        # All llm_compiled today; this assertion will need to be relaxed
        # as clinicians sign off diseases.
        assert s["pending_count"] + s["approved_count"] + s["missing_provenance_count"] == 11
        assert s["pending_count"] >= 1, (
            "If all 11 are approved, update this test and mark it as "
            "regression guard for never-backsliding."
        )

    @pytest.mark.skipif(not KB_PATH.exists(), reason="Production KB missing")
    def test_current_kb_fails_strict(self, tmp_path: Path):
        r = _run_check(self.KB_PATH, tmp_path / "r.json", strict=True)
        assert r.returncode == 2, (
            "Until all 11 diseases are clinician-reviewed, --strict "
            "(publication-grade) must fail-closed."
        )


# ── Scaffold generator ───────────────────────────────────────────────

class TestScaffoldGenerator:
    def test_generates_one_sheet_per_disease(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "t2d": {"name": "Type 2 Diabetes",
                    "icd10": ["E11"],
                    "medications": ["metformin"],
                    "provenance": {"source": "llm_compiled",
                                   "clinician_review_status": "pending"}},
            "htn": {"name": "Hypertension",
                    "icd10": ["I10"],
                    "provenance": {"source": "llm_compiled",
                                   "clinician_review_status": "pending"}},
        }, version="test-0.1")
        out_dir = tmp_path / "sheets"

        r = subprocess.run(
            [sys.executable, str(GEN),
             "--kb", str(kb), "--output-dir", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stdout + r.stderr

        files = sorted(p.name for p in out_dir.iterdir())
        assert "t2d_review.md" in files
        assert "htn_review.md" in files
        assert "INDEX.md" in files

        sheet = (out_dir / "t2d_review.md").read_text()
        assert "Type 2 Diabetes" in sheet
        assert "E11" in sheet
        assert "metformin" in sheet
        assert "test-0.1" in sheet
        # Sign-off placeholder present
        assert "(to be filled)" in sheet

    def test_force_flag_overwrites_signed_off_sheet(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, {
            "t2d": {"name": "Type 2 Diabetes",
                    "icd10": ["E11"],
                    "provenance": {"source": "llm_compiled",
                                   "clinician_review_status": "pending"}},
        })
        out_dir = tmp_path / "sheets"
        out_dir.mkdir()
        # Pre-create a "signed-off" sheet without placeholders
        sheet_path = out_dir / "t2d_review.md"
        sheet_path.write_text(
            "Reviewer: Dr. X\nDate: 2026-01-01\nAll verified.\n",
            encoding="utf-8",
        )

        # Without --force: preserve
        r = subprocess.run(
            [sys.executable, str(GEN),
             "--kb", str(kb), "--output-dir", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0
        assert "Dr. X" in sheet_path.read_text()

        # With --force: overwrite
        r = subprocess.run(
            [sys.executable, str(GEN),
             "--kb", str(kb), "--output-dir", str(out_dir), "--force"],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0
        assert "(to be filled)" in sheet_path.read_text()

    def test_missing_kb_exits_nonzero(self, tmp_path: Path):
        r = subprocess.run(
            [sys.executable, str(GEN),
             "--kb", str(tmp_path / "nope.json"),
             "--output-dir", str(tmp_path / "out")],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode != 0
        assert "not found" in r.stderr.lower()
