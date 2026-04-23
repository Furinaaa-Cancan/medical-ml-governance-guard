"""Tests for scripts/diagnostics/kb_hygiene_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "kb_hygiene_check.py"


def _run(kb_path: Path, report: Path, *, strict: bool = False):
    cmd = [sys.executable, str(SCRIPT),
           "--kb", str(kb_path),
           "--report", str(report)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _write_kb(path: Path, entries: list, *, version: str = "test-1.0") -> None:
    path.write_text(json.dumps(
        {"contract_version": version,
         "total_papers": len(entries),
         "total_concerns": sum(len(e.get("reviewer_concerns", [])) for e in entries),
         "entries": entries}
    ), encoding="utf-8")


def _clean_concern(**over) -> dict:
    base = {
        "concern_id": "PR-TEST-C01",
        "mlgg_gates": ["leakage_gate"],
        "category": "data_leakage",
        "severity": "HIGH",
        "mlgg_rules": ["F01"],
        "concern_text": "x",
    }
    base.update(over)
    return base


def _paper(concern: dict) -> dict:
    return {
        "id": "PR-TEST",
        "paper_doi": "10.1000/test",
        "journal": "Nature Communications",
        "year": 2026,
        "reviewer_concerns": [concern],
    }


# ── IO gate ──────────────────────────────────────────────────────────

class TestGateIOGuards:
    def test_missing_kb_fails(self, tmp_path: Path):
        r = _run(tmp_path / "nope.json", tmp_path / "r.json")
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        assert "kb_not_found" in [f["code"] for f in out["failures"]]

    def test_invalid_json_fails(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        kb.write_text("{not json", encoding="utf-8")
        r = _run(kb, tmp_path / "r.json")
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        assert "kb_invalid_json" in [f["code"] for f in out["failures"]]

    def test_missing_entries_fails(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        kb.write_text(json.dumps({"version": "x"}), encoding="utf-8")
        r = _run(kb, tmp_path / "r.json")
        assert r.returncode == 2


# ── Hygiene validations ──────────────────────────────────────────────

class TestHygieneChecks:
    def test_clean_kb_passes_strict(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern())])
        r = _run(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["total_violations"] == 0

    def test_unknown_gate_ref_is_warning(self, tmp_path: Path):
        """The exact class of bug Codex found today: mlgg_gates
        contains a gate name that isn't registered. retrieve_by_gate()
        returns empty for these, so the citation is lost silently."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(
            mlgg_gates=["leakage_gate", "reporting_compliance_gate"],
        ))])
        # Lenient mode: exit 0, but warning must be present.
        r = _run(kb, tmp_path / "r.json", strict=False)
        assert r.returncode == 0
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "invalid_gate_ref" in codes
        assert out["summary"]["invalid_gate_refs"] == 1
        # Strict mode: must fail.
        r = _run(kb, tmp_path / "r2.json", strict=True)
        assert r.returncode == 2

    def test_bare_rule_name_in_gates_caught(self, tmp_path: Path):
        """Regression: PR-111-C02 had the bare string 'reproducibility'
        (a category) inside mlgg_gates. That's also an invalid gate
        reference."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(
            mlgg_gates=["reproducibility"],
        ))])
        r = _run(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "invalid_gate_ref" in codes

    def test_out_of_allowlist_category_caught(self, tmp_path: Path):
        """Regression: PR-114-C03 had category='cohort_definition'
        which isn't in the 13-category allowlist (should be
        'study_design')."""
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(category="cohort_definition"))])
        r = _run(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "invalid_category" in codes

    def test_invalid_severity_caught(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(severity="high"))])  # lowercase
        r = _run(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "invalid_severity" in codes

    def test_invalid_rule_id_caught(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(
            mlgg_rules=["not-a-rule", "MLGG-X01", "M01"],  # first is bad
        ))])
        r = _run(kb, tmp_path / "r.json", strict=True)
        assert r.returncode == 2
        out = json.loads((tmp_path / "r.json").read_text())
        codes = [w["code"] for w in out["warnings"]]
        assert "invalid_rule_id" in codes
        # MLGG-X01 and M01 should pass → only 1 violation
        assert out["summary"]["invalid_rule_ids"] == 1

    def test_multiple_violations_tallied(self, tmp_path: Path):
        kb = tmp_path / "kb.json"
        _write_kb(kb, [_paper(_clean_concern(
            mlgg_gates=["bad_gate1", "bad_gate2"],
            category="no_such_category",
            severity="???",
            mlgg_rules=["junk"],
        ))])
        r = _run(kb, tmp_path / "r.json", strict=False)
        assert r.returncode == 0  # lenient
        out = json.loads((tmp_path / "r.json").read_text())
        s = out["summary"]
        assert s["invalid_gate_refs"] == 2
        assert s["invalid_categories"] == 1
        assert s["invalid_severities"] == 1
        assert s["invalid_rule_ids"] == 1
        assert s["total_violations"] == 5


# ── Real KB smoke test ───────────────────────────────────────────────

class TestRealKB:
    """After today's cleanup commits, the production KB must be clean
    under --strict. This pins that invariant so any future pollution
    will be caught at pre-commit / CI time instead of during a
    review audit."""

    KB_PATH = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

    @pytest.mark.skipif(not KB_PATH.exists(),
                        reason="Production peer-review-kb missing")
    def test_production_kb_clean(self, tmp_path: Path):
        r = _run(self.KB_PATH, tmp_path / "r.json", strict=True)
        assert r.returncode == 0, (
            "peer-review-kb regressed — run scripts/diagnostics/"
            "kb_hygiene_check.py --strict for details.\n"
            + r.stdout + r.stderr
        )
        out = json.loads((tmp_path / "r.json").read_text())
        assert out["summary"]["total_violations"] == 0
        # Sanity: catch a future schema breakage that would silently
        # zero the counters.
        assert out["summary"]["total_papers"] >= 100
        assert out["summary"]["total_concerns"] >= 100
