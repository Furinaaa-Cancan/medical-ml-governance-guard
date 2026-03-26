#!/usr/bin/env python3
"""
Run the full deflation experiment matrix for the MLGG methods paper.

Matrix: 6 datasets × 7 conditions × 10 seeds × 3 model families
Produces:
  - Per-run JSON results in output/<dataset>/<condition>/
  - Aggregated summary CSV: output/deflation_summary.csv
  - Bootstrap 95% CI table: output/deflation_ci_table.json

Usage:
  python3 experiments/paper/run_deflation_experiment.py --output-dir experiments/paper/output
  python3 experiments/paper/run_deflation_experiment.py --datasets heart pima --seeds 42 123
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

# Add scripts/ to path for dataset download
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "examples"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_leaky_pipeline import CONDITIONS, run_pipeline  # noqa: E402

# ---------------------------------------------------------------------------
# Dataset specifications
# ---------------------------------------------------------------------------

DATASETS: Dict[str, Dict[str, Any]] = {
    "heart": {
        "file": "heart_disease.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "UCI Heart Disease",
        "n_expected": 297,
    },
    "breast": {
        "file": "breast_cancer.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "Breast Cancer WDBC",
        "n_expected": 569,
    },
    "ckd": {
        "file": "chronic_kidney_disease.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "Chronic Kidney Disease",
        "n_expected": 400,
    },
    "pima": {
        "file": "pima_diabetes.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "Pima Diabetes",
        "n_expected": 768,
    },
    "framingham": {
        "file": "framingham_heart.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "Framingham Heart Study",
        "n_expected": 4240,
    },
    "diabetes130": {
        "file": "diabetes_130_readmission.csv",
        "target_col": "y",
        "patient_id_col": "patient_id",
        "ignore_cols": ["patient_id", "event_time"],
        "display_name": "Diabetes 130 Hospital",
        "n_expected": 10000,
    },
}

DEFAULT_SEEDS = [42, 123, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_dataset(name: str, data_dir: Path) -> pd.DataFrame:
    """Load a dataset CSV, downloading if needed."""
    spec = DATASETS[name]
    csv_path = data_dir / spec["file"]

    if not csv_path.exists():
        print(f"  Dataset {name} not found at {csv_path}")
        print(f"  Downloading via: python3 examples/download_real_data.py {name} --output {csv_path}")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "examples" / "download_real_data.py"),
             name, "--output", str(csv_path)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to download {name}: {result.stderr}")

    df = pd.read_csv(csv_path)
    print(f"  Loaded {name}: {len(df)} rows, {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

def run_experiment_matrix(
    datasets: List[str],
    seeds: List[int],
    output_dir: Path,
    data_dir: Path,
) -> List[Dict[str, Any]]:
    """Run the full experiment matrix."""
    conditions = sorted(CONDITIONS)
    all_results: List[Dict[str, Any]] = []

    total = len(datasets) * len(conditions) * len(seeds)
    done = 0

    for ds_name in datasets:
        spec = DATASETS[ds_name]
        print(f"\n{'='*60}")
        print(f"Dataset: {spec['display_name']} ({ds_name})")
        print(f"{'='*60}")

        try:
            df = load_dataset(ds_name, data_dir)
        except Exception as e:
            print(f"  SKIP: {e}")
            done += len(conditions) * len(seeds)
            continue

        for cond in conditions:
            for seed in seeds:
                done += 1
                tag = f"[{done}/{total}] {ds_name}/{cond}/seed={seed}"

                # Check if result already exists (resume support)
                result_path = output_dir / ds_name / cond / f"seed_{seed}.json"
                if result_path.exists():
                    try:
                        with result_path.open() as f:
                            cached = json.load(f)
                        if "error" not in cached:
                            all_results.append(cached)
                            print(f"  {tag} — cached")
                            continue
                    except Exception:
                        pass

                print(f"  {tag} — running...", end="", flush=True)
                try:
                    result = run_pipeline(
                        df=df,
                        target_col=spec["target_col"],
                        patient_id_col=spec["patient_id_col"],
                        ignore_cols=spec["ignore_cols"],
                        seed=seed,
                        condition=cond,
                    )
                    result["dataset"] = ds_name
                    result["dataset_display"] = spec["display_name"]
                    result["dataset_n"] = len(df)

                    # Save individual result
                    result_path.parent.mkdir(parents=True, exist_ok=True)
                    with result_path.open("w") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)

                    if "error" in result:
                        print(f" ERROR: {result['error']}")
                    else:
                        auc = result["metrics"]["test"]["auc_roc"]
                        print(f" AUC={auc:.4f} ({result['elapsed_seconds']:.1f}s)")
                    all_results.append(result)

                except Exception as e:
                    print(f" EXCEPTION: {e}")
                    err_result = {
                        "dataset": ds_name, "condition": cond,
                        "seed": seed, "error": str(e),
                    }
                    all_results.append(err_result)

    return all_results


# ---------------------------------------------------------------------------
# Aggregation and bootstrap CI
# ---------------------------------------------------------------------------

def compute_summary(results: List[Dict[str, Any]]) -> pd.DataFrame:
    """Aggregate results into a summary DataFrame."""
    rows = []
    for r in results:
        if "error" in r:
            continue
        test_m = r["metrics"]["test"]
        train_m = r["metrics"]["train"]
        rows.append({
            "dataset": r["dataset"],
            "condition": r["condition"],
            "seed": r["seed"],
            "model": r["selected_model"],
            "test_auc_roc": test_m["auc_roc"],
            "test_auc_pr": test_m["auc_pr"],
            "test_brier": test_m["brier"],
            "train_auc_roc": train_m["auc_roc"],
            "train_test_gap": round(train_m["auc_roc"] - test_m["auc_roc"], 4),
            "threshold": r["threshold"],
            "n_total": r["dataset_n"],
            "L1": r["leakage_flags"]["L1"],
            "L2": r["leakage_flags"]["L2"],
            "L3": r["leakage_flags"]["L3"],
            "L4": r["leakage_flags"]["L4"],
            "L5": r["leakage_flags"]["L5"],
        })
    return pd.DataFrame(rows)


def bootstrap_ci(
    values: np.ndarray,
    n_boot: int = 2000,
    ci: float = 0.95,
    seed: int = 42,
) -> Dict[str, float]:
    """Compute bootstrap confidence interval."""
    rng = np.random.default_rng(seed)
    n = len(values)
    if n == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan")}
    boot_means = np.array([
        np.mean(rng.choice(values, size=n, replace=True))
        for _ in range(n_boot)
    ])
    alpha = (1 - ci) / 2
    return {
        "mean": round(float(np.mean(values)), 4),
        "ci_lower": round(float(np.percentile(boot_means, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(boot_means, (1 - alpha) * 100)), 4),
        "std": round(float(np.std(values)), 4),
        "n": n,
    }


def compute_ci_table(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute bootstrap CI for each dataset × condition combination."""
    table: Dict[str, Any] = {}

    for ds in df["dataset"].unique():
        table[ds] = {}
        ds_df = df[df["dataset"] == ds]

        for cond in sorted(ds_df["condition"].unique()):
            cond_df = ds_df[ds_df["condition"] == cond]
            aucs = cond_df["test_auc_roc"].dropna().values
            table[ds][cond] = bootstrap_ci(aucs)

        # Compute deflation: all_leaky - clean
        leaky_aucs = ds_df[ds_df["condition"] == "all_leaky"]["test_auc_roc"].dropna().values
        clean_aucs = ds_df[ds_df["condition"] == "clean"]["test_auc_roc"].dropna().values

        if len(leaky_aucs) > 0 and len(clean_aucs) > 0:
            deflation = leaky_aucs.mean() - clean_aucs.mean()
            table[ds]["_deflation"] = {
                "leaky_mean": round(float(leaky_aucs.mean()), 4),
                "clean_mean": round(float(clean_aucs.mean()), 4),
                "inflation": round(float(deflation), 4),
                "inflation_pct": round(float(deflation / clean_aucs.mean() * 100), 2)
                if clean_aucs.mean() > 0 else None,
            }

    return table


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the full MLGG deflation experiment."
    )
    parser.add_argument("--output-dir", type=str,
                        default=str(REPO_ROOT / "experiments" / "paper" / "output"),
                        help="Output directory for results.")
    parser.add_argument("--data-dir", type=str,
                        default=str(REPO_ROOT / "examples"),
                        help="Directory containing dataset CSVs.")
    parser.add_argument("--datasets", nargs="+",
                        default=list(DATASETS.keys()),
                        choices=list(DATASETS.keys()),
                        help="Datasets to include.")
    parser.add_argument("--seeds", nargs="+", type=int,
                        default=DEFAULT_SEEDS,
                        help="Random seeds to use.")
    parser.add_argument("--summary-only", action="store_true",
                        help="Only re-aggregate existing results.")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    data_dir = Path(args.data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    if args.summary_only:
        # Re-aggregate from existing JSON files
        all_results = []
        for ds in args.datasets:
            for cond in sorted(CONDITIONS):
                for seed in args.seeds:
                    p = output_dir / ds / cond / f"seed_{seed}.json"
                    if p.exists():
                        with p.open() as f:
                            all_results.append(json.load(f))
        print(f"Loaded {len(all_results)} cached results.")
    else:
        all_results = run_experiment_matrix(
            datasets=args.datasets,
            seeds=args.seeds,
            output_dir=output_dir,
            data_dir=data_dir,
        )

    # Aggregate
    summary_df = compute_summary(all_results)
    if summary_df.empty:
        print("\nNo valid results to aggregate.")
        return 2

    # Save CSV
    csv_path = output_dir / "deflation_summary.csv"
    summary_df.to_csv(csv_path, index=False)
    print(f"\nSummary CSV: {csv_path} ({len(summary_df)} rows)")

    # Bootstrap CI table
    ci_table = compute_ci_table(summary_df)
    ci_path = output_dir / "deflation_ci_table.json"
    with ci_path.open("w") as f:
        json.dump(ci_table, f, indent=2, ensure_ascii=False)
    print(f"CI table: {ci_path}")

    # Print key results
    print(f"\n{'='*70}")
    print("DEFLATION EXPERIMENT RESULTS")
    print(f"{'='*70}")
    print(f"{'Dataset':<25} {'Leaky AUC':>10} {'Clean AUC':>10} {'Inflation':>10} {'%':>6}")
    print("-" * 70)
    for ds in args.datasets:
        if ds in ci_table and "_deflation" in ci_table[ds]:
            d = ci_table[ds]["_deflation"]
            pct = f"{d['inflation_pct']:.1f}%" if d.get("inflation_pct") else "N/A"
            print(f"{ds:<25} {d['leaky_mean']:>10.4f} {d['clean_mean']:>10.4f} {d['inflation']:>+10.4f} {pct:>6}")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} minutes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
