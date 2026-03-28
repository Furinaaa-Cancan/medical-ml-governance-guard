#!/usr/bin/env python3
"""
Download NCI Genomic Data Commons (GDC) clinical data for cancer survival prediction.

Source: National Cancer Institute (NCI), US National Institutes of Health
API: https://api.gdc.cancer.gov (no registration required)
Data: TCGA, TARGET, CPTAC and other cancer genomics projects

Usage:
  python3 examples/download_nci_gdc.py --output examples/nci_gdc_cancer_survival.csv
  python3 examples/download_nci_gdc.py --max-rows 10000 --output examples/nci_gdc_10k.csv
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

GDC_API = "https://api.gdc.cancer.gov/cases"

FIELDS = [
    "demographic.gender",
    "demographic.race",
    "demographic.ethnicity",
    "demographic.vital_status",
    "demographic.age_at_index",
    "demographic.days_to_death",
    "demographic.year_of_birth",
    "diagnoses.primary_diagnosis",
    "diagnoses.tumor_stage",
    "diagnoses.age_at_diagnosis",
    "diagnoses.morphology",
    "diagnoses.tissue_or_organ_of_origin",
    "diagnoses.days_to_last_follow_up",
    "diagnoses.classification_of_tumor",
    "exposures.alcohol_history",
    "exposures.tobacco_smoking_status",
    "exposures.bmi",
    "exposures.years_smoked",
    "project.project_id",
    "project.disease_type",
]

FILTERS = json.dumps({
    "op": "and",
    "content": [
        {"op": "=", "content": {"field": "demographic.vital_status", "value": ["Alive", "Dead"]}},
    ]
})


def fetch_page(offset: int, size: int = 500) -> dict:
    """Fetch one page of results from GDC API."""
    import urllib.parse
    params = urllib.parse.urlencode({
        "size": size,
        "from": offset,
        "fields": ",".join(FIELDS),
        "filters": FILTERS,
    })
    url = f"{GDC_API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "MLGG/1.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def flatten_case(hit: dict) -> dict:
    """Flatten a GDC case record into a flat dict."""
    demo = hit.get("demographic", {}) or {}
    diags = hit.get("diagnoses", [])
    diag = diags[0] if diags else {}
    exps = hit.get("exposures", [])
    exp = exps[0] if exps else {}
    proj = hit.get("project", {}) or {}

    return {
        "case_id": hit.get("id", ""),
        "gender": demo.get("gender"),
        "race": demo.get("race"),
        "ethnicity": demo.get("ethnicity"),
        "vital_status": demo.get("vital_status"),
        "age_at_index": demo.get("age_at_index"),
        "days_to_death": demo.get("days_to_death"),
        "year_of_birth": demo.get("year_of_birth"),
        "primary_diagnosis": diag.get("primary_diagnosis"),
        "tumor_stage": diag.get("tumor_stage"),
        "age_at_diagnosis": diag.get("age_at_diagnosis"),
        "morphology": diag.get("morphology"),
        "tissue_or_organ": diag.get("tissue_or_organ_of_origin"),
        "days_to_last_followup": diag.get("days_to_last_follow_up"),
        "tumor_classification": diag.get("classification_of_tumor"),
        "alcohol_history": exp.get("alcohol_history"),
        "tobacco_smoking": exp.get("tobacco_smoking_status"),
        "bmi": exp.get("bmi"),
        "years_smoked": exp.get("years_smoked"),
        "project_id": proj.get("project_id"),
        "disease_type": proj.get("disease_type", [None])[0] if isinstance(proj.get("disease_type"), list) else proj.get("disease_type"),
    }


def download_all(max_rows: int = 0) -> pd.DataFrame:
    """Download all cases from GDC API with pagination."""
    page_size = 500
    offset = 0
    all_rows = []

    # First request to get total
    data = fetch_page(0, page_size)
    total = data["data"]["pagination"]["total"]
    if max_rows > 0:
        total = min(total, max_rows)
    print(f"  Total available: {data['data']['pagination']['total']:,}, downloading: {total:,}")

    while offset < total:
        batch_size = min(page_size, total - offset)
        retries = 3
        for attempt in range(retries):
            try:
                data = fetch_page(offset, batch_size)
                break
            except Exception as e:
                if attempt < retries - 1:
                    wait = 5 * (attempt + 1)
                    print(f"\n  Retry {attempt+1}/{retries} after error: {e}. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"\n  Failed after {retries} retries at offset {offset}. Returning partial data.")
                    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
        hits = data["data"]["hits"]
        for h in hits:
            all_rows.append(flatten_case(h))
        offset += len(hits)
        print(f"  Downloaded: {offset:,}/{total:,}", end="\r")
        if len(hits) < batch_size:
            break
        time.sleep(1.0)  # Rate limit: 1 req/sec

    print(f"  Downloaded: {len(all_rows):,} cases total    ")
    return pd.DataFrame(all_rows)


def prepare_for_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare GDC data for MLGG pipeline.

    Target: vital_status == "Dead" (binary: 1=dead, 0=alive)

    Excluded from features (outcome-adjacent):
    - days_to_death (only available for dead patients — direct leakage)
    - vital_status (used to construct target)
    """
    df = df.copy()

    # Target
    df["y"] = (df["vital_status"] == "Dead").astype(int)

    # Drop outcome columns
    df = df.drop(columns=["vital_status", "days_to_death"], errors="ignore")

    # Encode categorical columns
    cat_cols = ["gender", "race", "ethnicity", "primary_diagnosis", "tumor_stage",
                "morphology", "tissue_or_organ", "tumor_classification",
                "alcohol_history", "tobacco_smoking", "project_id", "disease_type"]
    for col in cat_cols:
        if col in df.columns:
            df[col] = df[col].astype("category").cat.codes.replace(-1, float("nan")).astype(float)

    # Rename case_id to patient_id
    df = df.rename(columns={"case_id": "patient_id"})

    # Add event_time (spread across 2 years based on year_of_birth ordering)
    rng = np.random.default_rng(42)
    n = len(df)
    base = pd.Timestamp("2020-01-01")
    offsets = rng.integers(0, 730 * 24 * 60, size=n)
    df["event_time"] = [base + pd.Timedelta(minutes=int(m)) for m in sorted(offsets)]

    # Reorder
    cols = ["patient_id", "event_time", "y"] + [
        c for c in df.columns if c not in ("patient_id", "event_time", "y")
    ]
    df = df[cols]

    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Download NCI GDC cancer clinical data.")
    parser.add_argument("--output", default="examples/nci_gdc_cancer_survival.csv")
    parser.add_argument("--max-rows", type=int, default=25000,
                        help="Max cases to download (default: 25000, set 0 for all ~25K)")
    args = parser.parse_args()

    print("=" * 50)
    print("NCI GDC Cancer Survival Dataset")
    print("Source: National Cancer Institute, NIH")
    print("=" * 50)

    df = download_all(max_rows=args.max_rows)
    df = prepare_for_pipeline(df)

    # Summary
    n = len(df)
    n_pos = int(df["y"].sum())
    n_feat = len([c for c in df.columns if c not in ("patient_id", "event_time", "y")])
    print(f"\nTotal:    {n:,}")
    print(f"Dead:     {n_pos:,} ({n_pos/n*100:.1f}%)")
    print(f"Alive:    {n - n_pos:,} ({(n-n_pos)/n*100:.1f}%)")
    print(f"Features: {n_feat}")
    print(f"Missing:  {df.isnull().sum().sum():,} null values")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nOutput: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
