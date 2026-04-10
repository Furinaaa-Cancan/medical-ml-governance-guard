#!/usr/bin/env python3
"""
Experiment 2: Red Team Validation — evaluate MLGG lint detection rates.

Runs MLGG lint (25 rules) on 40 synthetic adversarial scenarios across 4
difficulty levels and reports detection rates by difficulty and rule.

Each test file contains documented BUGs (ground-truth defects).
A scenario counts as "detected" if lint flags at least one finding with
severity ≥ warning on the file.  A "leakage detected" flag is set when
the finding matches a known leakage rule (R001-R007, R017, R020, R023-R024).

Usage:
    python3 experiments/paper/run_redteam_evaluation.py \
        --redteam-dir experiments/paper/redteam \
        --output experiments/paper/output/redteam_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LINT_MODULE_DIR = REPO_ROOT / "plugin"
PYTHON = sys.executable

LEAKAGE_RULES = {
    "R001", "R002", "R003", "R005", "R006", "R007",
    "R011", "R017", "R020", "R023", "R024", "R026", "R027",
}

DIFFICULTY_LABELS = {
    "r1": "Easy",
    "r2": "Medium",
    "r3": "Hard",
    "r4": "Extreme",
}


def run_lint(filepath: Path) -> List[Dict[str, Any]]:
    """Run MLGG lint on a single file."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(LINT_MODULE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            [PYTHON, "-m", "mlgg_lint", "check", str(filepath), "--format", "json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT), env=env,
        )
        if result.stdout.strip():
            raw = result.stdout.strip()
            depth = 0
            end = 0
            for i, ch in enumerate(raw):
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > 0:
                findings = json.loads(raw[:end])
                if isinstance(findings, list):
                    return findings
    except Exception:
        pass
    return []


def evaluate_redteam(redteam_dir: Path) -> Dict[str, Any]:
    """Run lint on all red team files and compute detection rates."""
    results_by_difficulty: Dict[str, List[Dict[str, Any]]] = {}

    for difficulty in ("r1", "r2", "r3", "r4"):
        d = redteam_dir / difficulty
        if not d.exists():
            continue

        scenario_results = []
        for py_file in sorted(d.glob("*.py")):
            findings = run_lint(py_file)

            # Classify findings
            warnings_or_above = [
                f for f in findings
                if f.get("severity") in ("error", "warning")
            ]
            leakage_findings = [
                f for f in findings
                if f.get("rule_id") in LEAKAGE_RULES
            ]
            rules_triggered = sorted({f.get("rule_id", "") for f in findings})

            detected = len(warnings_or_above) > 0
            leakage_detected = len(leakage_findings) > 0

            scenario_results.append({
                "file": py_file.name,
                "total_findings": len(findings),
                "warnings_or_above": len(warnings_or_above),
                "leakage_findings": len(leakage_findings),
                "detected": detected,
                "leakage_detected": leakage_detected,
                "rules_triggered": rules_triggered,
            })

        results_by_difficulty[difficulty] = scenario_results

    # Compute summary statistics
    summary = {}
    total_detected = 0
    total_scenarios = 0
    total_leakage_detected = 0

    for difficulty, scenarios in results_by_difficulty.items():
        n = len(scenarios)
        n_detected = sum(1 for s in scenarios if s["detected"])
        n_leakage = sum(1 for s in scenarios if s["leakage_detected"])
        total_detected += n_detected
        total_leakage_detected += n_leakage
        total_scenarios += n

        summary[difficulty] = {
            "label": DIFFICULTY_LABELS.get(difficulty, difficulty),
            "n_scenarios": n,
            "n_detected": n_detected,
            "detection_rate": round(n_detected / n * 100, 1) if n else 0,
            "n_leakage_detected": n_leakage,
            "leakage_rate": round(n_leakage / n * 100, 1) if n else 0,
        }

    # Rule frequency across all scenarios
    rule_freq: Dict[str, int] = {}
    for scenarios in results_by_difficulty.values():
        for s in scenarios:
            for r in s["rules_triggered"]:
                rule_freq[r] = rule_freq.get(r, 0) + 1

    return {
        "experiment": "exp2_redteam_validation",
        "total_scenarios": total_scenarios,
        "total_detected": total_detected,
        "overall_detection_rate": round(total_detected / total_scenarios * 100, 1) if total_scenarios else 0,
        "total_leakage_detected": total_leakage_detected,
        "overall_leakage_rate": round(total_leakage_detected / total_scenarios * 100, 1) if total_scenarios else 0,
        "summary_by_difficulty": summary,
        "rule_frequency": dict(sorted(rule_freq.items(), key=lambda x: -x[1])),
        "detailed_results": results_by_difficulty,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run red team evaluation for MLGG lint.")
    parser.add_argument("--redteam-dir", type=str, default="experiments/paper/redteam")
    parser.add_argument("--output", type=str, default="experiments/paper/output/redteam_results.json")
    args = parser.parse_args()

    redteam_dir = Path(args.redteam_dir)
    if not redteam_dir.exists():
        print(f"Error: {redteam_dir} does not exist", file=sys.stderr)
        return 1

    print("Running MLGG lint on 40 red team scenarios...\n")
    results = evaluate_redteam(redteam_dir)

    # Print summary table
    print(f"{'Difficulty':<12} {'Scenarios':>10} {'Detected':>10} {'Rate':>8} {'Leakage':>10} {'Leak Rate':>10}")
    print("-" * 62)
    for diff in ("r1", "r2", "r3", "r4"):
        s = results["summary_by_difficulty"].get(diff, {})
        print(f"{s.get('label',''):<12} {s.get('n_scenarios',0):>10} {s.get('n_detected',0):>10} "
              f"{s.get('detection_rate',0):>7.1f}% {s.get('n_leakage_detected',0):>10} "
              f"{s.get('leakage_rate',0):>9.1f}%")
    print("-" * 62)
    print(f"{'TOTAL':<12} {results['total_scenarios']:>10} {results['total_detected']:>10} "
          f"{results['overall_detection_rate']:>7.1f}% {results['total_leakage_detected']:>10} "
          f"{results['overall_leakage_rate']:>9.1f}%")

    print(f"\nRule frequency:")
    for rule, count in results["rule_frequency"].items():
        print(f"  {rule}: {count} scenarios")

    # Undetected scenarios
    print(f"\nUndetected scenarios:")
    for diff, scenarios in results["detailed_results"].items():
        for s in scenarios:
            if not s["detected"]:
                print(f"  [{diff}] {s['file']}")

    # Save results
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
