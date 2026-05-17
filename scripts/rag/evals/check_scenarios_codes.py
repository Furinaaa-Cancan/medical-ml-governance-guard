#!/usr/bin/env python3
"""CI gate: every ``failure_code`` declared in
``references/retrieval_eval/scenarios.json`` MUST be a real code emitted
somewhere in ``scripts/gates/*.py`` OR captured by the W7 harvest
(``references/retrieval_eval/real_gate_codes_harvest.json``).

Closes the W17-C4 / W9-C1 ghost-finding loop: future drift between
hand-written scenarios and gate source MUST fail closed.

Exit codes:
    0 — full compliance
    2 — at least one phantom code; report prints per-scenario breakdown
    1 — input error (missing file, invalid JSON)

free_text_probe scenarios (no gate_name, empty failure_codes) are
ignored. Same for any scenario explicitly tagged
``"failure_codes_check": "skip"``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Reuse the AST collector + harvest loader from the regen script so the
# two stay byte-for-byte aligned on what a "real" code is.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from regen_scenarios import (  # noqa: E402
    GATES_DIR,
    HARVEST_PATH,
    SCENARIOS_PATH,
    collect_codes_per_gate,
    load_harvest_codes,
    valid_codes_for_gate,
)


def find_violations(
    scenarios_doc: dict,
    source_codes: Dict[str, Set[str]],
    harvest_codes: Dict[str, Dict[str, int]],
) -> List[Tuple[str, str, List[str]]]:
    """Return ``[(scenario_id, gate_name, [phantom_codes...]), ...]``.

    Only scenarios with at least one phantom code are returned.
    """
    violations: List[Tuple[str, str, List[str]]] = []
    for sc in scenarios_doc.get("scenarios", []):
        if sc.get("failure_codes_check") == "skip":
            continue
        gate = sc.get("gate_name")
        codes = sc.get("failure_codes", [])
        if not gate or gate == "free_text_probe":
            continue
        if not codes:
            continue
        valid = valid_codes_for_gate(gate, source_codes, harvest_codes)
        phantoms = [c for c in codes if c not in valid]
        if phantoms:
            violations.append(
                (sc.get("scenario_id", "<unknown>"), gate, phantoms)
            )
    return violations


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gates-dir", default=str(GATES_DIR))
    parser.add_argument("--harvest", default=str(HARVEST_PATH))
    parser.add_argument("--scenarios", default=str(SCENARIOS_PATH))
    args = parser.parse_args(argv)

    scenarios_path = Path(args.scenarios)
    if not scenarios_path.exists():
        print(f"error: scenarios file not found: {scenarios_path}", file=sys.stderr)
        return 1
    try:
        scenarios_doc = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid scenarios JSON: {exc}", file=sys.stderr)
        return 1

    source_codes = collect_codes_per_gate(Path(args.gates_dir))
    harvest_codes = load_harvest_codes(Path(args.harvest))

    violations = find_violations(scenarios_doc, source_codes, harvest_codes)

    n_scenarios = len(scenarios_doc.get("scenarios", []))
    if not violations:
        print(
            f"OK: all failure_codes across {n_scenarios} scenarios are valid "
            f"(source ∪ harvest)."
        )
        return 0

    print(
        f"FAIL: {len(violations)} scenario(s) declare phantom failure_codes "
        f"not found in gate source or W7 harvest.",
        file=sys.stderr,
    )
    for sid, gate, phantoms in violations:
        print(f"  - {sid} (gate={gate}):", file=sys.stderr)
        for code in phantoms:
            print(f"      phantom code: {code!r}", file=sys.stderr)
    print(
        "\nFix: run `python scripts/rag/evals/regen_scenarios.py` and "
        "review /tmp/W20_C1_scenarios_v2_diff.md before updating "
        "references/retrieval_eval/scenarios.json.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
