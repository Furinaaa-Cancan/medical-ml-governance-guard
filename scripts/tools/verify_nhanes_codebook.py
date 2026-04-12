#!/usr/bin/env python3
"""Verify NHANES codebook SQLite against CDC XPT source files.

Downloads XPT files from CDC, reads actual variable names and value
distributions, and compares against our codebook database.

This is the ground-truth verification — XPT files are the authoritative
source, not HTML pages or third-party metadata.

Usage:
  python3 scripts/tools/verify_nhanes_codebook.py --cycle 2017-2018
  python3 scripts/tools/verify_nhanes_codebook.py --cycle 2021-2023 --max-tables 10
  python3 scripts/tools/verify_nhanes_codebook.py --all-cycles --max-tables 5
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_codebook.sqlite"
CDC_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public"

CYCLE_TO_CDC_PATH = {
    "1999-2000": "1999-2000",
    "2001-2002": "2001-2002",
    "2003-2004": "2003-2004",
    "2005-2006": "2005-2006",
    "2007-2008": "2007-2008",
    "2009-2010": "2009-2010",
    "2011-2012": "2011-2012",
    "2013-2014": "2013-2014",
    "2015-2016": "2015-2016",
    "2017-2018": "2017",
    "2019-2020": "2017",  # Pre-pandemic uses P_ prefix
    "2021-2023": "2021",
}


def download_xpt(table_name: str, cycle: str) -> Optional[pd.DataFrame]:
    """Download and read an XPT file from CDC."""
    cdc_path = CYCLE_TO_CDC_PATH.get(cycle)
    if not cdc_path:
        return None

    url = f"{CDC_BASE}/{cdc_path}/DataFiles/{table_name}.xpt"
    tmp = tempfile.mktemp(suffix=".xpt")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MLGG-Verify/1.0"})
        urllib.request.urlretrieve(url, tmp)
        df = pd.read_sas(tmp, format="xport")
        return df
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def verify_table(
    conn: sqlite3.Connection,
    table_name: str,
    cycle: str,
    df: pd.DataFrame,
) -> Dict[str, Any]:
    """Verify a single table against XPT data."""
    result = {
        "table": table_name,
        "cycle": cycle,
        "xpt_columns": len(df.columns),
        "xpt_rows": len(df),
        "issues": [],
    }

    xpt_cols = set(df.columns)

    # Get our codebook variables for this table
    our_vars = conn.execute(
        "SELECT variable_code FROM variables WHERE table_name=?",
        (table_name,),
    ).fetchall()
    our_cols = set(r[0] for r in our_vars)

    # Compare column lists
    missing_in_ours = xpt_cols - our_cols
    extra_in_ours = our_cols - xpt_cols

    if missing_in_ours:
        result["issues"].append({
            "type": "MISSING_VARIABLE",
            "detail": f"XPT has {len(missing_in_ours)} vars we don't: {sorted(missing_in_ours)[:5]}",
        })

    if extra_in_ours:
        result["issues"].append({
            "type": "EXTRA_VARIABLE",
            "detail": f"We have {len(extra_in_ours)} vars XPT doesn't: {sorted(extra_in_ours)[:5]}",
        })

    result["columns_match"] = len(missing_in_ours) == 0 and len(extra_in_ours) == 0
    result["columns_in_both"] = len(xpt_cols & our_cols)

    # Verify value counts for categorical variables (sample up to 5)
    value_checks = 0
    value_match = 0
    value_mismatch = 0

    for col in sorted(xpt_cols & our_cols)[:10]:
        vid = f"{col}@{table_name}"
        our_codes = conn.execute(
            "SELECT code, label, count FROM value_codes WHERE variable_id=? AND is_missing=0",
            (vid,),
        ).fetchall()

        if not our_codes:
            continue

        # Check if this is a coded variable (not continuous range)
        is_coded = all(not _is_range(r[0]) for r in our_codes)
        if not is_coded:
            continue

        value_checks += 1
        xpt_vc = df[col].value_counts(dropna=True)

        all_match = True
        for code_str, label, expected_count in our_codes:
            try:
                code_val = float(code_str)
            except (ValueError, TypeError):
                continue

            actual = int(xpt_vc.get(code_val, 0))
            expected = int(expected_count) if expected_count else 0

            if actual != expected:
                all_match = False
                result["issues"].append({
                    "type": "COUNT_MISMATCH",
                    "detail": f"{col}={code_str}: expected {expected}, XPT has {actual}",
                })

        if all_match:
            value_match += 1
        else:
            value_mismatch += 1

    result["value_checks"] = value_checks
    result["value_match"] = value_match
    result["value_mismatch"] = value_mismatch

    return result


def _is_range(code: str) -> bool:
    """Check if a code looks like a range (e.g., '3.2 to 17.1')."""
    return " to " in code.lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify NHANES codebook against CDC XPT files")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cycle", type=str, help="Specific cycle to verify (e.g., 2017-2018)")
    parser.add_argument("--all-cycles", action="store_true", help="Verify all cycles")
    parser.add_argument("--max-tables", type=int, default=10, help="Max tables per cycle")
    parser.add_argument("--output", type=str, help="Output JSON report path")
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))

    if args.all_cycles:
        cycles = sorted(CYCLE_TO_CDC_PATH.keys())
    elif args.cycle:
        cycles = [args.cycle]
    else:
        cycles = ["2017-2018"]  # default

    all_results = []
    total_tables = 0
    total_col_match = 0
    total_val_checks = 0
    total_val_match = 0

    for cycle in cycles:
        print(f"\n{'='*60}")
        print(f"Cycle: {cycle}")
        print(f"{'='*60}")

        # Get tables for this cycle
        tables = conn.execute(
            "SELECT DISTINCT table_name FROM variables WHERE cycle=? ORDER BY table_name",
            (cycle,),
        ).fetchall()

        tables_to_check = [t[0] for t in tables][:args.max_tables]
        print(f"Tables to verify: {len(tables_to_check)} (of {len(tables)} total)")

        for i, table_name in enumerate(tables_to_check):
            print(f"  [{i+1}/{len(tables_to_check)}] {table_name}...", end="", flush=True)

            df = download_xpt(table_name, cycle)
            if df is None:
                print(" SKIP (download failed)")
                continue

            result = verify_table(conn, table_name, cycle, df)
            all_results.append(result)
            total_tables += 1

            if result["columns_match"]:
                total_col_match += 1
            total_val_checks += result["value_checks"]
            total_val_match += result["value_match"]

            issues = len(result["issues"])
            status = "OK" if issues == 0 else f"{issues} issues"
            cols = f"{result['columns_in_both']}/{result['xpt_columns']} cols"
            vals = f"{result['value_match']}/{result['value_checks']} vals"
            print(f" {result['xpt_rows']} rows, {cols}, {vals} — {status}")

            time.sleep(0.3)  # rate limit

    # Summary
    print(f"\n{'='*60}")
    print(f"VERIFICATION SUMMARY")
    print(f"{'='*60}")
    print(f"Tables verified:     {total_tables}")
    print(f"Column lists match:  {total_col_match}/{total_tables} ({total_col_match/max(total_tables,1)*100:.0f}%)")
    print(f"Value code checks:   {total_val_match}/{total_val_checks} ({total_val_match/max(total_val_checks,1)*100:.0f}%)")

    total_issues = sum(len(r["issues"]) for r in all_results)
    print(f"Total issues found:  {total_issues}")

    if args.output:
        report = {
            "total_tables": total_tables,
            "column_match_rate": total_col_match / max(total_tables, 1),
            "value_match_rate": total_val_match / max(total_val_checks, 1),
            "total_issues": total_issues,
            "results": all_results,
        }
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport: {args.output}")

    conn.close()
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
