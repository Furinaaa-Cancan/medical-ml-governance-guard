#!/usr/bin/env python3
"""Build UK Biobank codebook SQLite database from Data Showcase schema files.

Reads:
  references/codebooks/ukb/field.txt          (field definitions)
  references/codebooks/ukb/encoding.txt       (encoding metadata)
  references/codebooks/ukb/category.txt       (category definitions)
  references/codebooks/ukb/esimpint.txt       (integer encoding values)
  references/codebooks/ukb/esimpstring.txt    (string encoding values)
  references/codebooks/ukb/esimpreal.txt      (real encoding values)
  references/codebooks/ukb/esimpdate.txt      (date encoding values)
  references/codebooks/ukb/ehierint.txt       (hierarchical int encoding values)
  references/codebooks/ukb/ehierstring.txt    (hierarchical string encoding values)
  references/codebooks/ukb/catbrowse.txt      (category browse tree)
  references/codebooks/ukb/insvalue.txt       (instance definitions)

Produces:
  references/codebooks/ukb/ukb_codebook.sqlite

Usage:
  python3 scripts/codebooks/build_ukb_codebook_db.py
  python3 scripts/codebooks/build_ukb_codebook_db.py --output /tmp/ukb_test.sqlite
"""
from __future__ import annotations

import argparse
import codecs
import csv
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ── UKB source encoding quirk ──────────────────────────────────────
# UKB .txt exports are almost pure UTF-8, but category.txt has 2
# stray 0x97 bytes (cp1252 em-dash) that are invalid UTF-8. Previous
# `errors="replace"` silently turned them into `�`, corrupting the
# notes field of category 100079 ("Advanced boundary segmentation
# [TABS]"). Round-9 strict-review found this. Register a handler
# that decodes the offending byte as cp1252 — preserves the em-dash
# while leaving valid UTF-8 multi-byte sequences intact.
def _cp1252_fallback(err: UnicodeDecodeError):
    return (err.object[err.start:err.end].decode("cp1252", errors="replace"),
            err.end)

codecs.register_error("ukb_cp1252_fallback", _cp1252_fallback)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DIR = REPO_ROOT / "references" / "codebooks" / "ukb"
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


def classify_field(cid: Optional[int], title: str, private: Optional[int] = None) -> Tuple[str, str]:
    """Return (domain, risk_category) for a UKB field.

    Domain: broad data category (e.g., 'imaging_brain', 'laboratory', 'questionnaire_lifestyle').
    Risk category:
      - 'identifier_direct': UKB `private=1` fields — direct PHI identifiers
                             (date of birth, home location coords, etc.).
                             Takes precedence over any category-based
                             classification because these can re-identify
                             participants regardless of how they're used.
      - 'outcome_derived'  : first-occurrence ICD dates/sources, algorithmically-defined outcomes
      - 'death_registry'   : death register fields
      - 'hospital_derived' : hospital inpatient / GP record fields
      - 'imaging'          : imaging-visit fields (inherently from later instances)
      - 'genomics'         : time-invariant genetic data
      - 'online_followup'  : post-baseline online questionnaires
      - 'baseline'         : safe baseline measurements (default)
    """
    title_lower_early = title.lower()

    # UKB's 'EMBARGOED' private=1 fields are pre-announced future
    # imaging releases (DXA, MRI, rfMRI surfaces etc.) gated behind
    # a cat=1000 placeholder. They're private not because they're
    # PHI but because data isn't unlocked yet. Classify separately
    # so a leakage-guard isn't confused — these WILL have a proper
    # risk_category once UKB releases them under their real category.
    if "EMBARGOED" in title.upper() or "embargoed" in title_lower_early:
        return "embargoed_future_release", "embargoed"

    # Direct-identifier fields ALWAYS get the PHI flag, regardless of
    # category. UKB marks these with private=1 in field.txt (date of
    # birth, parents' DOB components, home-location 1km coords,
    # full-resolution postcode, etc.). Strict audit 2026-04-23 caught
    # all 319 private=1 fields being mis-labeled 'baseline' before
    # this, which would make a leakage gate treat them as safe inputs.
    if private == 1:
        # Still return a meaningful domain so dashboards / by-domain
        # queries work; risk_category is the sensitive column.
        if "birth" in title_lower_early and "weight" not in title_lower_early:
            return "identifier_birth", "identifier_direct"
        if "location" in title_lower_early or "coordinate" in title_lower_early or "postcode" in title_lower_early:
            return "identifier_location", "identifier_direct"
        return "identifier_other", "identifier_direct"

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
    # Cardiac-monitoring wearable sub-study cats (347/348/349) were
    # mistakenly bucketed with cardiac-MRI. They're a separate UKB
    # sub-study using a portable cardiac monitor device, not MRI.
    # Removed 2026-04-23 round-6 deep-check; now handled by the
    # cardiac_monitoring rule below (online_followup risk).
    _HEART_MRI = {102, 133, 157, 162, 306,
                  523, 524, 525, 526, 527, 528, 529, 538}
    _DXA = {103, 124, 125, 522}
    _ABDOMINAL = {105, 126, 131, 149, 156, 158, 159}
    _EYE = {521, 1080, 1081, 1306, 1419, 100016, 100017,
            # Deep-check 2026-04-23: these UKB eye sub-categories were
            # landing in domain='other'. Refractometry / IOP / OCT /
            # surgery are all Assessment centre > Eye measures.
            100013, 100014, 100015, 100079, 100099}
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
    if _cat_in(cid, 134, 135, 107):  # 107 = Diffusion brain MRI parent pipeline
        return "imaging_dmri", "imaging"
    # Regional grey matter, fMRI
    if _cat_in(cid, 1101, 1102, 106, 109):
        return "imaging_brain", "imaging"

    # ── VO2max exercise test — rule-order fix ───────────────────────
    # Cat 267 "VO2max during exercise" is an Assessment-centre physical
    # measure (ECG-during-exercise derived). It must be checked BEFORE
    # the genomics range rule below — the range (263, 274) otherwise
    # swallows it into 'genomics', mis-classifying 4 fields (30035-30038)
    # that round-6 deep-check already intended to split out. The original
    # fix added a cid==267 check further down but rule-ordering put it
    # after genomics, so the split never actually happened.
    if cid == 267:
        return "vo2max_exercise", "baseline"

    # ── Genomics (time-invariant) ────────────────────────────────────
    # 100313 = Genotyping process and sample QC (deep-check 2026-04-23)
    # 100035 = HLA imputation values (deep-check 2026-04-23)
    if _cat_in(cid, (170, 187), (263, 274), (300, 302), 100035, 100313,
               100314, 100315, 100316, 100317, 100319, 199001):
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
    if cid == 100049:  # Hearing test (Assessment centre > Physical measures)
        return "hearing_test", "baseline"
    if cid == 100020:
        return "spirometry", "baseline"
    # ECG automated diagnoses (e.g., field 12653) are derived labels,
    # not raw measurements. Using them as features would leak the
    # outcome in cardiac-event prediction. Caught in 2026-04-23
    # deep-check. Catches any future ECG-diagnosis fields too.
    if "automated diagnos" in title_lower and _cat_in(cid, 104, 100012):
        return "ecg_diagnosis", "outcome_derived"
    if _cat_in(cid, 104, 100012):
        return "ecg", "baseline"

    # ── Questionnaires ───────────────────────────────────────────────
    # Cat 1511 = Online follow-up > Mental well-being > COVID-19.
    # UKB parks COVID-19 self-reported diagnosis events (29156-29161)
    # under the Mental-well-being folder because they ship in the same
    # online questionnaire, but the FIELDS themselves are infection
    # dates / methods of diagnosis / recovery status — outcome
    # variables, not mental-health items. Caught 2026-04-23 deep-check.
    if cid == 1511:
        return "covid_selfreport", "outcome_derived"
    # Mental health
    # Cat 147 (Happiness and subjective well-being, online follow-up).
    # The online-followup tree override promotes risk separately.
    if _cat_in(cid, (136, 146), 147, (1500, 1513), 100060):
        return "questionnaire_mental_health", "baseline"
    # Lifestyle
    if _cat_in(cid, 100050, 100051, 100052, 100053, 100054, 100055, 100056,
               100057, 100058, (205, 213), 1039, (100100, 100118), 704):
        return "questionnaire_lifestyle", "baseline"
    # Medical history (incl. verbal-interview sub-cats:
    # 100072 early life, 100074 medical conditions, 100075 meds, 100076 operations)
    if _cat_in(cid, 100036, (100037, 100048), 100072, 100074, 100075, 100076,
               132, 153, 154, 160, 1003):
        return "questionnaire_medical", "baseline"
    # Cognitive
    # Cat 100077 = Word production (pilot). Deep-check 2026-04-23.
    if _cat_in(cid, (116, 122), (501, 506), 709, 100026, (100027, 100032),
               100077, 1358, 161, 11090):
        return "questionnaire_cognitive", "baseline"
    # Family / early life
    if _cat_in(cid, 100033, 100034, 214, 1002, 708):
        return "questionnaire_family", "baseline"
    # Psychosocial (social support), baseline touchscreen.
    # Deep-check 2026-04-23: cat 100061 had 4 fields stuck in 'other'.
    if cid == 100061:
        return "questionnaire_psychosocial", "baseline"
    # Employment / job codes (baseline verbal interview).
    # Deep-check 2026-04-23: cat 100073 had 3 fields stuck in 'other'.
    if cid == 100073:
        return "questionnaire_employment", "baseline"
    # ── Cat 2 participant admin — lost-to-follow-up & contact log ────
    # Cat 2 = Population characteristics > Ongoing characteristics.
    # This is the cohort attrition outcome (fields 190/191) and the
    # post-baseline recontact/communication log (20143/20144/20145/
    # 110007). Previously lumped under 'demographics, baseline' via
    # the rule below, which would let a leakage-guard treat attrition
    # status as a safe baseline predictor. Split them off here BEFORE
    # the demographics bucket. Email access (20005) stays baseline —
    # it's asked at the baseline assessment, not a follow-up artifact.
    if cid == 2 and (
        "lost to follow-up" in title_lower
        or "personal contact" in title_lower
        or "newsletter" in title_lower
    ):
        return "participant_admin", "online_followup"
    # Sociodemographics (100068-100070 are sex-specific, handled below)
    if _cat_in(cid, 2, 100062, (100063, 100067), 701, 1007):
        return "demographics", "baseline"
    # Sex-specific factors
    if _cat_in(cid, (100068, 100070)):
        return "questionnaire_sex_specific", "baseline"

    # (cat 267 VO2max handled earlier — above the genomics range rule
    # — because the range (263, 274) otherwise swallows it.)

    # ── Accelerometry (POST-BASELINE by mail) ────────────────────────
    # UKB shipped accelerometers by mail 2013-2015, i.e., several
    # years AFTER baseline assessment (2006-2010). Using these as
    # "baseline" features introduces temporal leakage. Classify
    # as online_followup risk while preserving the accelerometry
    # domain. Caught 2026-04-23 round-6 deep-check.
    if _cat_in(cid, (1008, 1013), 1020):
        return "accelerometry", "online_followup"

    # ── Cardiac-monitoring sub-study (POST-BASELINE) ─────────────────
    # Cats 347/348/349 are a cardiology follow-up sub-study (ECG and
    # oscillometry phases 1 & 2), recruited years after baseline.
    # Same temporal-leakage concern as accelerometry.
    if _cat_in(cid, 347, 348, 349):
        return "cardiac_monitoring", "online_followup"

    # ── Recruitment / procedural ─────────────────────────────────────
    # Cat 100095 = Urine sample collection (sample timestamps /
    # no-sample reason). Deep-check 2026-04-23.
    if _cat_in(cid, 100000, 100001, (100002, 100006), 100021, (100022, 100025),
               100004, 100094, 100095, 100096, 100097, 100078, (100084, 100088),
               152, 129, 130, 164, 148, 127):
        return "procedural", "baseline"

    # ── Online follow-up (post-baseline) ─────────────────────────────
    # 100098 = Diet by 24-hour recall > Estimated nutrients yesterday
    # 155 = Cognitive function online > Mood
    # 215, 216 = Sleep (Lifestyle routines, Recent feelings)
    # 517-520 = Social Interactions and Focus (ADHD, Autism Spectrum,
    #           Emotional Dysregulation, SPQ-10)
    if _cat_in(cid, 100089, (100090, 100091), 100098, 100114,
               155, 215, 216, (517, 520)):
        return "online_followup", "online_followup"

    # ── Environment / deprivation ────────────────────────────────────
    if _cat_in(cid, 76, (113, 115), (150, 151), 123, 603,
               (702, 703), 711):
        return "environment", "baseline"

    # ── COVID sub-studies ────────────────────────────────────────────
    # 97 = Records of COVID-19 test results (deep-check 2026-04-23)
    if _cat_in(cid, 97, (989, 999), 996, 997, 998):
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
    -- parent_code: parent's display value string. Sufficient when
    -- the parent is uniquely identifiable by its code (ICD-10, OPCS-4).
    -- Ambiguous when parent is a heading (value='-1') — use
    -- parent_node_id in that case.
    parent_code TEXT,
    -- node_id: UKB's internal code_id for hierarchical rows; 0 for
    -- simple encodings. Needed in PK because hierarchical encodings
    -- (Cancer / Operation / Non-cancer Illness trees used by fields
    -- 20001/20002/20004) use value='-1' as a placeholder on every
    -- category-heading row. Keying by code alone collapsed 104
    -- heading rows into 7 survivors. Fixed 2026-04-23 after strict
    -- audit. Lookup by display code remains cheap via idx_ev_code.
    node_id INTEGER NOT NULL DEFAULT 0,
    -- parent_node_id: UKB's raw parent_id (= parent row's code_id),
    -- NULL for root nodes. Use this for unambiguous heading-to-
    -- heading traversal: JOIN parent ON parent.encoding_id=child.
    -- encoding_id AND parent.node_id=child.parent_node_id.
    parent_node_id INTEGER,
    PRIMARY KEY (encoding_id, node_id, code)
);

CREATE INDEX IF NOT EXISTS idx_ev_code ON encoding_values(encoding_id, code);

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
    # NOTE: 30740 is UKB's non-fasting serum glucose — do NOT alias
    # `fasting_glucose` to it (participants were not fasted at baseline).
    # Removed 2026-04-23: previous alias misled users into treating it
    # as a true fasting measurement.
    "glucose": 30740, "random_glucose": 30740, "serum_glucose": 30740,
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
    # Conditions (first occurrence fields). Strict audit 2026-04-23:
    # - "diabetes" now points to E11 (T2D, 95% of cases) not E10 (T1D)
    # - "copd" now points to J44 (proper COPD) not J40 (bronchitis)
    # - Added infarction / chf / asthma / ckd / esrd / pneumonia /
    #   cancer families that the 15-term alias audit showed missing.
    "diabetes": 130708,                       # E11 T2D (was 130706 = E10 T1D)
    "type2_diabetes": 130708, "t2dm": 130708, "t2d": 130708,
    "type1_diabetes": 130706, "t1dm": 130706, "t1d": 130706,
    # 2026-04-23 alias-semantics audit fixes:
    #   gestational_diabetes was pointing to 130714 (E14 "unspecified
    #   diabetes"); correct ICD-10 is O24 = 132202.
    "gestational_diabetes": 132202,           # O24 diabetes in pregnancy
    "hypertension": 131286, "htn": 131286, "high_blood_pressure": 131286,
    "stroke": 131366,                         # I63 cerebral infarction (~85% of strokes)
    # Strict audit 2026-04-23:
    #   ischaemic_stroke was pointing to I64 "stroke unspecified" —
    #   semantically wrong. Ischemic stroke = I63 cerebral infarction.
    #   hemorrhagic_stroke was pointing to I65 precerebral artery
    #   occlusion, which is neither ischemic nor hemorrhagic. Correct
    #   hemorrhagic-stroke code is I61 intracerebral haemorrhage.
    "ischaemic_stroke": 131366, "ischemic_stroke": 131366,  # I63
    "hemorrhagic_stroke": 131362,              # I61 intracerebral haemorrhage
    "stroke_unspecified": 131368,              # I64 — kept under its own name
    "heart_failure": 131354, "chf": 131354, "congestive_heart_failure": 131354,
    "myocardial_infarction": 131298, "mi": 131298, "infarction": 131298,
    "acute_mi": 131298, "ami": 131298,
    "atrial_fibrillation": 131350, "af": 131350, "afib": 131350,
    "copd": 131492,                           # J44 (was 131484 = J40 bronchitis)
    "j44": 131492,
    "bronchitis": 131484,                     # J40 kept here under its own name
    "asthma": 131494, "j45": 131494,
    "pneumonia": 131456,                      # J18 pneumonia organism unspec
    "ckd": 132032, "chronic_kidney_disease": 132032,
    "chronic_renal_failure": 132032, "n18": 132032,
    "esrd": 132034, "end_stage_renal_disease": 132034,
    # 2026-04-23 audit fix:
    #   alzheimers was pointing to F01 "vascular dementia" — an entirely
    #   different disease. G30 (131036) is the primary ICD-10 code for
    #   Alzheimer's disease. F00 (130836) is "dementia in Alzheimer's"
    #   (narrower). Keep `dementia` at F00 as the broadest single code
    #   and move `alzheimers` to G30.
    "dementia": 130836,                        # F00 dementia in AD
    "alzheimers": 131036, "alzheimer": 131036, # G30 Alzheimer's disease
    "vascular_dementia": 130838,               # F01 (kept under its own name)
    "depression": 130894, "major_depression": 130894,
    # 2026-04-23 audit fix: anxiety was pointing to F42 (OCD) — wrong.
    # F41 "other anxiety disorders" is the generic anxiety code.
    "anxiety": 130906,                        # F41 other anxiety disorders
    "ocd": 130908,                            # F42 OCD (kept under its own name)
    "cancer": 40005, "date_cancer_diagnosis": 40005,
    "cancer_type": 40006,
    # Death
    "date_of_death": 40000, "cause_of_death": 40001,
    "death": 40000, "mortality": 40000,
}


# ── File parsers ────────────────────────────────────────────────────────────

def read_tab_file(path: Path) -> List[Dict[str, str]]:
    """Read a UKB schema tab-separated file.

    Uses quoting=csv.QUOTE_NONE because UKB's .txt exports are pure
    TSV — `"` in meanings is literal text, NOT a field delimiter.
    Default csv.DictReader treats `"` as a quote char and merges
    rows until it finds a closing quote, silently losing data.
    Round-9 strict-review found this dropped 66,379 of 332,115 CTV3
    clinical code rows (esimpstring.txt encoding 7128) because 1180
    unbalanced quote characters triggered multi-line field parsing.
    """
    if not path.exists():
        print(f"  [SKIP] {path.name} not found", file=sys.stderr)
        return []
    with open(path, "r", encoding="utf-8", errors="ukb_cp1252_fallback") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
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

    # Load catbrowse edges — these are the AUTHORITATIVE parent-child
    # relationships for UKB categories. category.txt does NOT carry a
    # parent_id column (the public Showcase schema only has
    # category_id, title, availability, group_type, descript, notes),
    # so without loading catbrowse every categories.parent_id would
    # remain NULL and tree-traversal queries (find all descendants of
    # a cat) would return nothing. Fixed 2026-04-23 after strict audit.
    #
    # Must load catbrowse BEFORE computing full_path — otherwise every
    # path collapses to just the category's own title because parent
    # lookups return None. 2026-04-23 deep-check audit found 362/410
    # full_paths were wrong for exactly this reason.
    browse_rows = read_tab_file(input_dir / "catbrowse.txt")
    for row in browse_rows:
        cid = safe_int(row.get("child_id", ""))
        pid = safe_int(row.get("parent_id", ""))
        if cid is not None and pid is not None:
            # Always prefer catbrowse over category.txt because
            # category.txt doesn't carry parent info at all.
            cat_parents[cid] = pid

    # Build full paths AFTER catbrowse is merged in.
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

    # Simple encoding values (integer, string, real, date).
    # node_id=0 for all simple rows — they're uniquely identified by
    # (encoding_id, code) alone, so the PK tie-breaker is unused.
    for fname in ("esimpint.txt", "esimpstring.txt", "esimpreal.txt", "esimpdate.txt"):
        rows = read_tab_file(input_dir / fname)
        for row in rows:
            eid = safe_int(row.get("encoding_id", ""))
            code = row.get("value", "").strip()
            meaning = row.get("meaning", "").strip()
            if eid is not None and code:
                ev_batch.append((eid, code, meaning, 1, None, 0, None))
                ev_count += 1
                if len(ev_batch) >= 10000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?,?,?)",
                        ev_batch,
                    )
                    ev_batch.clear()

    # Hierarchical encoding values (ICD-10, OPCS-4, etc.).
    #
    # Strict audit 2026-04-23 fixed 2 real bugs here:
    #
    # BUG A — parent_code was storing the UKB-internal code_id (a
    # numeric), not the parent's actual value string. Every ICD-10
    # parent_code referenced a number (e.g., "230") that never
    # appeared as a code anywhere in the table, so recursive
    # block→chapter traversal returned nothing. Fix: build a
    # (encoding_id, code_id) → value map over two passes, then
    # translate each parent_id to the parent's value string on
    # insert.
    #
    # BUG B — selectable parsed with a Y/N heuristic but the file
    # has integer 1/0. Any value that wasn't the literal string "N"
    # became 1, so every hierarchical code was marked selectable=1
    # even for block-level aggregation labels (I70-I79 etc.) which
    # must not be selected. Fix: parse selectable as int.
    #
    # Pass 1: build code_id → value lookup per encoding.
    code_id_to_value: Dict[Tuple[int, str], str] = {}
    for fname in ("ehierint.txt", "ehierstring.txt"):
        for row in read_tab_file(input_dir / fname):
            eid = safe_int(row.get("encoding_id", ""))
            code_id = (row.get("code_id", "") or "").strip()
            value = row.get("value", "").strip()
            if eid is not None and code_id and value:
                code_id_to_value[(eid, code_id)] = value

    # Pass 2: insert with resolved parent_code and node_id.
    # node_id = UKB's internal code_id. Keeping it in PK guarantees
    # heading rows (which all share value='-1') don't collapse.
    for fname in ("ehierint.txt", "ehierstring.txt"):
        rows = read_tab_file(input_dir / fname)
        for row in rows:
            eid = safe_int(row.get("encoding_id", ""))
            code_id = safe_int(row.get("code_id", ""))
            code = row.get("coding", row.get("value", "")).strip()
            meaning = row.get("meaning", "").strip()
            parent_id_raw = (row.get("parent_id", row.get("parent", "")) or "").strip()
            # Resolve parent_id (internal) → parent's value string.
            # If parent_id is 0 or the lookup fails, set parent_code=NULL
            # (root node or unresolvable reference).
            parent: Optional[str] = None
            if parent_id_raw and parent_id_raw != "0" and eid is not None:
                parent = code_id_to_value.get((eid, parent_id_raw))
            # selectable: parse as 0/1 integer per UKB Showcase format.
            # Anything != 1 (including 0 and unparseable) → 0 (not selectable).
            sel_raw = (row.get("selectable", "") or "").strip()
            selectable = 1 if sel_raw == "1" else 0
            parent_node_id: Optional[int] = None
            if parent_id_raw and parent_id_raw != "0":
                try:
                    parent_node_id = int(parent_id_raw)
                except ValueError:
                    parent_node_id = None
            if eid is not None and code and code_id is not None:
                ev_batch.append((eid, code, meaning, selectable, parent, code_id, parent_node_id))
                ev_count += 1
                if len(ev_batch) >= 10000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?,?,?)",
                        ev_batch,
                    )
                    ev_batch.clear()

    if ev_batch:
        conn.executemany(
            "INSERT OR IGNORE INTO encoding_values VALUES (?,?,?,?,?,?,?)",
            ev_batch,
        )
    conn.commit()
    print(f"    {ev_count} encoding values loaded")

    # Compute the full set of Online-follow-up descendant category_ids.
    # UKB's "Online follow-up" tree (root = cat 100089) contains ~80
    # sub-categories of post-baseline questionnaires. 2026-04-23
    # deep-check found 1625 of 1833 fields in this tree were labeled
    # risk_category='baseline', which would let a leakage-guard treat
    # them as safe baseline predictors. Apply a post-classify override
    # below so the domain stays meaningful (questionnaire_mental_health
    # etc.) but risk correctly reflects temporal position.
    online_followup_cats: Set[int] = set()
    online_root = next(
        (cid for cid, t in cat_titles.items() if t == "Online follow-up"),
        None,
    )
    if online_root is not None:
        stack, seen = [online_root], set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            online_followup_cats.add(current)
            for child_cid, parent_cid in cat_parents.items():
                if parent_cid == current and child_cid not in seen:
                    stack.append(child_cid)
    print(f"    Online-follow-up descendants: {len(online_followup_cats)} cats")

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
        private = safe_int(row.get("private", ""))

        # Classify field using category_id + title + private flag.
        # private=1 promotes the field to risk_category=identifier_direct
        # regardless of category — direct PHI identifiers must not be
        # silently re-labeled as 'baseline'.
        domain, risk_category = classify_field(main_cat, title, private)

        # Temporal-position override: any field under the Online
        # follow-up tree that would otherwise be labeled 'baseline'
        # gets promoted to 'online_followup' because its data was
        # collected AFTER the baseline visit. Leaves other risk
        # categories intact (PHI / outcome / imaging already take
        # precedence correctly).
        if risk_category == "baseline" and main_cat in online_followup_cats:
            risk_category = "online_followup"

        field_batch.append((
            fid,
            title,
            safe_int(row.get("availability", "")),
            safe_int(row.get("stability", "")),
            private,
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
    # Fixed 2026-04-23 strict audit: insvalue.txt columns are
    # (instance_id, descript, num_members) — there's no "title" or
    # "description" column in the Showcase export. Old code looked
    # for wrong column names and got empty strings for 9 of 13
    # instances (Coronavirus serology, Accelerometer wearing,
    # Vaccination events, Cancer/Death registry etc.).
    print("  Loading instances...")
    ins_rows = read_tab_file(input_dir / "insvalue.txt")
    ins_batch = []
    for row in ins_rows:
        iid = safe_int(row.get("instance_id", ""))
        if iid is not None:
            temporal = INSTANCE_TEMPORAL_ORDER.get(str(iid), {})
            descript = row.get("descript", "").strip()
            # Use first 80 chars of descript as title if no hardcoded
            # label; full descript goes to description. Preserves the
            # hardcoded human-friendly labels for the canonical
            # visits 0-3 while resurrecting the other 9 instances'
            # metadata.
            title = temporal.get("label") or (descript[:80] if descript else None)
            description = descript or None
            ins_batch.append((iid, title, description, temporal.get("order")))

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
    print("UK Biobank Codebook SQLite built successfully!")
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
            print("Run fetch_ukb_showcase.py first to download schema files.", file=sys.stderr)
            return 2

    build_database(args.input_dir, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
