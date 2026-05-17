"""W20-F2 / W17-C2 SPOOF-C regression tests.

The disease-KB review gate used to accept ANY non-empty string for
`provenance.last_reviewed`. That meant a one-line JSON edit setting
`last_reviewed: "2099-01-01"` (or even `"tomorrow"`) sailed past the
publication gate alongside a valid status + reviewer. These tests pin
the date-validation contract: ISO-8601 only, must fall in
[1990-01-01, today].
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "scripts" / "diagnostics" / "disease_kb_review_check.py"


def _write_kb(path: Path, diseases: dict, *, version: str = "1.0") -> None:
    path.write_text(
        json.dumps({"version": version, "diseases": diseases}),
        encoding="utf-8",
    )


def _run_check(kb_path: Path, report_path: Path, *, strict: bool = False):
    cmd = [sys.executable, str(CHECK),
           "--kb", str(kb_path),
           "--report", str(report_path)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _approved_entry(last_reviewed: str) -> dict:
    """Otherwise-valid approved entry parameterized on last_reviewed."""
    return {
        "name": "Test Disease",
        "provenance": {
            "source": "clinician_reviewed",
            "clinician_review_status": "clinician_reviewed",
            "reviewer": "Dr. Test",
            "last_reviewed": last_reviewed,
            "reviewed_against": ["ADA 2024"],
        },
    }


class TestLastReviewedDateValidation:
    def test_future_date_rejected(self, tmp_path: Path):
        """SPOOF-C: status+reviewer+future-date must NOT bypass the gate."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, {"d1": _approved_entry("2099-01-01")})
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2, "Future last_reviewed must fail in strict mode"
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 0
        assert out["summary"]["missing_provenance_count"] == 1
        codes = [w["code"] for w in out["warnings"]]
        assert "clinician_review_provenance_missing" in codes

    def test_pre_1990_rejected(self, tmp_path: Path):
        """Dates predating modern EHR/MLGG era are almost certainly errors."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, {"d1": _approved_entry("1985-06-01")})
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 0
        assert out["summary"]["missing_provenance_count"] == 1

    def test_gibberish_date_rejected(self, tmp_path: Path):
        """Non-ISO strings must be rejected, not crash, not pass."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, {"d1": _approved_entry("tomorrow")})
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2, f"stderr was: {r.stderr}"
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 0
        assert out["summary"]["missing_provenance_count"] == 1

    def test_valid_recent_date_still_passes(self, tmp_path: Path):
        """Regression: legitimate recent ISO-8601 dates must still be accepted."""
        recent = (date.today() - timedelta(days=7)).isoformat()
        kb = tmp_path / "kb.json"
        _write_kb(kb, {"d1": _approved_entry(recent)})
        r = _run_check(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 0, (
            f"Valid recent date {recent} should pass strict mode; "
            f"stderr={r.stderr}"
        )
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["approved_count"] == 1
        assert out["summary"]["missing_provenance_count"] == 0
