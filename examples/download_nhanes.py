#!/usr/bin/env python3
"""
Download NHANES data for diabetes prediction task.

Downloads demographics, labs, examination, and questionnaire data from
CDC NHANES 2017-2020 (pre-pandemic). Merges into a single CSV ready
for the MLGG pipeline.

Task: Predict diabetes (HbA1c >= 6.5% or self-reported diagnosed diabetes)
Split: Temporal — 2017-2018 for train, 2019-March2020 for test
Features: Age, BMI, blood pressure, lipids, lifestyle, family history

Usage:
  python3 examples/download_nhanes.py --output examples/nhanes_diabetes.csv
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# NHANES file URLs (CDC public data)
# ---------------------------------------------------------------------------

NHANES_DATA_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public"

# 2017-2018 (cycle J)
FILES_2017 = {
    "demo": f"{NHANES_DATA_BASE}/2017/DataFiles/DEMO_J.XPT",
    "bmx": f"{NHANES_DATA_BASE}/2017/DataFiles/BMX_J.XPT",
    "bpx": f"{NHANES_DATA_BASE}/2017/DataFiles/BPXO_J.XPT",
    "ghb": f"{NHANES_DATA_BASE}/2017/DataFiles/GHB_J.XPT",
    "glu": f"{NHANES_DATA_BASE}/2017/DataFiles/GLU_J.XPT",
    "tchol": f"{NHANES_DATA_BASE}/2017/DataFiles/TCHOL_J.XPT",
    "hdl": f"{NHANES_DATA_BASE}/2017/DataFiles/HDL_J.XPT",
    "trigly": f"{NHANES_DATA_BASE}/2017/DataFiles/TRIGLY_J.XPT",
    "diq": f"{NHANES_DATA_BASE}/2017/DataFiles/DIQ_J.XPT",
    "bpq": f"{NHANES_DATA_BASE}/2017/DataFiles/BPQ_J.XPT",
    "smq": f"{NHANES_DATA_BASE}/2017/DataFiles/SMQ_J.XPT",
    "alq": f"{NHANES_DATA_BASE}/2017/DataFiles/ALQ_J.XPT",
    "paq": f"{NHANES_DATA_BASE}/2017/DataFiles/PAQ_J.XPT",
    "mcq": f"{NHANES_DATA_BASE}/2017/DataFiles/MCQ_J.XPT",
}

# 2019-2020 pre-pandemic (P_ prefix files)
FILES_2020 = {
    "demo": f"{NHANES_DATA_BASE}/2019/DataFiles/P_DEMO.XPT",
    "bmx": f"{NHANES_DATA_BASE}/2019/DataFiles/P_BMX.XPT",
    "bpx": f"{NHANES_DATA_BASE}/2019/DataFiles/P_BPXO.XPT",
    "ghb": f"{NHANES_DATA_BASE}/2019/DataFiles/P_GHB.XPT",
    "glu": f"{NHANES_DATA_BASE}/2019/DataFiles/P_GLU.XPT",
    "tchol": f"{NHANES_DATA_BASE}/2019/DataFiles/P_TCHOL.XPT",
    "hdl": f"{NHANES_DATA_BASE}/2019/DataFiles/P_HDL.XPT",
    "trigly": f"{NHANES_DATA_BASE}/2019/DataFiles/P_TRIGLY.XPT",
    "diq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_DIQ.XPT",
    "bpq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_BPQ.XPT",
    "smq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_SMQ.XPT",
    "alq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_ALQ.XPT",
    "paq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_PAQ.XPT",
    "mcq": f"{NHANES_DATA_BASE}/2019/DataFiles/P_MCQ.XPT",
}


def download_xpt(url: str, label: str) -> Optional[pd.DataFrame]:
    """Download a SAS XPT file from CDC and return as DataFrame."""
    print(f"  Downloading {label}... ", end="", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MLGG/1.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        data = resp.read()
        df = pd.read_sas(io.BytesIO(data), format="xport")
        print(f"{len(df)} rows, {len(df.columns)} cols")
        return df
    except Exception as e:
        print(f"FAILED: {e}")
        return None


def download_cycle(files: Dict[str, str], cycle_label: str) -> Dict[str, pd.DataFrame]:
    """Download all files for one NHANES cycle."""
    print(f"\n{'='*50}")
    print(f"Downloading NHANES {cycle_label}")
    print(f"{'='*50}")
    dfs = {}
    for key, url in files.items():
        df = download_xpt(url, f"{cycle_label}/{key}")
        if df is not None:
            dfs[key] = df
    return dfs


def build_diabetes_dataset(dfs: Dict[str, pd.DataFrame], cycle: str) -> pd.DataFrame:
    """Merge NHANES tables and build diabetes prediction features."""
    # Start with demographics
    demo = dfs.get("demo")
    if demo is None:
        return pd.DataFrame()

    # SEQN is the unique participant ID
    merged = demo[["SEQN", "RIDAGEYR", "RIAGENDR", "RIDRETH3"]].copy()
    merged.columns = ["SEQN", "age", "gender", "race_ethnicity"]

    # Filter adults (>= 18)
    merged = merged[merged["age"] >= 18].copy()

    # BMI
    if "bmx" in dfs:
        bmx = dfs["bmx"][["SEQN", "BMXBMI", "BMXWAIST"]].copy()
        bmx.columns = ["SEQN", "bmi", "waist_circumference"]
        merged = merged.merge(bmx, on="SEQN", how="left")

    # Blood pressure
    if "bpx" in dfs:
        bpx = dfs["bpx"].copy()
        sbp_cols = [c for c in bpx.columns if c.startswith("BPXOSY")]
        dbp_cols = [c for c in bpx.columns if c.startswith("BPXODI")]
        if sbp_cols:
            bpx["sbp_mean"] = bpx[sbp_cols].mean(axis=1)
        if dbp_cols:
            bpx["dbp_mean"] = bpx[dbp_cols].mean(axis=1)
        bp_cols = ["SEQN"] + [c for c in ["sbp_mean", "dbp_mean"] if c in bpx.columns]
        merged = merged.merge(bpx[bp_cols], on="SEQN", how="left")

    # HbA1c (target variable component)
    if "ghb" in dfs:
        ghb = dfs["ghb"][["SEQN", "LBXGH"]].copy()
        ghb.columns = ["SEQN", "hba1c"]
        merged = merged.merge(ghb, on="SEQN", how="left")

    # Fasting glucose
    if "glu" in dfs:
        glu = dfs["glu"][["SEQN", "LBXGLU"]].copy()
        glu.columns = ["SEQN", "fasting_glucose"]
        merged = merged.merge(glu, on="SEQN", how="left")

    # Lipids
    if "tchol" in dfs:
        tc = dfs["tchol"][["SEQN", "LBXTC"]].copy()
        tc.columns = ["SEQN", "total_cholesterol"]
        merged = merged.merge(tc, on="SEQN", how="left")
    if "hdl" in dfs:
        hdl = dfs["hdl"][["SEQN", "LBDHDD"]].copy()
        hdl.columns = ["SEQN", "hdl"]
        merged = merged.merge(hdl, on="SEQN", how="left")
    if "trigly" in dfs:
        tg = dfs["trigly"][["SEQN", "LBXTR"]].copy()
        tg.columns = ["SEQN", "triglycerides"]
        merged = merged.merge(tg, on="SEQN", how="left")

    # Diabetes questionnaire (target component + risk factors)
    if "diq" in dfs:
        diq = dfs["diq"].copy()
        diq_cols = {"SEQN": "SEQN"}
        if "DIQ010" in diq.columns:
            diq_cols["DIQ010"] = "doctor_told_diabetes"
        if "DIQ160" in diq.columns:
            diq_cols["DIQ160"] = "prediabetes"
        if "DIQ170" in diq.columns:
            diq_cols["DIQ170"] = "at_risk_diabetes"
        if "DIQ172" in diq.columns:
            diq_cols["DIQ172"] = "family_history_diabetes"
        diq_sub = diq[list(diq_cols.keys())].copy()
        diq_sub.columns = list(diq_cols.values())
        merged = merged.merge(diq_sub, on="SEQN", how="left")

    # Smoking
    if "smq" in dfs:
        smq = dfs["smq"].copy()
        if "SMQ020" in smq.columns:
            smq_sub = smq[["SEQN", "SMQ020"]].copy()
            smq_sub.columns = ["SEQN", "ever_smoked"]
            merged = merged.merge(smq_sub, on="SEQN", how="left")

    # Blood pressure medication
    if "bpq" in dfs:
        bpq = dfs["bpq"].copy()
        if "BPQ050A" in bpq.columns:
            bpq_sub = bpq[["SEQN", "BPQ050A"]].copy()
            bpq_sub.columns = ["SEQN", "bp_medication"]
            merged = merged.merge(bpq_sub, on="SEQN", how="left")

    # Medical conditions (family history)
    if "mcq" in dfs:
        mcq = dfs["mcq"].copy()
        mcq_keep = {"SEQN": "SEQN"}
        if "MCQ160C" in mcq.columns:
            mcq_keep["MCQ160C"] = "coronary_heart_disease"
        if "MCQ160F" in mcq.columns:
            mcq_keep["MCQ160F"] = "stroke"
        if len(mcq_keep) > 1:
            mcq_sub = mcq[list(mcq_keep.keys())].copy()
            mcq_sub.columns = list(mcq_keep.values())
            merged = merged.merge(mcq_sub, on="SEQN", how="left")

    # Add cycle label for temporal split
    merged["nhanes_cycle"] = cycle

    return merged


def create_target(df: pd.DataFrame) -> pd.DataFrame:
    """Create binary diabetes target.

    Positive if:
    - HbA1c >= 6.5%, OR
    - Doctor told diabetes == 1 (Yes)

    Exclude from features:
    - hba1c (used to define target — would be definition variable leakage)
    - fasting_glucose (strongly collinear with target definition)
    - doctor_told_diabetes (part of target definition)
    - prediabetes, at_risk_diabetes (target-adjacent)
    """
    df = df.copy()

    # Build target
    hba1c_pos = df["hba1c"] >= 6.5 if "hba1c" in df.columns else pd.Series(False, index=df.index)
    doctor_pos = df["doctor_told_diabetes"] == 1.0 if "doctor_told_diabetes" in df.columns else pd.Series(False, index=df.index)
    df["y"] = (hba1c_pos | doctor_pos).astype(int)

    # Remove target-defining and target-adjacent variables from features
    drop_cols = [
        "hba1c", "fasting_glucose",
        "doctor_told_diabetes", "prediabetes", "at_risk_diabetes",
    ]
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])

    return df


def clean_features(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and encode features. Minimal preprocessing — rest left to MLGG pipeline."""
    df = df.copy()

    # Encode gender: 1=Male, 2=Female → 0/1
    if "gender" in df.columns:
        df["gender"] = (df["gender"] == 2).astype(float)  # 1 = female

    # Encode binary questionnaire fields (1=Yes, 2=No → 1/0)
    binary_cols = [
        "ever_smoked", "bp_medication", "family_history_diabetes",
        "coronary_heart_disease", "stroke",
    ]
    for col in binary_cols:
        if col in df.columns:
            df[col] = df[col].map({1.0: 1.0, 2.0: 0.0})

    # Race/ethnicity: one-hot (keep as numeric codes for now, let pipeline handle)
    # 1=Mexican, 2=Other Hispanic, 3=White, 4=Black, 6=Asian, 7=Other
    if "race_ethnicity" in df.columns:
        df["race_ethnicity"] = df["race_ethnicity"].astype(float)

    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Download NHANES diabetes prediction dataset.")
    parser.add_argument("--output", default="examples/nhanes_diabetes.csv", help="Output CSV path.")
    parser.add_argument("--cycles", default="2017-2018", choices=["2017-2018", "both"],
                        help="Which cycles to download. 'both' includes 2019-2020 for temporal test set.")
    args = parser.parse_args()

    # Download 2017-2018
    dfs_2017 = download_cycle(FILES_2017, "2017-2018")
    df_2017 = build_diabetes_dataset(dfs_2017, "2017-2018")
    print(f"\n2017-2018: {len(df_2017)} adults")

    all_dfs = [df_2017]

    if args.cycles == "both":
        dfs_2020 = download_cycle(FILES_2020, "2019-2020")
        df_2020 = build_diabetes_dataset(dfs_2020, "2019-2020")
        print(f"2019-2020: {len(df_2020)} adults")
        all_dfs.append(df_2020)

    # Combine
    df = pd.concat(all_dfs, ignore_index=True)
    print(f"\nCombined: {len(df)} adults")

    # Create target
    df = create_target(df)

    # Clean features
    df = clean_features(df)

    # Rename SEQN to patient_id
    df = df.rename(columns={"SEQN": "patient_id"})

    # Move y to last column
    cols = [c for c in df.columns if c != "y"] + ["y"]
    df = df[cols]

    # Summary
    n_pos = df["y"].sum()
    n_neg = len(df) - n_pos
    prevalence = n_pos / len(df) * 100
    n_features = len([c for c in df.columns if c not in ("patient_id", "y", "nhanes_cycle")])

    print(f"\n{'='*50}")
    print(f"NHANES Diabetes Prediction Dataset")
    print(f"{'='*50}")
    print(f"Total:      {len(df)}")
    print(f"Positive:   {int(n_pos)} ({prevalence:.1f}%)")
    print(f"Negative:   {int(n_neg)} ({100-prevalence:.1f}%)")
    print(f"Features:   {n_features}")
    print(f"Missing:    {df.isnull().sum().sum()} total null values")

    if args.cycles == "both":
        for cycle in df["nhanes_cycle"].unique():
            sub = df[df["nhanes_cycle"] == cycle]
            print(f"  {cycle}: N={len(sub)}, pos={int(sub['y'].sum())} ({sub['y'].mean()*100:.1f}%)")

    # Save
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nOutput: {out}")
    print(f"Size: {out.stat().st_size / 1024:.0f} KB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
