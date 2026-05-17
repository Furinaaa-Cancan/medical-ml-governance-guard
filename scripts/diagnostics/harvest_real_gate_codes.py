"""W8-W7: harvest real failure_codes from past gate runs in experiments/.

Builds a per-gate frequency table of real-world emitted codes. Used to
validate that eval scenarios.json failure_codes reflect production
gate output (W7-P7 finding).

Two shapes are supported because the corpus mixes:
  * envelope reports with ``failures: [{code: ...}, ...]`` plus ``gate_name``
  * onboarding-style summaries with ``failure_codes: [str, ...]`` nested
    under per-gate keys.

Both shapes contribute to the same per-gate Counter.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def harvest(experiments_dir: Path) -> dict[str, dict[str, int]]:
    """Walk every JSON file under ``experiments_dir`` and aggregate codes."""
    gate_to_codes: dict[str, Counter[str]] = defaultdict(Counter)
    for report in experiments_dir.rglob("*.json"):
        try:
            data = json.loads(report.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        _walk(data, gate_to_codes)
    return {g: dict(c.most_common()) for g, c in gate_to_codes.items()}


def _walk(
    obj: Any,
    accumulator: dict[str, Counter[str]],
    current_gate: str | None = None,
) -> None:
    """Recursively collect (gate, code) pairs from arbitrary JSON."""
    if isinstance(obj, dict):
        gate = obj.get("gate_name") or obj.get("gate") or current_gate

        # Shape 1: ``failures: [{code: "...", ...}, ...]``
        failures = obj.get("failures")
        if gate and isinstance(failures, list):
            for failure in failures:
                if isinstance(failure, dict):
                    code = failure.get("code")
                    if isinstance(code, str):
                        accumulator[gate][code] += 1
                elif isinstance(failure, str):
                    accumulator[gate][failure] += 1

        # Shape 2: ``failure_codes: ["...", ...]``
        codes = obj.get("failure_codes")
        if gate and isinstance(codes, list):
            for code in codes:
                if isinstance(code, str):
                    accumulator[gate][code] += 1

        for value in obj.values():
            _walk(value, accumulator, gate)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, accumulator, current_gate)


def main() -> None:
    # argparse first so --help exits cleanly (satisfies
    # tests/test_stress_gate_cli.py::TestAllScriptsHelp contract).
    argparse.ArgumentParser(
        prog="harvest_real_gate_codes.py",
        description=__doc__.split("\n\n")[0] if __doc__ else None,
    ).parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = harvest(repo / "experiments")
    out_path = repo / "references" / "retrieval_eval" / "real_gate_codes_harvest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"harvested codes for {len(out)} gates -> {out_path}")
    for gate, codes in sorted(
        out.items(), key=lambda kv: -sum(kv[1].values())
    )[:5]:
        total = sum(codes.values())
        top = list(codes.keys())[:3]
        print(f"  {gate}: {len(codes)} unique codes ({total} emissions), top: {top}")


if __name__ == "__main__":
    main()
