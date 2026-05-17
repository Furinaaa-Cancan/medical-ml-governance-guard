"""Tests for scripts/rag/evals/check_scenarios_codes.py — the CI gate
that prevents future drift between scenarios.json's declared
``failure_codes`` and the real codes emitted by gates.

Exit-code contract:
    0 — full compliance
    1 — input error
    2 — phantom code detected
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

_EVALS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "rag" / "evals"
if str(_EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(_EVALS_DIR))

from check_scenarios_codes import find_violations, main


def _write_fake_gate(dirpath: Path, name: str, codes: list[str]) -> None:
    """Drop a synthetic gate module whose AST declares ``codes`` via
    ``register_remediations``."""
    body = "from _gate_framework import register_remediations\n"
    body += "register_remediations({\n"
    for c in codes:
        body += f'    "{c}": "hint",\n'
    body += "})\n"
    (dirpath / f"{name}.py").write_text(body, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# find_violations unit
# ──────────────────────────────────────────────────────────────────────


def test_find_violations_clean_scenarios() -> None:
    """Every code valid → no violations."""
    source_codes = {"my_gate": {"a", "b"}}
    doc = {
        "scenarios": [
            {
                "scenario_id": "s1",
                "gate_name": "my_gate",
                "failure_codes": ["a", "b"],
            }
        ]
    }
    assert find_violations(doc, source_codes, {}) == []


def test_find_violations_flags_phantom() -> None:
    source_codes = {"my_gate": {"a"}}
    doc = {
        "scenarios": [
            {
                "scenario_id": "s_phantom",
                "gate_name": "my_gate",
                "failure_codes": ["a", "ghost"],
            }
        ]
    }
    violations = find_violations(doc, source_codes, {})
    assert len(violations) == 1
    sid, gate, phantoms = violations[0]
    assert sid == "s_phantom" and gate == "my_gate"
    assert phantoms == ["ghost"]


def test_find_violations_harvest_acts_as_fallback() -> None:
    """A code missing from source but present in harvest is accepted."""
    source_codes = {"my_gate": set()}
    harvest_codes = {"my_gate": {"harvest_only": 5}}
    doc = {
        "scenarios": [
            {
                "scenario_id": "s",
                "gate_name": "my_gate",
                "failure_codes": ["harvest_only"],
            }
        ]
    }
    assert find_violations(doc, source_codes, harvest_codes) == []


def test_find_violations_ignores_free_text_probes() -> None:
    doc = {
        "scenarios": [
            {
                "scenario_id": "probe",
                "gate_name": "free_text_probe",
                "failure_codes": [],
            }
        ]
    }
    assert find_violations(doc, {}, {}) == []


def test_find_violations_respects_explicit_skip() -> None:
    """An explicit ``failure_codes_check: skip`` opts out (for staged
    rollout scenarios)."""
    doc = {
        "scenarios": [
            {
                "scenario_id": "s",
                "gate_name": "my_gate",
                "failure_codes": ["phantom"],
                "failure_codes_check": "skip",
            }
        ]
    }
    assert find_violations(doc, {"my_gate": set()}, {}) == []


# ──────────────────────────────────────────────────────────────────────
# main() exit-code contract
# ──────────────────────────────────────────────────────────────────────


def _build_env(
    tmp_path: Path,
    gate_codes: dict[str, list[str]],
    harvest: dict,
    scenarios: list[dict],
) -> tuple[Path, Path, Path]:
    """Materialize a tmp gates_dir + harvest + scenarios file."""
    gates_dir = tmp_path / "gates"
    gates_dir.mkdir()
    for gate, codes in gate_codes.items():
        _write_fake_gate(gates_dir, gate, codes)

    harvest_path = tmp_path / "harvest.json"
    harvest_path.write_text(json.dumps(harvest), encoding="utf-8")

    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text(
        json.dumps({"scenarios": scenarios}), encoding="utf-8"
    )
    return gates_dir, harvest_path, scenarios_path


def test_main_exits_zero_on_clean(tmp_path: Path, capsys) -> None:
    gates_dir, harvest_path, scenarios_path = _build_env(
        tmp_path,
        gate_codes={"my_gate": ["a", "b"]},
        harvest={},
        scenarios=[
            {
                "scenario_id": "ok",
                "gate_name": "my_gate",
                "failure_codes": ["a"],
            }
        ],
    )
    rc = main(
        [
            "--gates-dir",
            str(gates_dir),
            "--harvest",
            str(harvest_path),
            "--scenarios",
            str(scenarios_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_main_exits_two_on_synthetic_phantom(tmp_path: Path, capsys) -> None:
    """Critical contract: synthetic phantom code → exit 2 with
    per-scenario breakdown on stderr."""
    gates_dir, harvest_path, scenarios_path = _build_env(
        tmp_path,
        gate_codes={"my_gate": ["a"]},
        harvest={},
        scenarios=[
            {
                "scenario_id": "phantom_scenario",
                "gate_name": "my_gate",
                "failure_codes": ["a", "i_do_not_exist"],
            }
        ],
    )
    rc = main(
        [
            "--gates-dir",
            str(gates_dir),
            "--harvest",
            str(harvest_path),
            "--scenarios",
            str(scenarios_path),
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "phantom_scenario" in captured.err
    assert "i_do_not_exist" in captured.err


def test_main_exits_one_on_missing_scenarios(tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "--gates-dir",
            str(tmp_path),
            "--harvest",
            str(tmp_path / "nope.json"),
            "--scenarios",
            str(tmp_path / "missing.json"),
        ]
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_main_exits_one_on_invalid_json(tmp_path: Path, capsys) -> None:
    scenarios_path = tmp_path / "bad.json"
    scenarios_path.write_text("{not: valid json", encoding="utf-8")
    rc = main(
        [
            "--gates-dir",
            str(tmp_path),
            "--harvest",
            str(tmp_path / "nope.json"),
            "--scenarios",
            str(scenarios_path),
        ]
    )
    assert rc == 1
    assert "invalid scenarios JSON" in capsys.readouterr().err
