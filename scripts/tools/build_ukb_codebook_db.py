#!/usr/bin/env python3
"""Build UK Biobank codebook SQLite database from Data Showcase schema files.

Reads:
  references/ukb_codebook/field.txt          (field definitions)
  references/ukb_codebook/encoding.txt       (encoding metadata)
  references/ukb_codebook/category.txt       (category definitions)
  references/ukb_codebook/esimpint.txt       (integer encoding values)
  references/ukb_codebook/esimpstring.txt    (string encoding values)
  references/ukb_codebook/esimpreal.txt      (real encoding values)
  references/ukb_codebook/esimpdate.txt      (date encoding values)
  references/ukb_codebook/ehierint.txt       (hierarchical int encoding values)
  references/ukb_codebook/ehierstring.txt    (hierarchical string encoding values)
  references/ukb_codebook/catbrowse.txt      (category browse tree)
  references/ukb_codebook/insvalue.txt       (instance definitions)

Produces:
  references/ukb_codebook/ukb_codebook.sqlite

Usage:
  python3 scripts/tools/build_ukb_codebook_db.py
  python3 scripts/tools/build_ukb_codebook_db.py --output /tmp/ukb_test.sqlite
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DIR = REPO_ROOT / "references" / "ukb_codebook"
DEFAULT_OUTPUT = DEFAULT_DIR / "ukb_codebook.sqlite"

# ── UKB value type mapping ──────────────────────────────────────────────────

VALUE_TYPE_MAP = {
    "11": "integer",
    "21": "categorical_single",
    "22": "categorical_multiple",
    "31": "continuous",
    "41": "text",
    "51": "date",
    "61": "time",
    "101": "compound",
}

# ── UKB instance semantics ──────────────────────────────────────────────────
# Instance 0 = initial assessment (2006-2010)
# Instance 1 = first repeat assessment (2012-2013)
# Instance 2 = imaging visit (2014+)
# Instance 3 = first repeat imaging (2019+)

INSTANCE_TEMPORAL_ORDER = {
    "0": {"label": "Initial assessment visit", "year_range": "2006-2010", "order": 0},
    "1": {"label": "First repeat assessment", "year_range": "2012-2013", "order": 1},
    "2": {"label": "Imaging visit", "year_range": "2014-ongoing", "order": 2},
    "3": {"label": "First repeat imaging visit", "year_range": "2019-ongoing", "order": 3},
}

# ── Category → domain mapping (top-level UKB categories) ────────────────────

_CATEGORY_DOMAIN_KEYWORDS = {
    "demographics": ["population", "sociodem", "household", "ethnic", "employment"],
    "anthropometry": ["body", "anthropo", "impedance"],
    "vitals": ["blood pressure", "arterial", "pulse", "ecg", "cardio"],
    "laboratory": ["blood", "urine", "assay", "biochem", "haematol", "infect"],
    "imaging": ["brain", "mri", "imaging", "dxa", "ultrasound", "retinal", "oct"],
    "questionnaire_mental_health": ["mental", "psychiatr", "depression", "anxiety"],
    "questionnaire_lifestyle": ["diet", "alcohol", "smoking", "physical activity",
                                  "sleep", "sun exposure", "sexual"],
    "questionnaire_medical": ["medical", "cancer", "medication", "operation",
                               "pain", "breathing", "digest", "general health"],
    "questionnaire_cognitive": ["cognitive", "prospective memory", "reaction time",
                                 "fluid intelligence", "trail making", "pairs"],
    "questionnaire_family": ["family history", "early life", "maternal"],
    "genomics": ["genomic", "genetic", "snp", "telomer", "whole exome"],
    "hospital_records": ["hospital", "death", "icd", "opcs", "hes", "gp"],
    "summary": ["first occurrence", "summary"],
    "recruitment": ["recruitment", "assessment centre", "baseline"],
}


def infer_domain_from_category_path(path: str) -> str:
    """Infer domain from the full category path string."""
    path_lower = path.lower()
    for domain, keywords in _CATEGORY_DOMAIN_KEYWORDS.items():
        if any(kw in path_lower for kw in keywords):
            return domain
    return "other"


# ── Schema creation ─────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fields (
    field_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    availability INTEGER,
    stability INTEGER,
    private INTEGER,
    value_type TEXT,
    base_type TEXT,
    item_type TEXT,
    strata INTEGER,
    instanced INTEGER,
    arrayed INTEGER,
    sexed INTEGER,
    units TEXT,
    main_category INTEGER,
    encoding_id INTEGER,
    instance_id INTEGER,
    instance_min INTEGER,
    instance_max INTEGER,
    array_min INTEGER,
    array_max INTEGER,
    notes TEXT,
    debut TEXT,
    version TEXT,
    num_participants INTEGER,
    item_count INTEGER,
    showcase_order REAL,
    domain TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY,
    parent_id INTEGER,
    title TEXT NOT NULL,
    full_path TEXT
);

CREATE TABLE IF NOT EXISTS encodings (
    encoding_id INTEGER PRIMARY KEY,
    title TEXT,
    coded_as TEXT
);

CREATE TABLE IF NOT EXISTS encoding_values (
    encoding_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    meaning TEXT NOT NULL,
    selectable INTEGER DEFAULT 1,
    parent_code TEXT,
    PRIMARY KEY (encoding_id, code)
);

CREATE TABLE IF NOT EXISTS instances (
    instance_id INTEGER PRIMARY KEY,
    title TEXT,
    description TEXT,
    temporal_order INTEGER
);

CREATE TABLE IF NOT EXISTS aliases (
    alias TEXT NOT NULL,
    field_id INTEGER NOT NULL,
    PRIMARY KEY (alias, field_id)
);

CREATE INDEX IF NOT EXISTS idx_fields_category ON fields(main_category);
CREATE INDEX IF NOT EXISTS idx_fields_encoding ON fields(encoding_id);
CREATE INDEX IF NOT EXISTS idx_fields_domain ON fields(domain);
CREATE INDEX IF NOT EXISTS idx_fields_value_type ON fields(value_type);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_encoding_values_enc ON encoding_values(encoding_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS fields_fts USING fts5(
    title, units, domain, notes,
    content='fields', content_rowid='field_id'
);

INSERT INTO fields_fts(fields_fts) VALUES('rebuild');
"""

# ── Common aliases for medical research ─────────────────────────────────────

COMMON_ALIASES = {
    # Demographics
    "age": 21003, "sex": 31, "gender": 31,
    "ethnicity": 21000, "race": 21000, "ethnic_group": 21000,
    "bmi": 21001, "body_mass_index": 21001,
    "weight": 21002, "height": 50,
    "waist": 48, "waist_circumference": 48,
    "hip": 49, "hip_circumference": 49,
    "townsend": 189, "deprivation": 189,
    # Blood pressure
    "systolic": 4080, "sbp": 4080, "systolic_bp": 4080,
    "diastolic": 4079, "dbp": 4079, "diastolic_bp": 4079,
    # Blood biomarkers
    "hba1c": 30750, "glycated_haemoglobin": 30750, "a1c": 30750,
    "glucose": 30740, "fasting_glucose": 30740,
    "cholesterol": 30690, "total_cholesterol": 30690,
    "hdl": 30760, "hdl_cholesterol": 30760,
    "ldl": 30780, "ldl_cholesterol": 30780,
    "triglycerides": 30870,
    "creatinine": 30700, "serum_creatinine": 30700,
    "albumin": 30600, "serum_albumin": 30600,
    "alt": 30620, "alanine_aminotransferase": 30620,
    "ast": 30650, "aspartate_aminotransferase": 30650,
    "crp": 30710, "c_reactive_protein": 30710,
    "haemoglobin": 30020,
    # Lifestyle
    "smoking": 20116, "smoking_status": 20116,
    "alcohol": 20117, "alcohol_status": 20117,
    "physical_activity": 22032, "ipaq": 22032,
    # Conditions (first occurrence fields)
    "diabetes": 130706, "type2_diabetes": 130708,
    "hypertension": 131286,
    "stroke": 131366, "ischaemic_stroke": 131368,
    "heart_failure": 131354,
    "myocardial_infarction": 131298, "mi": 131298,
    "atrial_fibrillation": 131350, "af": 131350,
    "copd": 131484,
    "dementia": 130836, "alzheimers": 130838,
    "depression": 130894,
    # Death
    "date_of_death": 40000, "cause_of_death": 40001,
}


# ── File parsers ────────────────────────────────────────────────────────────

def read_tab_file(path: Path) -> List[Dict[str, str]]:
    """Read a UKB schema tab-separated file."""
    if not path.exists():
        print(f"  [SKIP] {path.name} not found", file=sys.stderr)
        return []
    csv.field_size_limit(10 * 1024 * 1024)  # 10 MB — UKB hierarchical encodings can be large
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def safe_int(v: str) -> Optional[int]:
    if not v or not v.strip():
        return None
    try:
        return int(v.strip())
    except ValueError:
        return None


def safe_float(v: str) -> Optional[float]:
    if not v or not v.strip():
        return None
    try:
        import math
        f = float(v.strip())
        return f if math.isfinite(f) else None
    except ValueError:
        return None


# ── Main build ──────────────────────────────────────────────────────────────

def build_database(input_dir: Path, output: Path) -> Dict[str, int]:
    """Build SQLite from UKB Data Showcase schema files."""
    print(f"Building UKB codebook from {input_dir}")

    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA_SQL)

    # ── Step 1: Load categories & build path tree ────────────────────────
    print("  Loading categories...")
    cat_rows = read_tab_file(input_dir / "category.txt")
    cat_titles: Dict[int, str] = {}
    cat_parents: Dict[int, Optional[int]] = {}

    for row in cat_rows:
        cid = safe_int(row.get("category_id", ""))
        pid = safe_int(row.get("parent_id", ""))
        title = row.get("title", "").strip()
        if cid is not None:
            cat_titles[cid] = title
            cat_parents[cid] = pid

    # Build full paths
    def get_cat_path(cid: int, visited: Optional[Set[int]] = None) -> str:
        if visited is None:
            visited = set()
        if cid in visited:
            return cat_titles.get(cid, "")
        visited.add(cid)
        parent = cat_parents.get(cid)
        title = cat_titles.get(cid, "")
        if parent and parent in cat_titles:
            return get_cat_path(parent, visited) + " > " + title
        return title

    cat_paths: Dict[int, str] = {cid: get_cat_path(cid) for cid in cat_titles}

    # Also load catbrowse for supplementary parent-child relations
    browse_rows = read_tab_file(input_dir / "catbrowse.txt")
    for row in browse_rows:
        cid = safe_int(row.get("child_id", ""))
        pid = safe_int(row.get("parent_id", ""))
        if cid is not None and cid not in cat_parents:
            cat_parents[cid] = pid

    cat_batch = [
        (cid, cat_parents.get(cid), cat_titles.get(cid, ""), cat_paths.get(cid, ""))
        for cid in cat_titles
    ]
    conn.executemany("INSERT OR IGNORE INTO categories VALUES (?,?,?,?)", cat_batch)
    conn.commit()
    print(f"    {len(cat_batch)} categories loaded")

    # ── Step 2: Load encodings ───────────────────────────────────────────
    print("  Loading encodings...")
    enc_rows = read_tab_file(input_dir / "encoding.txt")
    enc_batch = []
    for row in enc_rows:
        eid = safe_int(row.get("encoding_id", ""))
        if eid is not None:
            enc_batch.append((
                eid,
                row.get("title", "").strip(),
                row.get("coded_as", "").strip() or None,
            ))
    conn.executemany("INSERT OR IGNORE INTO encodings VALUES (?,?,?)", enc_batch)
    conn.commit()
    print(f"    {len(enc_batch)} encodings loaded")

    # ── Step 3: Load encoding values (simple + hierarchical) ─────────────
    print("  Loading encoding values...")
    ev_count = 0
    ev_batch = []

    # Simple encoding values (integer, string, real, date)
    for fname in ("esimpint.txt", "esimpstring.txt", "esimpreal.txt", "esimpdate.txt"):
        rows = read_tab_file(input_dir / fname)
        for row in rows:
            eid = safe_int(row.get("encoding_id", ""))
            code = row.get("value", "").strip()
            meaning = row.get("meaning", "").strip()
            if eid is not None and code:
                ev_batch.append((eid, code, meaning, 1, None))
                ev_count += 1
                if len(ev_batch) >= 10000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?)",
                        ev_batch,
                    )
                    ev_batch.clear()

    # Hierarchical encoding values (ICD-10, OPCS-4, etc.)
    for fname in ("ehierint.txt", "ehierstring.txt"):
        rows = read_tab_file(input_dir / fname)
        for row in rows:
            eid = safe_int(row.get("encoding_id", ""))
            code = row.get("coding", row.get("value", "")).strip()
            meaning = row.get("meaning", "").strip()
            parent = row.get("parent_id", row.get("parent", "")).strip() or None
            selectable = 1 if row.get("selectable", "Y").strip().upper() != "N" else 0
            if eid is not None and code:
                ev_batch.append((eid, code, meaning, selectable, parent))
                ev_count += 1
                if len(ev_batch) >= 10000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?)",
                        ev_batch,
                    )
                    ev_batch.clear()

    if ev_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?)",
            ev_batch,
        )
    conn.commit()
    print(f"    {ev_count} encoding values loaded")

    # ── Step 4: Load fields ──────────────────────────────────────────────
    print("  Loading fields...")
    field_rows = read_tab_file(input_dir / "field.txt")
    field_count = 0
    field_batch = []

    for row in field_rows:
        fid = safe_int(row.get("field_id", ""))
        if fid is None:
            continue

        main_cat = safe_int(row.get("main_category", ""))
        vtype_code = row.get("value_type", "").strip()
        value_type = VALUE_TYPE_MAP.get(vtype_code, vtype_code)

        # Infer domain from category path
        domain = "other"
        if main_cat and main_cat in cat_paths:
            domain = infer_domain_from_category_path(cat_paths[main_cat])

        field_batch.append((
            fid,
            row.get("title", "").strip(),
            safe_int(row.get("availability", "")),
            safe_int(row.get("stability", "")),
            safe_int(row.get("private", "")),
            value_type,
            row.get("base_type", "").strip() or None,
            row.get("item_type", "").strip() or None,
            safe_int(row.get("strata", "")),
            safe_int(row.get("instanced", "")),
            safe_int(row.get("arrayed", "")),
            safe_int(row.get("sexed", "")),
            row.get("units", "").strip() or None,
            main_cat,
            safe_int(row.get("encoding_id", "")),
            safe_int(row.get("instance_id", "")),
            safe_int(row.get("instance_min", "")),
            safe_int(row.get("instance_max", "")),
            safe_int(row.get("array_min", "")),
            safe_int(row.get("array_max", "")),
            row.get("notes", "").strip() or None,
            row.get("debut", "").strip() or None,
            row.get("version", "").strip() or None,
            safe_int(row.get("num_participants", "")),
            safe_int(row.get("item_count", "")),
            safe_float(row.get("showcase_order", "")),
            domain,
        ))
        field_count += 1

        if len(field_batch) >= 5000:
            conn.executemany(
                "INSERT OR IGNORE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                field_batch,
            )
            field_batch.clear()

    if field_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            field_batch,
        )
    conn.commit()
    print(f"    {field_count} fields loaded")

    # ── Step 5: Load instances ───────────────────────────────────────────
    print("  Loading instances...")
    ins_rows = read_tab_file(input_dir / "insvalue.txt")
    ins_batch = []
    for row in ins_rows:
        iid = safe_int(row.get("instance_id", ""))
        if iid is not None:
            temporal = INSTANCE_TEMPORAL_ORDER.get(str(iid), {})
            ins_batch.append((
                iid,
                row.get("title", "").strip() or temporal.get("label"),
                row.get("description", "").strip() or None,
                temporal.get("order"),
            ))

    # Also insert well-known instances if not already present
    for inst_str, meta in INSTANCE_TEMPORAL_ORDER.items():
        iid = int(inst_str)
        if not any(r[0] == iid for r in ins_batch):
            ins_batch.append((iid, meta["label"], meta["year_range"], meta["order"]))

    conn.executemany("INSERT OR IGNORE INTO instances VALUES (?,?,?,?)", ins_batch)
    conn.commit()
    print(f"    {len(ins_batch)} instances loaded")

    # ── Step 6: Insert aliases ───────────────────────────────────────────
    alias_batch = [(alias, fid) for alias, fid in COMMON_ALIASES.items()]
    conn.executemany("INSERT OR IGNORE INTO aliases VALUES (?,?)", alias_batch)
    conn.commit()
    print(f"    {len(alias_batch)} aliases loaded")

    # ── Step 7: Build FTS5 index ─────────────────────────────────────────
    print("  Building FTS5 full-text search index...")
    conn.executescript(FTS_SQL)
    conn.commit()

    # ── Stats ─────────────────────────────────────────────────────────────
    stats = {}
    stats["fields"] = conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
    stats["categories"] = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    stats["encodings"] = conn.execute("SELECT COUNT(*) FROM encodings").fetchone()[0]
    stats["encoding_values"] = conn.execute("SELECT COUNT(*) FROM encoding_values").fetchone()[0]
    stats["instances"] = conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
    stats["aliases"] = conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
    stats["domains"] = conn.execute("SELECT COUNT(DISTINCT domain) FROM fields").fetchone()[0]

    conn.close()
    size_mb = output.stat().st_size / (1024 * 1024)
    stats["file_size_mb"] = round(size_mb, 1)

    print(f"\n{'='*50}")
    print(f"UK Biobank Codebook SQLite built successfully!")
    print(f"{'='*50}")
    print(f"  Fields:           {stats['fields']:,}")
    print(f"  Categories:       {stats['categories']:,}")
    print(f"  Encodings:        {stats['encodings']:,}")
    print(f"  Encoding values:  {stats['encoding_values']:,}")
    print(f"  Instances:        {stats['instances']}")
    print(f"  Aliases:          {stats['aliases']}")
    print(f"  Domains:          {stats['domains']}")
    print(f"  File size:        {stats['file_size_mb']} MB")
    print(f"  Output:           {output}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Build UKB codebook SQLite database")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_DIR,
                        help="Directory containing UKB schema files")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output SQLite path")
    args = parser.parse_args()

    required = ["field.txt", "encoding.txt"]
    for fname in required:
        if not (args.input_dir / fname).exists():
            print(f"ERROR: Required file not found: {args.input_dir / fname}", file=sys.stderr)
            print(f"Run fetch_ukb_showcase.py first to download schema files.", file=sys.stderr)
            return 2

    build_database(args.input_dir, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
