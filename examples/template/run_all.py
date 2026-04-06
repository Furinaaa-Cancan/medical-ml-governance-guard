"""
run_all.py — Execute all 9 phases sequentially.

Usage:
    python3 run_all.py              # Run all phases
    python3 run_all.py --from 3     # Start from Phase 3
    python3 run_all.py --only 6     # Run only Phase 6
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

PHASES = [
    (1, "01_exploration/scripts/explore.py", "Data Understanding"),
    (2, "02_splitting/scripts/split.py", "Data Splitting"),
    (3, "03_preprocessing/scripts/preprocess.py", "Preprocessing"),
    (4, "04_feature_selection/scripts/select_features.py", "Feature Selection"),
    (5, "05_modeling/scripts/train_models.py", "Model Training"),
    (6, "06_evaluation/scripts/evaluate.py", "Evaluation"),
    (7, "07_interpretability/scripts/interpret.py", "Interpretability"),
    (8, "08_fairness/scripts/fairness.py", "Fairness"),
    (9, "09_reporting/scripts/report.py", "Reporting"),
]


def run_phase(num, script, description):
    """Run a single phase script."""
    script_path = PROJECT_ROOT / script
    if not script_path.exists():
        print(f"  SKIP: {script} not found")
        return False

    print(f"\n{'=' * 60}")
    print(f"Phase {num}: {description}")
    print(f"{'=' * 60}")

    start = time.time()
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(PROJECT_ROOT),
        timeout=1800,  # 30 min per phase
    )
    elapsed = time.time() - start

    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"\n[{status}] Phase {num} ({elapsed:.1f}s)")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", type=int, default=1, dest="from_phase",
                        help="Start from this phase number")
    parser.add_argument("--only", type=int, default=None,
                        help="Run only this phase")
    args = parser.parse_args()

    total_start = time.time()
    results = []

    for num, script, desc in PHASES:
        if args.only and num != args.only:
            continue
        if num < args.from_phase:
            continue

        ok = run_phase(num, script, desc)
        results.append((num, desc, ok))

        if not ok:
            print(f"\nStopped at Phase {num} due to failure.")
            break

    # Summary
    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}")
    for num, desc, ok in results:
        print(f"  Phase {num} ({desc}): {'PASS' if ok else 'FAIL'}")
    print(f"\nTotal time: {time.time() - total_start:.1f}s")


if __name__ == "__main__":
    main()
