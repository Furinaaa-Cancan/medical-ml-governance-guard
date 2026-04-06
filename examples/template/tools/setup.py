"""
setup.py — Interactive project setup wizard.

Asks simple questions, auto-fills config.py.
Eliminates the intimidation of editing config.py manually.

Usage:
    python3 tools/setup.py
    python3 tools/setup.py --csv path/to/data.csv   # auto-detect columns
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# ── Helpers ────────────────────────────────────────────

def ask(prompt, default=None, choices=None):
    """Ask user a question with optional default and choices."""
    suffix = ""
    if choices:
        suffix = f" [{'/'.join(choices)}]"
    if default is not None:
        suffix += f" (default: {default})"
    suffix += ": "

    while True:
        answer = input(f"  {prompt}{suffix}").strip()
        if not answer and default is not None:
            return default
        if choices and answer not in choices:
            print(f"    Please choose from: {', '.join(choices)}")
            continue
        if answer:
            return answer
        print("    Please enter a value.")


def ask_yn(prompt, default=True):
    """Ask yes/no question."""
    hint = "Y/n" if default else "y/N"
    answer = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def detect_columns(csv_path):
    """Auto-detect likely patient_id, time, and label columns from a CSV."""
    if not HAS_PANDAS:
        return {}

    df = pd.read_csv(csv_path, nrows=100)
    hints = {}

    # Detect patient ID candidates
    id_patterns = ["patient", "subject", "person", "mrn", "encounter"]
    id_suffixes = ["_id", "id_", "_nbr"]
    for col in df.columns:
        col_lower = col.lower()
        if any(p in col_lower for p in id_patterns) or any(col_lower.endswith(s) or col_lower.startswith(s) for s in id_suffixes):
            if df[col].nunique() > len(df) * 0.5:  # high cardinality → likely ID
                hints.setdefault("patient_id_candidates", []).append(col)

    # Detect time candidates
    time_patterns = ["date", "time", "dt", "timestamp", "admit", "discharge"]
    for col in df.columns:
        col_lower = col.lower()
        if any(p in col_lower for p in time_patterns):
            hints.setdefault("time_candidates", []).append(col)

    # Detect label candidates (binary columns)
    for col in df.columns:
        nunique = df[col].nunique()
        if nunique == 2:
            vals = set(df[col].dropna().unique())
            if vals <= {0, 1} or vals <= {"yes", "no"} or vals <= {"Yes", "No"}:
                hints.setdefault("label_candidates", []).append(col)
        col_lower = col.lower()
        if any(k in col_lower for k in ["target", "label", "outcome", "readmi", "death", "mortal"]):
            hints.setdefault("label_candidates", []).append(col)

    # Deduplicate
    for k in hints:
        hints[k] = list(dict.fromkeys(hints[k]))

    return hints


def show_data_preview(csv_path):
    """Show a quick preview of the dataset."""
    if not HAS_PANDAS:
        print("  (pandas not installed — skipping preview)")
        return

    df = pd.read_csv(csv_path, nrows=5)
    print(f"\n  Dataset preview ({csv_path.name}):")
    print(f"  Columns ({len(df.columns)}): {', '.join(df.columns[:15])}", end="")
    if len(df.columns) > 15:
        print(f" ... +{len(df.columns) - 15} more")
    else:
        print()

    # Quick stats — count rows without loading full dataset
    with open(csv_path) as f:
        n_rows = sum(1 for _ in f) - 1  # subtract header
    print(f"  Rows: {n_rows:,}")

    # Sample for missing rate
    sample = pd.read_csv(csv_path, nrows=min(5000, n_rows))
    print(f"  Missing: ~{sample.isnull().mean().mean():.1%} avg (sampled)")
    return sample


# ── Main wizard ────────────────────────────────────────

def run_wizard(csv_path=None):
    print()
    print("=" * 55)
    print("  MLGG Project Setup Wizard")
    print("=" * 55)
    print()

    # Step 1: Data
    print("[1/5] Data")
    print("-" * 40)

    if csv_path and csv_path.exists():
        print(f"  Found: {csv_path}")
    else:
        raw_dir = PROJECT_ROOT / "00_database" / "raw"
        csvs = list(raw_dir.glob("*.csv"))
        if csvs:
            print(f"  Found CSV files in 00_database/raw/:")
            for i, f in enumerate(csvs):
                print(f"    [{i + 1}] {f.name}")
            choice = ask("Which file?", default="1")
            try:
                idx = int(choice) - 1
            except ValueError:
                print(f"  ERROR: Enter a number, not '{choice}'")
                sys.exit(1)
            if not (0 <= idx < len(csvs)):
                print(f"  ERROR: Invalid choice. Pick 1-{len(csvs)}")
                sys.exit(1)
            csv_path = csvs[idx]
        else:
            path_str = ask("Path to your CSV file")
            csv_path = Path(path_str).expanduser().resolve()
            if not csv_path.exists():
                print(f"  ERROR: File not found: {csv_path}")
                sys.exit(1)

            # Copy to raw directory
            if ask_yn(f"Copy to 00_database/raw/?", default=True):
                import shutil
                dest = raw_dir / csv_path.name
                raw_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(csv_path, dest)
                csv_path = dest
                print(f"  Copied to {dest}")

    df = show_data_preview(csv_path) if HAS_PANDAS else None
    hints = detect_columns(csv_path) if csv_path else {}

    # Step 2: Columns
    print()
    print("[2/5] Column Definitions")
    print("-" * 40)

    if hints.get("patient_id_candidates"):
        print(f"  Auto-detected patient ID candidates: {hints['patient_id_candidates']}")
    patient_id = ask("Patient ID column name",
                     default=hints.get("patient_id_candidates", ["patient_id"])[0])

    if hints.get("time_candidates"):
        print(f"  Auto-detected time candidates: {hints['time_candidates']}")
    has_time = ask_yn("Does your data have a time/date column?", default=bool(hints.get("time_candidates")))
    time_col = ""
    if has_time:
        time_col = ask("Time column name",
                       default=hints.get("time_candidates", [""])[0] or "event_time")

    if hints.get("label_candidates"):
        print(f"  Auto-detected label candidates: {hints['label_candidates']}")
    label_col = ask("Binary label column (0/1)",
                    default=hints.get("label_candidates", ["y"])[0])

    # Check if label needs binarization
    needs_binarize = False
    if df is not None and label_col in df.columns:
        unique_vals = df[label_col].dropna().unique()
        if not (set(unique_vals) <= {0, 1, 0.0, 1.0}):
            print(f"  Label values: {sorted(unique_vals)[:10]}")
            needs_binarize = True
            positive_val = ask("Which value means POSITIVE (event occurred)?")

    # Step 3: Clinical context
    print()
    print("[3/5] Clinical Context")
    print("-" * 40)

    outcome_desc = ask("What are you predicting? (e.g., '30-day readmission', 'mortality')")
    prediction_point = ask("When is the prediction made? (e.g., 'at admission', 'at discharge')",
                           default="at admission")

    # Step 4: Exclusions
    print()
    print("[4/5] Cohort Exclusions (MLGG-C01)")
    print("-" * 40)
    print("  Exclude records where the outcome is structurally impossible.")
    print("  Example: deceased patients cannot be readmitted.")

    exclusions = {}
    while ask_yn("Add an exclusion criterion?", default=False):
        col = ask("Column name")
        vals = ask("Values to exclude (comma-separated)")
        exclusions[col] = [v.strip() for v in vals.split(",")]

    # Step 5: Preferences
    print()
    print("[5/5] Preferences")
    print("-" * 40)

    try:
        seed = int(ask("Random seed", default="42"))
    except ValueError:
        print("  ERROR: Random seed must be an integer")
        sys.exit(1)
    split_ratio = ask("Train/Valid/Test ratio", default="60/20/20")
    parts = split_ratio.split("/")
    if len(parts) != 3:
        print("  ERROR: Ratio must be A/B/C format (e.g., 60/20/20)")
        sys.exit(1)
    try:
        ratios = [int(x) / 100 for x in parts]
    except ValueError:
        print("  ERROR: Ratios must be integers (e.g., 60/20/20)")
        sys.exit(1)
    if abs(sum(ratios) - 1.0) > 0.01:
        print(f"  ERROR: Ratios must sum to 100 (got {sum(int(x) for x in parts)})")
        sys.exit(1)

    # ── Generate config ────────────────────────

    print()
    print("=" * 55)
    print("  Generating config.py...")
    print("=" * 55)

    config_lines = [
        '"""',
        f'config.py — {outcome_desc} prediction project',
        '',
        'Auto-generated by MLGG setup wizard.',
        '"""',
        '',
        'from pathlib import Path',
        '',
        '# Paths',
        'PROJECT_ROOT = Path(__file__).resolve().parent',
        'RAW_DATA_DIR = PROJECT_ROOT / "00_database" / "raw"',
        'EXPLORATION_RESULTS = PROJECT_ROOT / "01_exploration" / "results"',
        'SPLIT_RESULTS = PROJECT_ROOT / "02_splitting" / "results"',
        'PREPROCESS_RESULTS = PROJECT_ROOT / "03_preprocessing" / "results"',
        'FEATURE_RESULTS = PROJECT_ROOT / "04_feature_selection" / "results"',
        'MODELING_RESULTS = PROJECT_ROOT / "05_modeling" / "results"',
        'EVALUATION_RESULTS = PROJECT_ROOT / "06_evaluation" / "results"',
        'INTERPRET_RESULTS = PROJECT_ROOT / "07_interpretability" / "results"',
        'FAIRNESS_RESULTS = PROJECT_ROOT / "08_fairness" / "results"',
        'REPORTING_RESULTS = PROJECT_ROOT / "09_reporting" / "results"',
        'OUTPUT_FIGURES = PROJECT_ROOT / "outputs" / "figures"',
        'OUTPUT_TABLES = PROJECT_ROOT / "outputs" / "tables"',
        'OUTPUT_MODELS = PROJECT_ROOT / "outputs" / "models"',
        '',
        f'# Raw data file',
        f'RAW_DATA = RAW_DATA_DIR / "{csv_path.name}"',
        '',
        '# Column definitions',
        f'PATIENT_ID_COL = {json.dumps(patient_id)}',
        f'TIME_COL = {json.dumps(time_col)}' if time_col else 'TIME_COL = ""  # No time column',
        f'LABEL_COL = {json.dumps(label_col)}',
    ]

    if needs_binarize:
        config_lines += [
            f'ORIGINAL_TARGET = "{label_col}"',
            f'POSITIVE_CLASS = "{positive_val}"',
        ]

    config_lines += [
        '',
        f'# Clinical context',
        f'OUTCOME_DESCRIPTION = {json.dumps(outcome_desc, ensure_ascii=False)}',
        f'PREDICTION_POINT = {json.dumps(prediction_point, ensure_ascii=False)}',
        '',
        '# Cohort exclusion (MLGG-C01)',
        f'EXCLUDE_CONDITIONS = {json.dumps(exclusions, ensure_ascii=False)}',
        '',
        '# Feature temporal classification (MLGG-F05)',
        '# TODO: Fill in after Phase 1 data understanding',
        'ADMISSION_FEATURES = []  # Features available at prediction time',
        'DISCHARGE_FEATURES = []  # All features including post-prediction',
        '',
        '# ── Preprocessing (Phase 3) ──',
        '',
        '# Column type detection (MLGG-P05)',
        'MAX_ONEHOT_CARDINALITY = 15',
        '',
        '# Missingness tier thresholds (MLGG-P06, Madley-Dowd 2019)',
        'MISSING_TIER1_UPPER = 0.05   # <5% → simple impute',
        'MISSING_TIER2_UPPER = 0.40   # 5-40% → impute + indicator',
        'MISSING_TIER3_UPPER = 0.80   # 40-80% → impute + indicator + sensitivity',
        '                              # >80% → drop value, keep indicator only',
        '',
        '# Manual overrides (take priority over auto-detection)',
        'COLS_DROP_VALUE_KEEP_INDICATOR = []  # Force Tier 4',
        'COLS_IMPUTE_WITH_INDICATOR = []      # Force Tier 2/3',
        'COLS_SIMPLE_IMPUTE = []              # Force Tier 1',
        '',
        '# Verified ordinal columns: {"col": ["low", "mid", "high"]}',
        'ORDINAL_COLUMNS = {}',
        '',
        '# ── Feature Selection (Phase 4) ──',
        '',
        'NZV_THRESHOLD = 0.99              # Near-zero variance cutoff',
        '',
        '# Stability Selection (Meinshausen & Buhlmann 2010)',
        'STABILITY_N_SUBSAMPLES = 100',
        'STABILITY_SUBSAMPLE_RATIO = 0.50',
        'STABILITY_THRESHOLD = 0.60',
        'STABILITY_L1_RATIOS = (0.1, 0.3, 0.5, 0.7, 1.0)  # Elastic Net alpha',
        'STABILITY_CS = (0.001, 0.01, 0.1, 1.0, 10.0)      # Regularization C',
        'STABILITY_CV_FOLDS = 5',
        'STABILITY_MAX_ITER = 3000',
        '',
        '# Ridge baseline (Harrell 2015)',
        'RIDGE_CV_CS = (0.001, 0.01, 0.1, 1.0, 10.0, 100.0)',
        'RIDGE_FALLBACK_THRESHOLD = 0.005  # PR-AUC drop → fallback to full model',
        '',
        '# Group LASSO (auto-detected from Phase 3, or override here)',
        'FEATURE_GROUPS = {}',
        '',
        '# Forbidden features (MLGG-F01/F02)',
        'FORBIDDEN_FEATURES = []',
        '',
        '# Legacy alias',
        'NEAR_ZERO_VARIANCE_COLS = []',
        '',
        '# ── Reproducibility ──',
        f'RANDOM_STATE = {seed}',
        f'SEED_LIST = [{seed}, {seed + 81}, {seed + 414}, {seed + 747}, {seed + 982}]',
        '',
        '# Split ratios',
        f'TRAIN_RATIO = {ratios[0]}',
        f'VALID_RATIO = {ratios[1]}',
        f'TEST_RATIO = {ratios[2]}',
        '',
        '# Evaluation',
        'N_BOOTSTRAP = 1000',
        'CI_LEVEL = 0.95',
        'CALIBRATION_ECE_THRESHOLD = 0.1',
    ]

    config_path = PROJECT_ROOT / "config.py"
    config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    print(f"  Wrote {config_path}")

    # Summary
    print()
    print("=" * 55)
    print("  Setup complete!")
    print("=" * 55)
    print()
    print(f"  Dataset:    {csv_path.name}")
    print(f"  Outcome:    {outcome_desc}")
    print(f"  Patient ID: {patient_id}")
    print(f"  Label:      {label_col}")
    if time_col:
        print(f"  Time:       {time_col}")
    if exclusions:
        print(f"  Exclusions: {len(exclusions)} rules")
    print()
    print("  Next steps:")
    print("  1. Open Claude Code in this directory")
    print("  2. Type /mlgg to start guided analysis")
    print("  3. Or run: python3 tools/check.py")
    print()


def main():
    parser = argparse.ArgumentParser(description="MLGG project setup wizard")
    parser.add_argument("--csv", type=Path, help="Path to your CSV data file")
    args = parser.parse_args()
    run_wizard(csv_path=args.csv)


if __name__ == "__main__":
    main()
