#!/usr/bin/env python3
"""
Download CDC public health survey datasets (BRFSS, NHIS) for MLGG pipeline.

All data is publicly available from CDC without registration.

Usage:
  python3 examples/download_cdc_data.py brfss --output examples/brfss2022_diabetes.csv
  python3 examples/download_cdc_data.py nhis --output examples/nhis2022_diabetes.csv
  python3 examples/download_cdc_data.py all
"""
from __future__ import annotations

import argparse
import io
import sys
import tempfile
import zipfile
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BRFSS_URL = "https://www.cdc.gov/brfss/annual_data/2022/files/LLCP2022XPT.zip"
NHIS_URL = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Datasets/NHIS/2022/adult22csv.zip"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download_zip(url: str, label: str) -> bytes:
    """Download a ZIP file and return raw bytes."""
    print(f"  Downloading {label}... ", end="", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MLGG/1.0)"})
    data = urllib.request.urlopen(req, timeout=300).read()
    print(f"{len(data) / 1024 / 1024:.1f} MB")
    return data


def extract_from_zip(data: bytes, extension: str = "") -> bytes:
    """Extract the first matching file from a ZIP archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if extension and not name.upper().endswith(extension.upper()):
                continue
            if name.startswith("__MACOSX"):
                continue
            print(f"  Extracting: {name}")
            return z.read(name)
    raise ValueError(f"No {extension} file found in ZIP")


def add_patient_id_and_time(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Add patient_id and event_time columns for MLGG pipeline compatibility."""
    rng = np.random.default_rng(seed)
    n = len(df)
    df = df.copy()
    df.insert(0, "patient_id", [f"P{i:06d}" for i in range(1, n + 1)])
    # Spread across 2 years for temporal split
    base = pd.Timestamp("2022-01-01")
    offsets = rng.integers(0, 730 * 24 * 60, size=n)  # minutes in 2 years
    df.insert(1, "event_time", [base + pd.Timedelta(minutes=int(m)) for m in sorted(offsets)])
    return df


def cdc_recode_binary(series: pd.Series) -> pd.Series:
    """Recode CDC binary variables: 1=Yes→1, 2=No→0, else→NaN."""
    return series.map({1.0: 1.0, 2.0: 0.0}).astype(float)


def cdc_clean_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Replace CDC missing codes (77, 88, 99, 7, 8, 9) with NaN."""
    df = df.copy()
    for col in df.select_dtypes(include=[np.number]).columns:
        vals = df[col]
        # Common CDC missing codes
        df.loc[vals.isin([77, 88, 99, 777, 888, 999, 7777, 8888, 9999, 77777, 88888, 99999]), col] = np.nan
    return df


def print_summary(df: pd.DataFrame, name: str, target_col: str = "y") -> None:
    """Print dataset summary."""
    n = len(df)
    n_pos = int(df[target_col].sum())
    prev = n_pos / n * 100
    n_feat = len([c for c in df.columns if c not in ("patient_id", "event_time", target_col)])
    n_miss = df.isnull().sum().sum()
    print(f"\n{'='*50}")
    print(f"{name}")
    print(f"{'='*50}")
    print(f"Total:      {n:,}")
    print(f"Positive:   {n_pos:,} ({prev:.1f}%)")
    print(f"Negative:   {n - n_pos:,} ({100 - prev:.1f}%)")
    print(f"Features:   {n_feat}")
    print(f"Missing:    {n_miss:,} null values ({n_miss / (n * n_feat) * 100:.1f}%)")


# ---------------------------------------------------------------------------
# BRFSS 2022
# ---------------------------------------------------------------------------

BRFSS_COLUMNS = {
    "_AGE80": "age",
    "_SEX": "sex",
    "_RACE": "race",
    "_EDUCAG": "education",
    "_INCOMG1": "income",
    "_BMI5": "bmi_x100",
    "PHYSHLTH": "days_phys_unwell",
    "MENTHLTH": "days_ment_unwell",
    "GENHLTH": "general_health",
    "_SMOKER3": "smoking_status",
    "_RFDRHV7": "heavy_drinking",
    "_TOTINDA": "physical_activity",
    "BPHIGH6": "high_bp",
    "TOLDHI3": "high_cholesterol",
    "CVDSTRK3": "stroke",
    "CHCCOPD3": "copd",
    "CHECKUP1": "last_checkup",
    "EXERANY2": "any_exercise",
    "DIABETE4": "_target_raw",
}


def prepare_brfss(output: Path, max_rows: int = 100_000) -> None:
    """Download and prepare BRFSS 2022 diabetes prediction dataset.

    Source: CDC Behavioral Risk Factor Surveillance System
    Task: Predict diabetes status (self-reported)
    Target: DIABETE4 == 1 (told by doctor they have diabetes)

    Excluded from features (definition variable leakage):
    - Diabetes medication variables
    - Insulin use variables
    - Pre-diabetes/borderline variables
    """
    print("\n" + "=" * 50)
    print("BRFSS 2022 — Diabetes Prediction")
    print("=" * 50)

    raw = download_zip(BRFSS_URL, "BRFSS 2022")

    # Extract XPT to temp file (1.1GB uncompressed — too large for memory)
    print("  Extracting XPT to temp file...")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xpt_name = [n for n in z.namelist() if n.strip().upper().endswith(".XPT") and not n.startswith("__")][0]
        tmp_path = Path(tempfile.mkdtemp()) / xpt_name
        z.extract(xpt_name, tmp_path.parent)
        tmp_path = tmp_path.parent / xpt_name
    del raw  # free ~80MB

    print(f"  Parsing XPT format ({tmp_path.stat().st_size / 1024 / 1024:.0f} MB, this may take a minute)...")
    try:
        df = pd.read_sas(str(tmp_path), format="xport")
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"  Raw: {df.shape[0]:,} rows × {df.shape[1]} cols")

    # Select and rename columns
    available = {c: v for c, v in BRFSS_COLUMNS.items() if c in df.columns}
    missing_cols = set(BRFSS_COLUMNS.keys()) - set(available.keys())
    if missing_cols:
        print(f"  Warning: columns not found: {missing_cols}")

    df = df[list(available.keys())].copy()
    df.columns = [available[c] for c in df.columns]

    # Filter to valid diabetes responses (1=Yes, 3=No)
    df = df[df["_target_raw"].isin([1.0, 3.0])].copy()
    df["y"] = (df["_target_raw"] == 1.0).astype(int)
    df = df.drop(columns=["_target_raw"])
    print(f"  After diabetes filter: {len(df):,} rows")

    # Clean missing values
    df = cdc_clean_missing(df)

    # Recode BMI
    if "bmi_x100" in df.columns:
        df["bmi"] = df["bmi_x100"] / 100.0
        df = df.drop(columns=["bmi_x100"])

    # Recode binary variables
    for col in ["high_bp", "high_cholesterol", "stroke", "copd", "any_exercise"]:
        if col in df.columns:
            df[col] = cdc_recode_binary(df[col])

    # Subsample if needed
    if max_rows > 0 and len(df) > max_rows:
        df = df.sample(n=max_rows, random_state=42).reset_index(drop=True)
        print(f"  Subsampled to {max_rows:,} rows")

    # Add pipeline columns
    df = add_patient_id_and_time(df, seed=2022)

    # Reorder: patient_id, event_time, y, features...
    cols = ["patient_id", "event_time", "y"] + [c for c in df.columns if c not in ("patient_id", "event_time", "y")]
    df = df[cols]

    print_summary(df, "BRFSS 2022 Diabetes Dataset")

    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"Output: {output} ({output.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# NHIS 2022
# ---------------------------------------------------------------------------

NHIS_COLUMNS = {
    "AGEP_A": "age",
    "SEX_A": "sex",
    "HISPALLP_A": "hispanic",
    "RACEASIP_A": "race",
    "EDUC_A": "education",
    "RATCAT_A": "income_ratio",
    "BMICAT_A": "bmi_category",
    "HEIGHTTC_A": "height_inches",
    "WEIGHTLBTC_A": "weight_lbs",
    "PHSTAT_A": "health_status",
    "HYPEV_A": "hypertension_ever",
    "CHLEV_A": "high_cholesterol_ever",
    "CHDEV_A": "coronary_hd_ever",
    "STREV_A": "stroke_ever",
    "COPDEV_A": "copd_ever",
    "SMKEV_A": "ever_smoked",
    "ALC12MNO_A": "alcohol_freq_12m",
    "VIGFREQW_A": "vigorous_activity_freq",
    "COVER_A": "has_insurance",
    "USUALPL_A": "has_usual_care",
    "DIBEV_A": "_target_raw",
}


def prepare_nhis(output: Path) -> None:
    """Download and prepare NHIS 2022 diabetes prediction dataset.

    Source: CDC National Health Interview Survey
    Task: Predict diabetes status (self-reported, ever told by doctor)
    Target: DIBEV_A == 1

    Excluded from features (definition variable leakage):
    - Diabetes medication / insulin variables
    - Age at diabetes diagnosis
    - Diabetes management variables
    """
    print("\n" + "=" * 50)
    print("NHIS 2022 — Diabetes Prediction")
    print("=" * 50)

    raw = download_zip(NHIS_URL, "NHIS 2022 Adult")
    csv_data = extract_from_zip(raw, ".csv")

    df = pd.read_csv(io.BytesIO(csv_data))
    print(f"  Raw: {df.shape[0]:,} rows × {df.shape[1]} cols")

    # Select and rename columns
    available = {c: v for c, v in NHIS_COLUMNS.items() if c in df.columns}
    missing_cols = set(NHIS_COLUMNS.keys()) - set(available.keys())
    if missing_cols:
        print(f"  Warning: columns not found: {missing_cols}")

    df = df[list(available.keys())].copy()
    df.columns = [available[c] for c in df.columns]

    # Filter to valid diabetes responses (1=Yes, 2=No)
    df = df[df["_target_raw"].isin([1, 2])].copy()
    df["y"] = (df["_target_raw"] == 1).astype(int)
    df = df.drop(columns=["_target_raw"])
    print(f"  After diabetes filter: {len(df):,} rows")

    # Clean NHIS missing codes (7=Refused, 8=Not ascertained, 9=Don't know)
    for col in df.select_dtypes(include=[np.number]).columns:
        if col == "y":
            continue
        vals = df[col]
        # Top-coded/missing values depend on variable range
        # Common: 7,8,9 for single-digit; 97,98,99 for two-digit; 997,998,999 for three-digit
        df.loc[vals.isin([7, 8, 9, 97, 98, 99, 997, 998, 999]), col] = np.nan

    # Recode binary variables (1=Yes, 2=No → 1/0)
    for col in ["hypertension_ever", "high_cholesterol_ever", "coronary_hd_ever",
                 "stroke_ever", "copd_ever", "ever_smoked"]:
        if col in df.columns:
            df[col] = cdc_recode_binary(df[col])

    # Add pipeline columns
    df = add_patient_id_and_time(df, seed=2023)

    # Reorder
    cols = ["patient_id", "event_time", "y"] + [c for c in df.columns if c not in ("patient_id", "event_time", "y")]
    df = df[cols]

    print_summary(df, "NHIS 2022 Diabetes Dataset")

    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"Output: {output} ({output.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download CDC public health datasets for MLGG pipeline.",
    )
    parser.add_argument(
        "dataset",
        choices=["brfss", "nhis", "all"],
        help="Dataset to download. brfss=BRFSS 2022 (~100K), nhis=NHIS 2022 (~28K).",
    )
    parser.add_argument("--output", default="", help="Output CSV path.")
    parser.add_argument("--max-rows", type=int, default=100_000,
                        help="Max rows for BRFSS (default: 100K). Set 0 for all ~350K.")
    args = parser.parse_args()

    examples_dir = SCRIPT_DIR

    if args.dataset in ("brfss", "all"):
        out = Path(args.output) if args.output and args.dataset != "all" else examples_dir / "brfss2022_diabetes.csv"
        prepare_brfss(out, max_rows=args.max_rows)

    if args.dataset in ("nhis", "all"):
        out = Path(args.output) if args.output and args.dataset != "all" else examples_dir / "nhis2022_diabetes.csv"
        prepare_nhis(out)

    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
