"""Fail-closed exit-decision contract across all gates (Phase 2 review finding).

The PASS/FAIL exit code is the harness's entire fail-closed guarantee, yet the
decision `should_fail = bool(failures) or (args.strict and bool(warnings))` is
copy-pasted across all 33 gates with no central enforcement. A single future
edit that drops the `args.strict` clause or inverts the boolean would silently
turn that gate fail-OPEN, and no existing test would catch it. This contract
test locks the invariant: every gate must compute the fail-closed decision and
exit 2 on it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_GATES_DIR = Path(__file__).resolve().parents[1] / "scripts" / "gates"
_GATE_FILES = sorted(
    p for p in _GATES_DIR.glob("*.py")
    if p.name != "__init__.py" and not p.name.startswith("._")  # skip macOS AppleDouble metadata
)

# Allow either `warnings` or `warnings_list` as the warning-bucket variable name.
_SHOULD_FAIL = re.compile(
    r"should_fail\s*=\s*bool\(failures\)\s*or\s*\(args\.strict\s+and\s+bool\(warnings(?:_list)?\)\)"
)
_RETURN_2 = re.compile(r"return\s+2\s+if\s+should_fail")


def test_exactly_33_gates():
    # If a gate is added/removed, revisit the fail-closed contract for it.
    assert len(_GATE_FILES) == 33, [p.name for p in _GATE_FILES]


@pytest.mark.parametrize("gate", _GATE_FILES, ids=lambda p: p.name)
def test_gate_computes_failclosed_decision(gate: Path):
    src = gate.read_text(encoding="utf-8")
    assert _SHOULD_FAIL.search(src), (
        f"{gate.name} is missing the fail-closed decision "
        f"`should_fail = bool(failures) or (args.strict and bool(warnings))` — "
        f"a dropped strict clause or inverted boolean would make this gate fail-OPEN."
    )


@pytest.mark.parametrize("gate", _GATE_FILES, ids=lambda p: p.name)
def test_gate_exits_2_on_should_fail(gate: Path):
    src = gate.read_text(encoding="utf-8")
    assert _RETURN_2.search(src), f"{gate.name} is missing `return 2 if should_fail` (exit-code contract)."
