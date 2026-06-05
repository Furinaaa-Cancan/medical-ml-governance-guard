"""Run-binding consistency for publication_gate (asymmetric two-tier, P0.1a).

Aggregated evidence must describe a single run. If component reports carry
differing ``run_id`` values, the set is mixed (stale/substituted reports) and
the gate fails closed. The check is additive and a no-op until gates emit
``run_id`` (absent on all reports → pass), so it never regresses today's runs.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from test_publication_gate import (  # noqa: E402
    _build_cmd,
    _make_all_artifacts,
)


def _run(tmp_path, paths):
    cmd = _build_cmd(tmp_path, paths)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def _stamp(path: Path, run_id: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["run_id"] = run_id
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_absent_run_id_is_noop(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)  # none carry run_id
    result, report = _run(tmp_path, paths)

    assert result.returncode == 0
    rb = report["summary"]["run_binding"]
    assert rb["consistent"] is True
    assert rb["distinct_run_ids"] == []
    assert rb["reports_with_run_id"] == 0


def test_single_run_id_passes(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    for p in paths.values():
        _stamp(p, "RUN-2026-0001")
    result, report = _run(tmp_path, paths)

    assert result.returncode == 0
    rb = report["summary"]["run_binding"]
    assert rb["consistent"] is True
    assert rb["distinct_run_ids"] == ["RUN-2026-0001"]


def test_mixed_run_ids_fail_closed(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    for p in paths.values():
        _stamp(p, "RUN-2026-0001")
    _stamp(paths["leakage_report"], "RUN-2026-9999")  # substituted/stale report
    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "mixed_run_evidence" in codes
    assert report["summary"]["run_binding"]["consistent"] is False


def test_mixed_run_ids_fail_even_with_some_absent(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    # only two reports carry run_id, and they disagree; the rest are absent
    _stamp(paths["leakage_report"], "RUN-A")
    _stamp(paths["split_protocol_report"], "RUN-B")
    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "mixed_run_evidence" in codes
