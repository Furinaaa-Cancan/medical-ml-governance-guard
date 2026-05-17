"""W9-C1: validate eval scenarios cover real production gate codes (W7b).

Three signals:
  (a) eval_only: codes in scenarios.json never emitted by real gates
  (b) production_only: codes emitted in production never tested
  (c) overlap: codes in both (good)

(a) = unreachable test cases (probably wrong codes in scenarios.json)
(b) = test coverage gap (production behavior unguarded)
"""
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARVEST = REPO / "references/retrieval_eval/real_gate_codes_harvest.json"
SCENARIOS = REPO / "references/retrieval_eval/scenarios.json"


def load() -> tuple[dict, dict]:
    harvest = json.loads(HARVEST.read_text())
    scenarios = json.loads(SCENARIOS.read_text())
    return harvest, scenarios


def main():
    harvest, scenarios_data = load()
    # Build per-gate set of codes in scenarios
    eval_codes = defaultdict(set)
    for s in scenarios_data.get("scenarios", []):
        gate = s.get("gate_name") or s.get("mlgg_gate_hint")
        codes = s.get("failure_codes") or s.get("failure_codes_hint") or []
        if gate:
            eval_codes[gate].update(codes)

    # Compare with harvest
    eval_only = defaultdict(set)
    prod_only = defaultdict(set)
    overlap = defaultdict(set)
    all_gates = set(harvest.keys()) | set(eval_codes.keys())
    for gate in all_gates:
        h = set(harvest.get(gate, {}).keys())
        e = eval_codes.get(gate, set())
        eval_only[gate] = e - h
        prod_only[gate] = h - e
        overlap[gate] = h & e

    # Print summary + write JSON
    print("## Cross-validation summary")
    print(f"gates with overlap: {sum(1 for g in all_gates if overlap[g])}")
    print(f"gates with eval_only codes: {sum(1 for g in all_gates if eval_only[g])}")
    print(f"gates with prod_only codes: {sum(1 for g in all_gates if prod_only[g])}")

    print("\n## Top 5 by production_only (test coverage gaps):")
    for gate in sorted(all_gates, key=lambda g: -len(prod_only[g]))[:5]:
        if prod_only[gate]:
            print(f"  {gate}: {len(prod_only[gate])} untested codes: {list(prod_only[gate])[:5]}")

    print("\n## Top 5 by eval_only (unreachable scenarios):")
    for gate in sorted(all_gates, key=lambda g: -len(eval_only[g]))[:5]:
        if eval_only[gate]:
            print(f"  {gate}: {len(eval_only[gate])} unreachable codes: {list(eval_only[gate])[:5]}")

    # Write JSON sidecar
    out = {
        "eval_only": {k: sorted(v) for k, v in eval_only.items() if v},
        "production_only": {k: sorted(v) for k, v in prod_only.items() if v},
        "overlap": {k: sorted(v) for k, v in overlap.items() if v},
    }
    out_path = Path("/tmp/W9C1_gate_code_alignment.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nfull diff -> {out_path}")


if __name__ == "__main__":
    import argparse
    argparse.ArgumentParser(prog="validate_gate_code_alignment.py", description=__doc__.split("\n\n")[0]).parse_args()
    main()
