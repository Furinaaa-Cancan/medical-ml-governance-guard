#!/usr/bin/env python3
"""Build NHANES codebook SQLite database from Harvard CCB-HMS TSV files.

Reads:
  references/nhanes_codebook/nhanes_variables.tsv        (58K variables)
  references/nhanes_codebook/nhanes_variables_codebooks.tsv (202K codebook entries)
  references/dataset-codebook-registry.json               (curated annotations)

Produces:
  references/nhanes_codebook/nhanes_codebook.sqlite

Usage:
  python3 scripts/tools/build_nhanes_codebook_db.py
  python3 scripts/tools/build_nhanes_codebook_db.py --output /tmp/test.sqlite
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_VARS_TSV = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_variables.tsv"
DEFAULT_CODES_TSV = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_variables_codebooks.tsv"
DEFAULT_CURATED = REPO_ROOT / "references" / "dataset-codebook-registry.json"
DEFAULT_OUTPUT = REPO_ROOT / "references" / "nhanes_codebook" / "nhanes_codebook.sqlite"

# ── Cycle detection ──────────────────────────────────────────────────────────

SUFFIX_TO_CYCLE = {
    "A": "1999-2000",
    "B": "2001-2002", "C": "2003-2004", "D": "2005-2006",
    "E": "2007-2008", "F": "2009-2010", "G": "2011-2012",
    "H": "2013-2014", "I": "2015-2016", "J": "2017-2018",
}


def infer_cycle(table_name: str) -> str:
    """Infer NHANES cycle from table suffix."""
    if table_name.startswith("P_"):
        return "2019-2020"
    if "_" in table_name:
        suffix = table_name.rsplit("_", 1)[-1]
        return SUFFIX_TO_CYCLE.get(suffix, f"other_{suffix}")
    return "pre-1999"


# ── Domain inference ─────────────────────────────────────────────────────────

_TABLE_PREFIX_TO_DOMAIN = {
    "DEMO": "demographics", "DMQ": "demographics",
    "BMX": "anthropometry", "WHQ": "anthropometry",
    "BPX": "vitals", "BPXO": "vitals",
    "GHB": "laboratory", "GLU": "laboratory", "TCHOL": "laboratory",
    "HDL": "laboratory", "TRIGLY": "laboratory", "CBC": "laboratory",
    "BIOPRO": "laboratory", "FERTIN": "laboratory", "FOLATE": "laboratory",
    "LBX": "laboratory", "LBD": "laboratory", "UR": "laboratory",
    "SS": "laboratory", "SSANA": "laboratory",
    "DIQ": "questionnaire_diabetes", "BPQ": "questionnaire_blood_pressure",
    "SMQ": "questionnaire_smoking", "ALQ": "questionnaire_alcohol",
    "PAQ": "questionnaire_physical_activity", "MCQ": "questionnaire_medical_conditions",
    "HUQ": "questionnaire_hospital_utilization", "HIQ": "questionnaire_health_insurance",
    "OHQ": "questionnaire_oral_health", "DPQ": "questionnaire_depression",
    "SLQ": "questionnaire_sleep", "CDQ": "questionnaire_cardiovascular",
    "KIQ": "questionnaire_kidney", "RHQ": "questionnaire_reproductive",
    "DBQ": "questionnaire_diet", "FSQ": "questionnaire_food_security",
    "OCQ": "questionnaire_occupation", "DUQ": "questionnaire_drug_use",
    "HSQ": "questionnaire_health_status", "IMQ": "questionnaire_immunization",
    "AUQ": "questionnaire_audiometry", "VIQ": "questionnaire_vision",
    "AUX": "examination_audiometry", "DXX": "examination_dxa",
    "OHXDEN": "examination_dental", "OHXPER": "examination_periodontal",
    "DR": "dietary", "DSQTOT": "dietary_supplement",
    "RXQ": "prescription_medication", "RXQANA": "prescription_medication",
}


def infer_domain(table_name: str, variable_code: str) -> str:
    """Infer domain from table prefix or variable code prefix."""
    # Strip cycle suffix
    base = table_name.split("_")[0] if "_" in table_name else table_name
    if table_name.startswith("P_"):
        base = table_name[2:].split("_")[0] if "_" in table_name[2:] else table_name[2:]

    # Try longest prefix match
    for prefix_len in range(len(base), 0, -1):
        prefix = base[:prefix_len]
        if prefix in _TABLE_PREFIX_TO_DOMAIN:
            return _TABLE_PREFIX_TO_DOMAIN[prefix]

    # Variable code prefix fallback
    if variable_code.startswith("LBX") or variable_code.startswith("LBD"):
        return "laboratory"
    if variable_code.startswith("URX") or variable_code.startswith("URD"):
        return "laboratory"
    if variable_code.startswith("BPX") or variable_code.startswith("BPD"):
        return "vitals"
    if variable_code.startswith("BMX"):
        return "anthropometry"
    if variable_code.startswith("RID") or variable_code.startswith("DMD"):
        return "demographics"
    if variable_code.startswith("DR"):
        return "dietary"
    if variable_code.startswith("WT") or variable_code.startswith("SD"):
        return "survey_weight"
    if variable_code == "SEQN":
        return "identifier"

    return "other"


# ── Type inference from codebook ─────────────────────────────────────────────

_RANGE_RE = re.compile(r"^[\d.\-\s]+to[\d.\-\s]+$")
_MISSING_LABELS = {"Missing", ".", "Don't know", "Refused", "Don't Know"}


def infer_data_type(codes: List[Dict[str, str]]) -> str:
    """Infer data type from codebook entries."""
    non_missing = [c for c in codes if c["label"] not in _MISSING_LABELS and c["code"] != "."]
    if not non_missing:
        return "unknown"

    has_range = any(_RANGE_RE.match(c["code"]) for c in non_missing)
    if has_range:
        # Check if there are also coded values (mixed continuous + categorical)
        coded = [c for c in non_missing if not _RANGE_RE.match(c["code"])]
        if len(coded) <= 2:  # e.g., "0 = No Lab Result" alongside range
            return "continuous"
        return "mixed"

    # All discrete codes
    unique_codes = set(c["code"] for c in non_missing)
    if unique_codes <= {"0", "1"} or unique_codes <= {"1", "2"}:
        return "binary"
    try:
        vals = sorted(int(c["code"]) for c in non_missing)
        if len(vals) <= 10:
            return "ordinal_categorical"
    except (ValueError, TypeError):
        pass
    return "nominal_categorical"


# ── Missing rate computation ─────────────────────────────────────────────────

def compute_missing_rate(codes: List[Dict[str, str]]) -> Optional[float]:
    """Compute missing rate from codebook counts."""
    total = 0
    missing = 0
    for c in codes:
        count = c.get("count")
        if count is None:
            continue
        try:
            n = int(count)
        except (ValueError, TypeError):
            continue
        if c["label"] in _MISSING_LABELS or c["code"] == ".":
            missing += n
        total = max(total, int(c.get("cumulative", 0) or 0))

    if total <= 0:
        return None
    return round(missing / total, 4)


# ── Schema creation ──────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS variables (
    id TEXT PRIMARY KEY,
    variable_code TEXT NOT NULL,
    table_name TEXT NOT NULL,
    cycle TEXT,
    sas_label TEXT,
    english_text TEXT,
    english_instructions TEXT,
    target_population TEXT,
    data_type TEXT,
    domain TEXT,
    unit TEXT,
    missing_rate REAL,
    is_phenotype BOOLEAN,
    ontology_mapped BOOLEAN
);

CREATE TABLE IF NOT EXISTS value_codes (
    variable_id TEXT NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    count INTEGER,
    cumulative INTEGER,
    skip_to TEXT,
    is_missing BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (variable_id, code)
);

CREATE TABLE IF NOT EXISTS gating (
    downstream_var TEXT NOT NULL,
    upstream_var TEXT NOT NULL,
    upstream_table TEXT,
    condition TEXT,
    skip_target TEXT,
    PRIMARY KEY (downstream_var, upstream_var)
);

CREATE TABLE IF NOT EXISTS aliases (
    alias TEXT NOT NULL,
    variable_code TEXT NOT NULL,
    PRIMARY KEY (alias, variable_code)
);

CREATE INDEX IF NOT EXISTS idx_variables_code ON variables(variable_code);
CREATE INDEX IF NOT EXISTS idx_variables_cycle ON variables(cycle);
CREATE INDEX IF NOT EXISTS idx_variables_domain ON variables(domain);
CREATE INDEX IF NOT EXISTS idx_value_codes_var ON value_codes(variable_id);
CREATE INDEX IF NOT EXISTS idx_gating_downstream ON gating(downstream_var);
CREATE INDEX IF NOT EXISTS idx_gating_upstream ON gating(upstream_var);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS variables_fts USING fts5(
    variable_code, sas_label, english_text, domain, table_name,
    content='variables', content_rowid='rowid'
);

INSERT INTO variables_fts(variables_fts) VALUES('rebuild');
"""

# ── Common aliases ───────────────────────────────────────────────────────────

COMMON_ALIASES = {
    "hba1c": "LBXGH", "a1c": "LBXGH", "glycohemoglobin": "LBXGH",
    "glycated_hemoglobin": "LBXGH", "hemoglobin_a1c": "LBXGH",
    "fasting_glucose": "LBXGLU", "glucose": "LBXGLU", "fbg": "LBXGLU",
    "bmi": "BMXBMI", "body_mass_index": "BMXBMI",
    "waist": "BMXWAIST", "waist_circumference": "BMXWAIST",
    "systolic": "BPXOSY1", "sbp": "BPXOSY1",
    "diastolic": "BPXODI1", "dbp": "BPXODI1",
    "age": "RIDAGEYR", "gender": "RIAGENDR", "sex": "RIAGENDR",
    "race": "RIDRETH3", "ethnicity": "RIDRETH3", "race_ethnicity": "RIDRETH3",
    "cholesterol": "LBXTC", "total_cholesterol": "LBXTC",
    "hdl": "LBDHDD", "hdl_cholesterol": "LBDHDD",
    "triglycerides": "LBXTR",
    "smoking": "SMQ020", "ever_smoked": "SMQ020",
    "alcohol": "ALQ130", "drinks": "ALQ130",
    "diabetes": "DIQ010", "doctor_told_diabetes": "DIQ010",
    "hypertension": "BPQ020", "high_blood_pressure": "BPQ020",
    "bp_medication": "BPQ050A",
    "family_history_diabetes": "MCQ300C",
    "coronary_heart_disease": "MCQ160C", "chd": "MCQ160C",
    "stroke": "MCQ160F",
    "depression": "DPQ010",
    "weight": "BMXWT", "height": "BMXHT",
}


# ── Main build ───────────────────────────────────────────────────────────────

def build_database(
    vars_tsv: Path,
    codes_tsv: Path,
    curated_path: Optional[Path],
    output: Path,
) -> Dict[str, int]:
    """Build SQLite from TSV sources."""
    print(f"Reading variables from {vars_tsv}...")
    print(f"Reading codebooks from {codes_tsv}...")

    # Remove existing database
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA_SQL)

    # ── Step 1: Load variables ────────────────────────────────────────────
    var_count = 0
    with open(vars_tsv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        batch = []
        for row in reader:
            var_code = row.get("Variable", "").strip()
            table = row.get("Table", "").strip()
            if not var_code or not table:
                continue

            vid = f"{var_code}@{table}"
            cycle = infer_cycle(table)
            domain = infer_domain(table, var_code)

            batch.append((
                vid, var_code, table, cycle,
                row.get("SASLabel", "").strip() or None,
                row.get("EnglishText", "").strip() or None,
                row.get("EnglishInstructions", "").strip() or None,
                row.get("Target", "").strip() or None,
                None,  # data_type — filled after codebook pass
                domain,
                None,  # unit
                None,  # missing_rate
                row.get("IsPhenotype", "").strip().upper() == "TRUE",
                row.get("OntologyMapped", "").strip().upper() == "TRUE",
            ))
            var_count += 1

            if len(batch) >= 5000:
                conn.executemany(
                    "INSERT OR IGNORE INTO variables VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()

        if batch:
            conn.executemany(
                "INSERT OR IGNORE INTO variables VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
    conn.commit()
    print(f"  Loaded {var_count} variables")

    # ── Step 2: Load codebook entries ─────────────────────────────────────
    code_count = 0
    # Group codes by variable@table for type inference and missing rate
    var_codes: Dict[str, List[Dict[str, str]]] = {}

    with open(codes_tsv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        batch = []
        for row in reader:
            var_code = row.get("Variable", "").strip().strip('"')
            table = row.get("Table", "").strip().strip('"')
            code_val = row.get("CodeOrValue", "").strip().strip('"')
            label = row.get("ValueDescription", "").strip().strip('"')
            count_str = row.get("Count", "").strip().strip('"')
            cumul_str = row.get("Cumulative", "").strip().strip('"')
            skip_to = row.get("SkipToItem", "").strip().strip('"') or None

            if not var_code or not table:
                continue

            vid = f"{var_code}@{table}"
            is_missing = label in _MISSING_LABELS or code_val == "."

            try:
                count_int = int(count_str) if count_str else None
            except ValueError:
                count_int = None
            try:
                cumul_int = int(cumul_str) if cumul_str else None
            except ValueError:
                cumul_int = None

            batch.append((vid, code_val, label, count_int, cumul_int, skip_to, is_missing))
            code_count += 1

            # Collect for type inference
            var_codes.setdefault(vid, []).append({
                "code": code_val, "label": label,
                "count": count_str, "cumulative": cumul_str,
            })

            if len(batch) >= 10000:
                conn.executemany(
                    "INSERT OR IGNORE INTO value_codes VALUES (?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()

        if batch:
            conn.executemany(
                "INSERT OR IGNORE INTO value_codes VALUES (?,?,?,?,?,?,?)",
                batch,
            )
    conn.commit()
    print(f"  Loaded {code_count} codebook entries")

    # ── Step 3: Infer data types and missing rates ────────────────────────
    print("  Inferring data types and missing rates...")
    updates = []
    for vid, codes in var_codes.items():
        dt = infer_data_type(codes)
        mr = compute_missing_rate(codes)
        updates.append((dt, mr, vid))

    conn.executemany("UPDATE variables SET data_type=?, missing_rate=? WHERE id=?", updates)
    conn.commit()
    print(f"  Updated {len(updates)} variables with type/missing info")

    # ── Step 4: Build gating table from skip patterns ─────────────────────
    print("  Building skip-chain gating graph...")
    gating_count = 0

    # Group variables by table, ordered by their appearance
    table_vars: Dict[str, List[Tuple[str, str]]] = {}  # table -> [(var_code, vid), ...]
    cur = conn.execute("SELECT id, variable_code, table_name FROM variables ORDER BY rowid")
    for vid, vc, tbl in cur:
        table_vars.setdefault(tbl, []).append((vc, vid))

    # Find skip patterns: if var X skips to var Y, then vars between X and Y are gated by X
    skip_entries = conn.execute(
        "SELECT variable_id, code, skip_to FROM value_codes WHERE skip_to IS NOT NULL AND skip_to != ''"
    ).fetchall()

    skip_by_table: Dict[str, List[Tuple[str, str, str]]] = {}
    for vid, code, skip_to in skip_entries:
        table = vid.split("@")[1] if "@" in vid else ""
        var_code = vid.split("@")[0] if "@" in vid else vid
        skip_by_table.setdefault(table, []).append((var_code, code, skip_to))

    gating_batch = []
    for table, skips in skip_by_table.items():
        tbl_vars = table_vars.get(table, [])
        var_order = {vc: idx for idx, (vc, _) in enumerate(tbl_vars)}

        for gating_var, code_val, skip_target in skips:
            gating_idx = var_order.get(gating_var)
            target_idx = var_order.get(skip_target)
            if gating_idx is None or target_idx is None:
                continue
            # All variables between gating_var and skip_target are gated
            for idx in range(gating_idx + 1, target_idx):
                if idx < len(tbl_vars):
                    downstream_vc, downstream_vid = tbl_vars[idx]
                    gating_batch.append((
                        downstream_vid,
                        f"{gating_var}@{table}",
                        table,
                        f"{gating_var}={code_val}",
                        skip_target,
                    ))
                    gating_count += 1

    if gating_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO gating VALUES (?,?,?,?,?)",
            gating_batch,
        )
    conn.commit()
    print(f"  Built {gating_count} gating relationships")

    # ── Step 5: Insert aliases ────────────────────────────────────────────
    alias_batch = [(alias, code) for alias, code in COMMON_ALIASES.items()]
    conn.executemany("INSERT OR IGNORE INTO aliases VALUES (?,?)", alias_batch)
    conn.commit()
    print(f"  Inserted {len(alias_batch)} aliases")

    # ── Step 6: Build FTS5 index ──────────────────────────────────────────
    print("  Building FTS5 full-text search index...")
    conn.executescript(FTS_SQL)
    conn.commit()

    # ── Step 7: Merge curated annotations ─────────────────────────────────
    if curated_path and curated_path.exists():
        print(f"  Merging curated annotations from {curated_path}...")
        curated = json.loads(curated_path.read_text(encoding="utf-8"))
        nhanes_vars = curated.get("nhanes", curated.get("variables", {}))
        if isinstance(nhanes_vars, dict):
            anno_count = 0
            for var_code, anno in nhanes_vars.items():
                if not isinstance(anno, dict):
                    continue
                # Update all rows matching this variable code
                unit = anno.get("unit")
                if unit:
                    conn.execute(
                        "UPDATE variables SET unit=? WHERE variable_code=?",
                        (unit, var_code),
                    )
                    anno_count += 1
            conn.commit()
            print(f"  Applied {anno_count} curated annotations")

    # ── Stats ─────────────────────────────────────────────────────────────
    stats = {}
    stats["variables"] = conn.execute("SELECT COUNT(*) FROM variables").fetchone()[0]
    stats["value_codes"] = conn.execute("SELECT COUNT(*) FROM value_codes").fetchone()[0]
    stats["gating"] = conn.execute("SELECT COUNT(*) FROM gating").fetchone()[0]
    stats["aliases"] = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    stats["cycles"] = conn.execute("SELECT COUNT(DISTINCT cycle) FROM variables").fetchone()[0]
    stats["tables"] = conn.execute("SELECT COUNT(DISTINCT table_name) FROM variables").fetchone()[0]

    # File size
    conn.close()
    size_mb = output.stat().st_size / (1024 * 1024)
    stats["file_size_mb"] = round(size_mb, 1)

    print(f"\n{'='*50}")
    print(f"NHANES Codebook SQLite built successfully!")
    print(f"{'='*50}")
    print(f"  Variables:    {stats['variables']:,}")
    print(f"  Value codes:  {stats['value_codes']:,}")
    print(f"  Gating:       {stats['gating']:,}")
    print(f"  Aliases:      {stats['aliases']:,}")
    print(f"  Cycles:       {stats['cycles']}")
    print(f"  Tables:       {stats['tables']:,}")
    print(f"  File size:    {stats['file_size_mb']} MB")
    print(f"  Output:       {output}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NHANES codebook SQLite database")
    parser.add_argument("--vars-tsv", type=Path, default=DEFAULT_VARS_TSV)
    parser.add_argument("--codes-tsv", type=Path, default=DEFAULT_CODES_TSV)
    parser.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.vars_tsv.exists():
        print(f"ERROR: Variables TSV not found: {args.vars_tsv}", file=sys.stderr)
        return 2
    if not args.codes_tsv.exists():
        print(f"ERROR: Codebooks TSV not found: {args.codes_tsv}", file=sys.stderr)
        return 2

    build_database(args.vars_tsv, args.codes_tsv, args.curated, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
