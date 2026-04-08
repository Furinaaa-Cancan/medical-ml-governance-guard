#!/usr/bin/env python3
"""
run_all.py — MLGG 9-Phase 一键运行脚本

Usage:
    python3 run_all.py                  # 运行全流程
    python3 run_all.py --download-only  # 仅下载数据
    python3 run_all.py --from 4         # 从 Phase 4 开始
"""

import os
import sys
import time
import subprocess
import argparse
import json
import urllib.request
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def download_data():
    """下载 UCI Diabetes 130-US Hospitals 数据集。"""
    raw_dir = os.path.join(PROJECT_ROOT, "00_database", "raw")
    csv_path = os.path.join(raw_dir, "diabetic_data.csv")

    if os.path.exists(csv_path):
        print(f"  Data already exists: {csv_path}")
        return

    os.makedirs(raw_dir, exist_ok=True)
    url = "https://archive.ics.uci.edu/ml/machine-learning-databases/00296/dataset_diabetes.zip"
    zip_path = os.path.join(raw_dir, "dataset_diabetes.zip")

    print(f"  Downloading from UCI...")
    urllib.request.urlretrieve(url, zip_path)
    print(f"  Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(raw_dir)

    # Move from subdirectory
    extracted = os.path.join(raw_dir, "dataset_diabetes", "diabetic_data.csv")
    if os.path.exists(extracted):
        os.rename(extracted, csv_path)

    # Cleanup
    sub = os.path.join(raw_dir, "dataset_diabetes")
    if os.path.isdir(sub):
        import shutil
        shutil.rmtree(sub)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print(f"  Done: {csv_path}")

    # Data integrity hash for reproducibility
    import hashlib
    sha = hashlib.sha256(open(csv_path, "rb").read()).hexdigest()
    manifest = {"file": "diabetic_data.csv", "sha256": sha, "source": url}
    manifest_path = os.path.join(raw_dir, "DATA_MANIFEST.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  SHA-256: {sha[:16]}... (saved to DATA_MANIFEST.json)")


PHASES = [
    (1, "01_exploration/scripts/explore.py", "Data Understanding"),
    (2, "02_splitting/scripts/split.py", "Data Splitting"),
    (3, "03_preprocessing/scripts/preprocess.py", "Preprocessing"),
    (4, "04_feature_selection/scripts/select_features.py", "Feature Selection"),
    (5, "05_modeling/scripts/train_models.py", "Model Training"),
    (5.5, "05_modeling/scripts/train_admission_model.py", "Admission vs Discharge Comparison"),
    (6, "06_evaluation/scripts/evaluate.py", "Evaluation"),
    (6.5, "06_evaluation/scripts/calibrate.py", "Calibration"),
    (7, "07_interpretability/scripts/interpret.py", "Interpretability"),
    (8, "08_fairness/scripts/fairness.py", "Fairness"),
    (9, "09_reporting/scripts/report.py", "Reporting"),
]


def run_phase(phase_num, script, description):
    """运行单个 Phase 脚本。"""
    full_path = os.path.join(PROJECT_ROOT, script)
    if not os.path.exists(full_path):
        print(f"  SKIP: {script} not found")
        return False

    print(f"\n{'='*60}")
    print(f"Phase {phase_num}: {description}")
    print(f"{'='*60}")

    start = time.time()
    result = subprocess.run(
        [sys.executable, full_path],
        cwd=PROJECT_ROOT,
        timeout=1800,  # 30 min max per phase
    )
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  Phase {phase_num} completed in {elapsed:.0f}s")
        return True
    else:
        print(f"\n  Phase {phase_num} FAILED (exit {result.returncode}) after {elapsed:.0f}s")
        return False


def main():
    parser = argparse.ArgumentParser(description="MLGG 9-Phase runner")
    parser.add_argument("--download-only", action="store_true",
                        help="Only download data, don't run phases")
    parser.add_argument("--from", type=int, default=1, dest="start_phase",
                        help="Start from this phase number (default: 1)")
    args = parser.parse_args()

    print("MLGG 9-Phase Pipeline Runner")
    print("="*60)

    # Download data
    print("\nStep 0: Data download")
    download_data()

    if args.download_only:
        return

    # Run phases
    total_start = time.time()
    results = []

    for phase_num, script, description in PHASES:
        if int(phase_num) < args.start_phase:
            continue
        ok = run_phase(phase_num, script, description)
        results.append((phase_num, description, ok))
        if not ok:
            print(f"\nStopping at Phase {phase_num} due to failure.")
            break

    # Summary
    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"SUMMARY ({total_elapsed:.0f}s total)")
    print(f"{'='*60}")
    for phase_num, description, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  Phase {phase_num:4}: {description:25s} [{status}]")


if __name__ == "__main__":
    main()
