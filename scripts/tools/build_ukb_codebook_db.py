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

# ── Category-based domain + risk mapping ─────────────────────────────────────
# Uses UKB category_id ranges for precise classification instead of keyword guessing.

def _cat_in(cid: Optional[int], *ranges) -> bool:
    """Check if category_id falls in any of the given ranges/sets."""
    if cid is None:
        return False
    for r in ranges:
        if isinstance(r, int) and cid == r:
            return True
        if isinstance(r, tuple) and r[0] <= cid <= r[1]:
            return True
        if isinstance(r, (set, frozenset)) and cid in r:
            return True
    return False


def classify_field(cid: Optional[int], title: str) -> Tuple[str, str]:
    """Return (domain, risk_category) for a UKB field.

    Domain: broad data category (e.g., 'imaging_brain', 'laboratory', 'questionnaire_lifestyle').
    Risk category:
      - 'outcome_derived'  : first-occurrence ICD dates/sources, algorithmically-defined outcomes
      - 'death_registry'   : death register fields
      - 'hospital_derived' : hospital inpatient / GP record fields
      - 'imaging'          : imaging-visit fields (inherently from later instances)
      - 'genomics'         : time-invariant genetic data
      - 'online_followup'  : post-baseline online questionnaires
      - 'baseline'         : safe baseline measurements (default)
    """
    title_lower = title.lower()

    # ── Outcome / registry derived (CRITICAL leakage risk) ───────────
    # First occurrences (ICD code date/source fields)
    if cid == 1712 or _cat_in(cid, (2401, 2417)):
        return "first_occurrence_icd", "outcome_derived"
    # Algorithmically-defined outcomes (stroke, MI, asthma, COPD, dementia, ESRD, MND, PD)
    if _cat_in(cid, (42, 50), 91):
        return "algorithmically_defined_outcome", "outcome_derived"
    # Death register
    if cid == 100093 or "death" in title_lower:
        return "death_registry", "death_registry"
    # Hospital inpatient records
    if _cat_in(cid, (2000, 2006)):
        return "hospital_inpatient", "hospital_derived"
    # Primary care / GP records
    if _cat_in(cid, (3000, 3001)):
        return "primary_care", "hospital_derived"
    # Cancer register
    if cid == 100092:
        return "cancer_registry", "outcome_derived"
    # Health outcomes (externally sourced)
    if cid == 100091:
        return "health_outcomes_external", "outcome_derived"

    # ── Imaging (temporal risk — later instances) ────────────────────
    _BRAIN_MRI = {100, 110, 111, 112, 119, 190, 191, 192, 193, 194, 195, 196,
                  197, 198, 200, 201, 202, 203, 204, 507, 508, 509,
                  530, 531, 532, 533, 534, 535, 536, 537, 539}
    _HEART_MRI = {102, 133, 157, 162, 306, 347, 348, 349,
                  523, 524, 525, 526, 527, 528, 529, 538}
    _DXA = {103, 124, 125, 522}
    _ABDOMINAL = {105, 126, 131, 149, 156, 158, 159}
    _EYE = {521, 1080, 1081, 1306, 1419, 100016, 100017}
    if _cat_in(cid, *_BRAIN_MRI):
        return "imaging_brain", "imaging"
    if _cat_in(cid, *_HEART_MRI):
        return "imaging_cardiac", "imaging"
    if _cat_in(cid, *_DXA):
        return "imaging_dxa", "imaging"
    if _cat_in(cid, *_ABDOMINAL):
        return "imaging_abdominal", "imaging"
    if cid == 101:
        return "imaging_carotid", "imaging"
    if _cat_in(cid, *_EYE):
        return "imaging_eye", "imaging"
    if cid == 100003:
        return "imaging_procedural", "imaging"
    # dMRI
    if _cat_in(cid, 134, 135):
        return "imaging_dmri", "imaging"
    # Regional grey matter, fMRI
    if _cat_in(cid, 1101, 1102, 106, 109):
        return "imaging_brain", "imaging"

    # ── Genomics (time-invariant) ────────────────────────────────────
    if _cat_in(cid, (170, 187), (263, 274), (300, 302), 100314, 100315,
               100316, 100317, 100319, 199001):
        return "genomics", "genomics"

    # ── Laboratory ───────────────────────────────────────────────────
    if _cat_in(cid, 17518, 18518):
        return "laboratory_biochemistry", "baseline"
    if _cat_in(cid, 81, 9081, 100081):
        return "laboratory_haematology", "baseline"
    if cid == 100080:
        return "laboratory_blood_assays", "baseline"
    if _cat_in(cid, 100082, 100083):
        return "laboratory_urine_saliva", "baseline"
    if _cat_in(cid, (220, 222)):
        return "laboratory_nmr_metabolomics", "baseline"
    if _cat_in(cid, (1838, 1839)):
        return "laboratory_proteomics", "baseline"
    if _cat_in(cid, 51428, 1307):
        return "laboratory_infectious", "baseline"
    if cid == 163:
        return "laboratory_neurobiomarkers", "baseline"

    # ── Anthropometry / vitals ───────────────────────────────────────
    if _cat_in(cid, 100008, 100009, 100010):
        return "anthropometry", "baseline"
    if _cat_in(cid, 100007, 100011, 128):
        return "vitals", "baseline"
    if _cat_in(cid, 100018, 100019):
        return "physical_measures", "baseline"
    if cid == 100020:
        return "spirometry", "baseline"
    if _cat_in(cid, 104, 100012):
        return "ecg", "baseline"

    # ── Questionnaires ───────────────────────────────────────────────
    # Mental health
    if _cat_in(cid, (136, 146), (1500, 1513), 100060):
        return "questionnaire_mental_health", "baseline"
    # Lifestyle
    if _cat_in(cid, 100050, 100051, 100052, 100053, 100054, 100055, 100056,
               100057, 100058, (205, 213), 1039, (100100, 100118), 704):
        return "questionnaire_lifestyle", "baseline"
    # Medical history
    if _cat_in(cid, 100036, (100037, 100048), 132, 153, 154, 160, 1003):
        return "questionnaire_medical", "baseline"
    # Cognitive
    if _cat_in(cid, (116, 122), (501, 506), 709, 100026, (100027, 100032),
               1358, 161, 11090):
        return "questionnaire_cognitive", "baseline"
    # Family / early life
    if _cat_in(cid, 100033, 100034, 214, 1002, 708):
        return "questionnaire_family", "baseline"
    # Sociodemographics (100068-100070 are sex-specific, handled below)
    if _cat_in(cid, 100062, (100063, 100067), 701, 1007):
        return "demographics", "baseline"
    # Sex-specific factors
    if _cat_in(cid, (100068, 100070)):
        return "questionnaire_sex_specific", "baseline"

    # ── Accelerometry ────────────────────────────────────────────────
    if _cat_in(cid, (1008, 1013), 1020, 267):
        return "accelerometry", "baseline"

    # ── Recruitment / procedural ─────────────────────────────────────
    if _cat_in(cid, 100000, 100001, (100002, 100006), 100021, (100022, 100025),
               100004, 100094, 100096, 100097, 100078, (100084, 100088),
               152, 129, 130, 164, 148, 127):
        return "procedural", "baseline"

    # ── Online follow-up (post-baseline) ─────────────────────────────
    if _cat_in(cid, 100089, (100090, 100091), 100114):
        return "online_followup", "online_followup"

    # ── Environment / deprivation ────────────────────────────────────
    if _cat_in(cid, 76, (113, 115), (150, 151), 123, 603,
               (702, 703), 711):
        return "environment", "baseline"

    # ── COVID sub-studies ────────────────────────────────────────────
    if _cat_in(cid, (989, 999), 996, 997, 998):
        return "covid", "online_followup"

    # ── PRS ──────────────────────────────────────────────────────────
    if _cat_in(cid, (300, 302)):
        return "polygenic_risk_scores", "genomics"

    # ── Summary / derived ────────────────────────────────────────────
    if _cat_in(cid, 1004, 1005, 1006, 54):
        return "summary_derived", "baseline"

    # ── Title-based fallback for "first occurrence" fields ───────────
    if "date" in title_lower and "first reported" in title_lower:
        return "first_occurrence_icd", "outcome_derived"
    if "source of report" in title_lower:
        return "first_occurrence_icd", "outcome_derived"

    return "other", "baseline"


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
    domain TEXT,
    risk_category TEXT DEFAULT 'baseline'
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
CREATE INDEX IF NOT EXISTS idx_fields_risk ON fields(risk_category);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_encoding_values_enc ON encoding_values(encoding_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS fields_fts USING fts5(
    title, units, domain, notes, risk_category,
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
    csv.field_size_limit(10 * 1024 * 1024)  # 10 MB — UKB hierarchical encodings can be large
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
        title = row.get("title", "").strip()

        # Classify field using category_id + title
        domain, risk_category = classify_field(main_cat, title)

        field_batch.append((
            fid,
            title,
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
            risk_category,
        ))
        field_count += 1

        if len(field_batch) >= 5000:
            conn.executemany(
                "INSERT OR IGNORE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                field_batch,
            )
            field_batch.clear()

    if field_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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

    # Risk category breakdown
    print("\n  Risk category breakdown:")
    for row in conn.execute("SELECT risk_category, COUNT(*) c FROM fields GROUP BY risk_category ORDER BY c DESC"):
        print(f"    {row[0]:25s} {row[1]:6,}")

    # Domain breakdown (top 15)
    print("\n  Domain breakdown (top 15):")
    for row in conn.execute("SELECT domain, COUNT(*) c FROM fields GROUP BY domain ORDER BY c DESC LIMIT 15"):
        print(f"    {row[0]:40s} {row[1]:6,}")

    # How many "other" remain?
    other_n = conn.execute("SELECT COUNT(*) FROM fields WHERE domain='other'").fetchone()[0]
    total_n = stats["fields"]
    print(f"\n  Unclassified (domain='other'): {other_n}/{total_n} = {other_n/total_n:.0%}")

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
