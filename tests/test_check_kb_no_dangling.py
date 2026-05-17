"""Tests for scripts/diagnostics/check_kb_no_dangling.py (W20-C3 / W17-C5).

Coverage:
* Clean KB + clean external refs → exit 0.
* Synthetic dangling ref → exit 2, named in output.
* External ref to a soft-deprecated (but still-present) concern → OK.
* Empty external artifacts → exit 0.
* Regex extracts concern_ids from both YAML and JSON inputs.
* load_kb_concern_ids includes deprecated concerns (tombstones still count).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# scripts/diagnostics is on sys.path via tests/conftest.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "diagnostics" / "check_kb_no_dangling.py"


def _write_kb(path: Path, concern_ids):
    """Write a minimal KB with the given concern_ids (all active)."""
    kb = {
        "contract_version": "peer_review_kb.v1.4",
        "entries": [
            {
                "id": f"PR-{i:03d}",
                "reviewer_concerns": [
                    {
                        "concern_id": cid,
                        "concern_text": "synthetic",
                        "severity": "HIGH",
                        "mlgg_gates": ["leakage_gate"],
                    }
                ],
            }
            for i, cid in enumerate(concern_ids, start=1)
        ],
    }
    path.write_text(json.dumps(kb))


def _write_eval_set(path: Path, concern_ids):
    """Write a minimal rag-eval-set.yaml-style file (regex-scanned, not parsed)."""
    lines = [
        "version: 1",
        "cases:",
        "  - id: test_case",
        "    gate: leakage_gate",
        "    issue_codes: [foo]",
        f"    relevant_concern_ids: [{', '.join(concern_ids)}]",
    ]
    path.write_text("\n".join(lines) + "\n")


def _write_scenarios(path: Path, payload):
    """Write a minimal scenarios.json (regex-scanned via json.dumps)."""
    path.write_text(json.dumps(payload))


def _run_checker(kb, eval_set, scenarios, report=None):
    cmd = [
        sys.executable,
        str(CHECKER),
        "--kb", str(kb),
        "--eval-set", str(eval_set),
        "--scenarios", str(scenarios),
    ]
    if report:
        cmd += ["--report", str(report)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ──────────────────────────────────────────────────────────────────────────
# Direct-call tests (faster, no subprocess)
# ──────────────────────────────────────────────────────────────────────────


def test_load_kb_concern_ids_includes_deprecated(tmp_path):
    """Soft-deprecated tombstones still occupy concern_id slots."""
    from check_kb_no_dangling import load_kb_concern_ids

    kb_path = tmp_path / "kb.json"
    kb = {
        "entries": [
            {
                "id": "PR-001",
                "reviewer_concerns": [
                    {
                        "concern_id": "PR-001-C01",
                        "concern_text": "active",
                        "severity": "HIGH",
                        "mlgg_gates": [],
                    },
                    {
                        "concern_id": "PR-001-C02",
                        "concern_text": "tombstoned",
                        "severity": "LOW",
                        "mlgg_gates": [],
                        "deprecated": True,
                        "deprecated_at": "2026-05-17",
                        "deprecated_reason": "merged",
                    },
                ],
            }
        ]
    }
    kb_path.write_text(json.dumps(kb))
    ids = load_kb_concern_ids(kb_path)
    assert ids == {"PR-001-C01", "PR-001-C02"}


def test_collect_external_refs_regex_finds_inline_yaml(tmp_path):
    from check_kb_no_dangling import collect_external_refs

    eval_set = tmp_path / "eval.yaml"
    _write_eval_set(eval_set, ["PR-001-C01", "PR-002-C03"])
    scenarios = tmp_path / "scenarios.json"
    _write_scenarios(scenarios, {"scenarios": []})

    refs = collect_external_refs(eval_set_path=eval_set, scenarios_path=scenarios)
    assert set(refs.keys()) == {"PR-001-C01", "PR-002-C03"}


def test_collect_external_refs_dedupes_sources(tmp_path):
    """A repeated concern_id in the same file only lists the source once."""
    from check_kb_no_dangling import collect_external_refs

    eval_set = tmp_path / "eval.yaml"
    eval_set.write_text(
        "cases:\n"
        "  - relevant_concern_ids: [PR-040-C01]\n"
        "  - relevant_concern_ids: [PR-040-C01]\n"
    )
    refs = collect_external_refs(eval_set_path=eval_set, scenarios_path=None)
    assert refs["PR-040-C01"].count(str(eval_set.resolve())) <= 1 or len(refs["PR-040-C01"]) == 1


def test_find_dangling_returns_empty_on_clean(tmp_path):
    from check_kb_no_dangling import find_dangling

    dangling = find_dangling(
        kb_ids={"PR-001-C01", "PR-002-C01"},
        external_refs={"PR-001-C01": ["a.yaml"]},
    )
    assert dangling == []


def test_find_dangling_flags_missing_concern(tmp_path):
    from check_kb_no_dangling import find_dangling

    dangling = find_dangling(
        kb_ids={"PR-001-C01"},
        external_refs={
            "PR-001-C01": ["a.yaml"],
            "PR-040-C01": ["b.yaml", "c.json"],
        },
    )
    assert dangling == [("PR-040-C01", ["b.yaml", "c.json"])]


# ──────────────────────────────────────────────────────────────────────────
# End-to-end subprocess tests (exit codes are part of the contract)
# ──────────────────────────────────────────────────────────────────────────


def test_checker_exits_zero_on_clean_fixture(tmp_path):
    kb = tmp_path / "kb.json"
    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"

    _write_kb(kb, ["PR-001-C01", "PR-002-C01"])
    _write_eval_set(eval_set, ["PR-001-C01"])
    _write_scenarios(scenarios, {"scenarios": []})

    result = _run_checker(kb, eval_set, scenarios)
    assert result.returncode == 0, (
        f"expected exit 0 on clean fixture, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_checker_exits_two_on_synthetic_dangling(tmp_path):
    kb = tmp_path / "kb.json"
    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"

    # KB has only PR-001-C01; eval-set references the missing PR-040-C01.
    _write_kb(kb, ["PR-001-C01"])
    _write_eval_set(eval_set, ["PR-001-C01", "PR-040-C01"])
    _write_scenarios(scenarios, {"scenarios": []})

    result = _run_checker(kb, eval_set, scenarios)
    assert result.returncode == 2, (
        f"expected exit 2 on dangling ref, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "PR-040-C01" in result.stdout
    assert "soft-deprecate" in result.stdout.lower()


def test_checker_accepts_ref_to_soft_deprecated_concern(tmp_path):
    """A deprecated-but-still-present concern is a valid target."""
    kb_path = tmp_path / "kb.json"
    kb = {
        "entries": [
            {
                "id": "PR-040",
                "reviewer_concerns": [
                    {
                        "concern_id": "PR-040-C01",
                        "concern_text": "External validation note.",
                        "severity": "HIGH",
                        "mlgg_gates": ["external_validation_gate"],
                        "deprecated": True,
                        "deprecated_at": "2026-05-17",
                        "deprecated_reason": "Paper has fabricated DOI; retained as tombstone.",
                    }
                ],
            }
        ]
    }
    kb_path.write_text(json.dumps(kb))

    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"
    _write_eval_set(eval_set, ["PR-040-C01"])
    _write_scenarios(scenarios, {"scenarios": []})

    result = _run_checker(kb_path, eval_set, scenarios)
    assert result.returncode == 0, (
        f"expected exit 0 — ref points at deprecated tombstone which is valid;\n"
        f"got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_checker_writes_machine_readable_report(tmp_path):
    kb = tmp_path / "kb.json"
    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"
    report = tmp_path / "report.json"

    _write_kb(kb, ["PR-001-C01"])
    _write_eval_set(eval_set, ["PR-001-C01", "PR-999-C99"])
    _write_scenarios(scenarios, {"scenarios": []})

    result = _run_checker(kb, eval_set, scenarios, report=report)
    assert result.returncode == 2
    assert report.exists()
    payload = json.loads(report.read_text())
    assert payload["dangling_count"] == 1
    assert payload["dangling"][0]["concern_id"] == "PR-999-C99"
    assert payload["kb_concern_count"] == 1


def test_checker_handles_empty_external_artifacts(tmp_path):
    kb = tmp_path / "kb.json"
    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"

    _write_kb(kb, ["PR-001-C01"])
    eval_set.write_text("version: 1\ncases: []\n")
    scenarios.write_text(json.dumps({"scenarios": []}))

    result = _run_checker(kb, eval_set, scenarios)
    assert result.returncode == 0


def test_checker_fails_on_missing_kb(tmp_path):
    kb = tmp_path / "nonexistent.json"
    eval_set = tmp_path / "eval.yaml"
    scenarios = tmp_path / "scenarios.json"
    eval_set.write_text("cases: []\n")
    scenarios.write_text("{}")

    result = _run_checker(kb, eval_set, scenarios)
    assert result.returncode == 2
    assert "KB not found" in result.stderr or "not found" in result.stderr.lower()
