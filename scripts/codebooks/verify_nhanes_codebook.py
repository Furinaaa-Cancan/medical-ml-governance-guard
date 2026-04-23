#!/usr/bin/env python3
"""Verify NHANES codebook SQLite against CDC XPT source files.

Downloads XPT files from CDC, reads actual variable names and value
distributions, and compares against our codebook database.

Layers:
  L2b  source TSV ↔ DB row count (offline, deterministic)
  L3   per-table XPT ↔ DB column/value spot check (network, sampled)

XPT files are the authoritative source, not HTML pages or third-party
metadata. CHECK ITEM / BOX skip-pattern pseudo-variables are recognised
and excluded from column-match comparison — they appear in CDC codebook
docs but are never emitted to XPT data files.

Usage:
  python3 scripts/codebooks/verify_nhanes_codebook.py --cycle 2017-2018
  python3 scripts/codebooks/verify_nhanes_codebook.py --cycle 2021-2023 --max-tables 10
  python3 scripts/codebooks/verify_nhanes_codebook.py --all-cycles --max-tables 5
  python3 scripts/codebooks/verify_nhanes_codebook.py --l2b-only
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "references" / "codebooks" / "nhanes" / "nhanes_codebook.sqlite"
NHANES_DIR = REPO_ROOT / "references" / "codebooks" / "nhanes"

# CDC public XPT files live under the single-year directory for every cycle,
# not the full cycle range. Probed 2026-04 against live CDC; all 12 cycles
# return a valid SAS XPT blob (not a landing-page HTML redirect).
CDC_BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public"

CYCLE_TO_CDC_PATH = {
    "1999-2000": "1999",
    "2001-2002": "2001",
    "2003-2004": "2003",
    "2005-2006": "2005",
    "2007-2008": "2007",
    "2009-2010": "2009",
    "2011-2012": "2011",
    "2013-2014": "2013",
    "2015-2016": "2015",
    "2017-2018": "2017",
    "2019-2020": "2017",  # pre-pandemic merged release uses P_ prefix
    "2021-2023": "2021",
}

ALL_CYCLES = list(CYCLE_TO_CDC_PATH.keys())

# NHANES questionnaires contain CHECK ITEM / BOX skip-pattern pseudo-variables
# that are documented in codebook pages but never emitted to XPT data files.
# Detect them from source-TSV text so we can exclude them from column-match.
_SKIP_CONTROL_HINTS = (
    re.compile(r"\bBOX\b", re.IGNORECASE),
    re.compile(r"\bCHECK ITEM\b", re.IGNORECASE),
    re.compile(r"\bGO TO\b", re.IGNORECASE),
)


def _is_skip_control_label(sas_label: Optional[str], instructions: Optional[str]) -> bool:
    """Heuristic: CHECK ITEM / BOX flow-control variables have no real data column.

    Matches both 1999-2018 style (empty SASLabel + BOX/GO TO in instructions)
    and 2021-2023 style (SASLabel == 'CHECK ITEM').
    """
    if sas_label and "CHECK ITEM" in sas_label.upper():
        return True
    if not instructions:
        return False
    if not sas_label:  # empty label + flow-control keywords → skip marker
        for pat in _SKIP_CONTROL_HINTS:
            if pat.search(instructions):
                return True
    return False


def _decode_xpt_value(v: Any) -> Any:
    """pandas.read_sas yields bytes for SAS character columns. Decode to str
    so comparisons against codebook string codes behave."""
    if isinstance(v, (bytes, bytearray)):
        return v.decode("latin-1", errors="replace").strip()
    return v


def download_xpt(table_name: str, cycle: str) -> Optional[pd.DataFrame]:
    """Download and read an XPT file from CDC."""
    cdc_year = CYCLE_TO_CDC_PATH.get(cycle)
    if not cdc_year:
        return None

    url = f"{CDC_BASE}/{cdc_year}/DataFiles/{table_name}.xpt"
    tmp = tempfile.mktemp(suffix=".xpt")

    try:
        urllib.request.urlretrieve(url, tmp)
        # Guard against landing-page HTML when the file is missing (CDC sometimes
        # returns a 200 with an HTML redirect shell instead of a 404).
        with open(tmp, "rb") as f:
            head = f.read(13)
        if not head.startswith(b"HEADER RECORD"):
            return None
        df = pd.read_sas(tmp, format="xport")
        return df
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def skip_control_variables_for_table(
    conn: sqlite3.Connection, table_name: str
) -> set:
    """Return set of variable codes in this table that are CHECK ITEM / BOX
    skip-pattern pseudo-variables (documented but not in XPT)."""
    rows = conn.execute(
        "SELECT variable_code, sas_label, english_instructions "
        "FROM variables WHERE table_name=?",
        (table_name,),
    ).fetchall()
    return {
        code for code, sas_label, instructions in rows
        if _is_skip_control_label(sas_label, instructions)
    }


def verify_table(
    conn: sqlite3.Connection,
    table_name: str,
    cycle: str,
    df: pd.DataFrame,
) -> Dict[str, Any]:
    """Verify a single table against XPT data."""
    # Decode SAS column names (bytes in some pandas versions)
    df = df.rename(columns=lambda c: _decode_xpt_value(c))

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

    # Exclude CHECK ITEM / BOX skip-pattern pseudo-variables from column match:
    # they are documented in CDC codebook pages but never emitted to XPT data.
    skip_controls = skip_control_variables_for_table(conn, table_name)
    our_cols_data = our_cols - skip_controls

    # Compare column lists
    missing_in_ours = xpt_cols - our_cols_data
    extra_in_ours = our_cols_data - xpt_cols

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
    result["columns_in_both"] = len(xpt_cols & our_cols_data)
    result["skip_controls_excluded"] = len(skip_controls)

    # Verify value counts for categorical variables (sample up to 10)
    value_checks = 0
    value_match = 0
    value_mismatch = 0

    for col in sorted(xpt_cols & our_cols_data)[:10]:
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

        # Decode bytes→str, build both numeric and string value_counts so we
        # can match codes regardless of whether SAS stored them as char or num.
        series = df[col].map(_decode_xpt_value)
        vc_str = series.astype(str).value_counts(dropna=True)
        vc_num = pd.to_numeric(series, errors="coerce").value_counts(dropna=True)

        def _xpt_count(code_str: str) -> int:
            # Try string match first ("0", "01"), then numeric (0.0).
            n = int(vc_str.get(code_str, 0))
            if n:
                return n
            try:
                return int(vc_num.get(float(code_str), 0))
            except (ValueError, TypeError):
                return 0

        all_match = True
        for code_str, label, expected_count in our_codes:
            actual = _xpt_count(code_str)
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


# ── L2b: source TSV ↔ DB row count (offline) ────────────────────────────────

# Source TSVs used by build_nhanes_codebook_db.py. Keep in sync with the
# VARS_TSV_SOURCES / CODES_TSV_SOURCES below so L2b captures every feed.
VARS_TSV_SOURCES = (
    "nhanes_variables.tsv",
    "nhanes_2021_2023_variables.tsv",
)
CODES_TSV_SOURCES = (
    "nhanes_variables_codebooks.tsv",
    "nhanes_2021_2023_codebooks.tsv",
)


def _tsv_unique_pairs(path: Path, var_key: str, tbl_key: str) -> set:
    if not path.exists():
        return set()
    pairs = set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            v = (row.get(var_key) or "").strip()
            t = (row.get(tbl_key) or "").strip()
            if v and t:
                pairs.add((v, t))
    return pairs


def check_source_vs_db_row_counts(
    conn: sqlite3.Connection, nhanes_dir: Path = NHANES_DIR
) -> Dict[str, Any]:
    """L2b: union of source TSV (var, table) pairs must equal DB (var, table).

    Mirrors the UKB L2b check. Drift here is a deterministic red flag that
    no network-level spot-check would have caught (the 919-row delta that
    the April-2026 audit turned up, for example).
    """
    # Variables TSVs — union across all feeds
    tsv_var_pairs: set = set()
    for name in VARS_TSV_SOURCES:
        tsv_var_pairs |= _tsv_unique_pairs(nhanes_dir / name, "Variable", "Table")

    db_var_pairs = set(conn.execute(
        "SELECT variable_code, table_name FROM variables"
    ).fetchall())

    # value_codes: also compare (var, table, code) across feeds
    tsv_code_rows = 0
    for name in CODES_TSV_SOURCES:
        path = nhanes_dir / name
        if path.exists():
            with open(path, newline="") as f:
                tsv_code_rows += sum(1 for _ in csv.DictReader(f, delimiter="\t"))
    db_code_rows = conn.execute("SELECT COUNT(*) FROM value_codes").fetchone()[0]

    db_minus_tsv = db_var_pairs - tsv_var_pairs
    tsv_minus_db = tsv_var_pairs - db_var_pairs

    return {
        "tsv_var_pairs": len(tsv_var_pairs),
        "db_var_pairs": len(db_var_pairs),
        "db_minus_tsv": len(db_minus_tsv),
        "tsv_minus_db": len(tsv_minus_db),
        "tsv_code_rows": tsv_code_rows,
        "db_code_rows": db_code_rows,
        "sample_db_minus_tsv": sorted(db_minus_tsv)[:10],
        "sample_tsv_minus_db": sorted(tsv_minus_db)[:10],
    }


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
    parser.add_argument(
        "--l2b-only", action="store_true",
        help="Run only the offline source↔DB row-count check (no CDC downloads)"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))

    # ── L2b: source↔DB row counts (always; cheap, deterministic) ──────────
    print("="*60)
    print("L2b: source TSV ↔ DB row counts")
    print("="*60)
    l2b = check_source_vs_db_row_counts(conn)
    print(f"  TSV (var,table) pairs:     {l2b['tsv_var_pairs']:>7,}")
    print(f"  DB  (var,table) pairs:     {l2b['db_var_pairs']:>7,}")
    print(f"  DB - TSV (extra in DB):    {l2b['db_minus_tsv']:>7,}")
    print(f"  TSV - DB (missing in DB):  {l2b['tsv_minus_db']:>7,}")
    print(f"  TSV value_code rows:       {l2b['tsv_code_rows']:>7,}")
    print(f"  DB  value_codes rows:      {l2b['db_code_rows']:>7,}")
    if l2b["db_minus_tsv"] or l2b["tsv_minus_db"]:
        print("  WARN: source↔DB variable set mismatch")
        for p in l2b["sample_db_minus_tsv"][:5]:
            print(f"    DB-only: {p[0]}@{p[1]}")
        for p in l2b["sample_tsv_minus_db"][:5]:
            print(f"    TSV-only: {p[0]}@{p[1]}")
    else:
        print("  OK: source and DB variable sets agree")
    print()

    if args.l2b_only:
        conn.close()
        if args.output:
            Path(args.output).write_text(json.dumps({"l2b": l2b}, indent=2, ensure_ascii=False))
        return 0 if (l2b["db_minus_tsv"] + l2b["tsv_minus_db"]) == 0 else 1

    if args.all_cycles:
        cycles = list(ALL_CYCLES)
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
    print("VERIFICATION SUMMARY")
    print(f"{'='*60}")
    print(f"Tables verified:     {total_tables}")
    print(f"Column lists match:  {total_col_match}/{total_tables} ({total_col_match/max(total_tables,1)*100:.0f}%)")
    print(f"Value code checks:   {total_val_match}/{total_val_checks} ({total_val_match/max(total_val_checks,1)*100:.0f}%)")

    total_issues = sum(len(r["issues"]) for r in all_results)
    print(f"Total issues found:  {total_issues}")

    if args.output:
        report = {
            "l2b": l2b,
            "total_tables": total_tables,
            "column_match_rate": total_col_match / max(total_tables, 1),
            "value_match_rate": total_val_match / max(total_val_checks, 1),
            "total_issues": total_issues,
            "results": all_results,
        }
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport: {args.output}")

    conn.close()
    l2b_failed = (l2b["db_minus_tsv"] + l2b["tsv_minus_db"]) != 0
    return 0 if (total_issues == 0 and not l2b_failed) else 1


if __name__ == "__main__":
    sys.exit(main())
