#!/usr/bin/env python3
"""UK Biobank codebook lookup and column validation tool.

Provides field lookup, column validation, and leakage detection for UKB datasets.
Analogous to nhanes_codebook_lookup.py but adapted to UKB's field/instance/encoding
structure.

Usage:
  # Single field lookup
  python3 scripts/codebooks/ukb_codebook_lookup.py --field 21001

  # Search by keyword
  python3 scripts/codebooks/ukb_codebook_lookup.py --search "blood pressure"

  # Validate CSV columns
  python3 scripts/codebooks/ukb_codebook_lookup.py --data my_ukb_extract.csv --report report.json

  # Lookup by common name
  python3 scripts/codebooks/ukb_codebook_lookup.py --field bmi
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "references" / "codebooks" / "ukb" / "ukb_codebook.sqlite"

# ── UKB column name parser ──────────────────────────────────────────────────
# Supports multiple UKB column naming conventions:
#
# 1. RAP (DNAnexus) format: p<field_id>_i<instance>_a<array>
#    Examples: p21001_i0_a0, p4080_i1_a0, p41270, p53_i0
#
# 2. Data Showcase format: <field_id>-<instance>.<array>
#    Examples: 21001-0.0, 4080-1.0
#
# 3. Bare field ID: 21001, 4080

# RAP format: p<field>_i<inst>_a<arr> (instance/array optional)
_RAP_COL_RE = re.compile(r"^p(\d+)(?:_i(\d+))?(?:_a(\d+))?$")
# Showcase format: <field>-<inst>.<arr>
_SHOWCASE_COL_RE = re.compile(r"^(\d+)-(\d+)\.(\d+)$")


def parse_ukb_column(col: str) -> Optional[Tuple[int, int, int]]:
    """Parse UKB column name into (field_id, instance, array_index).

    Accepts RAP format (p21001_i0_a0), Showcase format (21001-0.0),
    or bare field ID (21001).
    """
    s = col.strip()

    # RAP format: p21001_i0_a0
    m = _RAP_COL_RE.match(s)
    if m:
        return (int(m.group(1)),
                int(m.group(2)) if m.group(2) else 0,
                int(m.group(3)) if m.group(3) else 0)

    # Showcase format: 21001-0.0
    m = _SHOWCASE_COL_RE.match(s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    # Bare field ID
    try:
        return int(s), 0, 0
    except ValueError:
        return None


# ── Main lookup class ───────────────────────────────────────────────────────

class UKBCodebook:
    """Query engine for the UKB codebook SQLite database."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._db_path.exists():
                raise FileNotFoundError(
                    f"UKB codebook database not found: {self._db_path}\n"
                    f"Run: python3 scripts/codebooks/fetch_ukb_showcase.py && "
                    f"python3 scripts/codebooks/build_ukb_codebook_db.py"
                )
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Alias resolution ─────────────────────────────────────────────────

    def resolve_alias(self, name: str) -> Optional[int]:
        """Resolve a common name to a field ID."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT field_id FROM aliases WHERE alias = ?",
            (name.lower().strip(),),
        ).fetchone()
        return row["field_id"] if row else None

    # ── Field lookup ─────────────────────────────────────────────────────

    def lookup(self, field_id_or_name: str) -> Optional[Dict[str, Any]]:
        """Look up a field by ID, column name, or common alias."""
        conn = self._ensure_conn()

        # Try parsing as UKB column (e.g., "21001-0.0")
        parsed = parse_ukb_column(field_id_or_name)
        if parsed:
            fid = parsed[0]
        else:
            # Try alias
            resolved = self.resolve_alias(field_id_or_name)
            if resolved:
                fid = resolved
            else:
                return None

        row = conn.execute("SELECT * FROM fields WHERE field_id = ?", (fid,)).fetchone()
        if not row:
            return None

        result = dict(row)

        # Get encoding values
        if result.get("encoding_id"):
            values = conn.execute(
                "SELECT code, meaning, selectable, parent_code FROM encoding_values "
                "WHERE encoding_id = ? ORDER BY code LIMIT 200",
                (result["encoding_id"],),
            ).fetchall()
            result["encoding_values"] = [dict(v) for v in values]
            total = conn.execute(
                "SELECT COUNT(*) FROM encoding_values WHERE encoding_id = ?",
                (result["encoding_id"],),
            ).fetchone()[0]
            result["encoding_total_values"] = total

        # Get category path
        if result.get("main_category"):
            cat = conn.execute(
                "SELECT full_path FROM categories WHERE category_id = ?",
                (result["main_category"],),
            ).fetchone()
            if cat:
                result["category_path"] = cat["full_path"]

        return result

    # ── Full-text search ─────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search fields by keyword using FTS5."""
        conn = self._ensure_conn()
        # Sanitize FTS query: strip punctuation and FTS5 operators
        _FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
        safe_query = " ".join(
            w for w in re.sub(r"[^\w\s]", " ", query).split()
            if w and w.upper() not in _FTS_OPERATORS
        )
        if not safe_query:
            return []

        rows = conn.execute(
            "SELECT f.field_id, f.title, f.value_type, f.units, f.domain, "
            "f.num_participants, f.main_category "
            "FROM fields_fts fts "
            "JOIN fields f ON f.field_id = fts.rowid "
            "WHERE fields_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (safe_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Column validation for leakage detection ──────────────────────────

    def validate_columns(
        self,
        columns: List[str],
        target_col: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate a list of UKB-style column names for leakage and data quality.

        Returns a dict with:
          - field_summary: per-field metadata
          - issues: list of detected problems
          - domain_breakdown: count by domain
        """
        conn = self._ensure_conn()
        issues: List[Dict[str, Any]] = []
        field_summary: List[Dict[str, Any]] = []
        domain_counts: Dict[str, int] = {}
        seen_fields: Dict[int, str] = {}  # field_id -> first column name

        # Parse target
        target_fid = None
        if target_col:
            parsed = parse_ukb_column(target_col)
            if parsed:
                target_fid = parsed[0]

        for col in columns:
            parsed = parse_ukb_column(col)
            if not parsed:
                # Not a UKB-format column, skip
                field_summary.append({"column": col, "recognized": False})
                continue

            fid, instance, array_idx = parsed

            # Skip target itself
            if target_fid and fid == target_fid:
                continue

            row = conn.execute(
                "SELECT * FROM fields WHERE field_id = ?", (fid,)
            ).fetchone()
            if not row:
                field_summary.append({"column": col, "recognized": False, "field_id": fid})
                issues.append({
                    "code": "UKB_UNKNOWN_FIELD",
                    "message": f"Field {fid} not found in UKB Data Showcase.",
                    "column": col,
                    "severity": "info",
                })
                continue

            info = dict(row)
            domain = info.get("domain", "other")
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

            field_summary.append({
                "column": col,
                "recognized": True,
                "field_id": fid,
                "title": info["title"],
                "value_type": info["value_type"],
                "domain": domain,
                "instance": instance,
                "array_index": array_idx,
            })

            # ── Check 1: Temporal leakage (using later instance to predict earlier) ──
            if target_col and target_fid:
                target_parsed = parse_ukb_column(target_col)
                if target_parsed:
                    target_instance = target_parsed[1]
                    if instance > target_instance:
                        issues.append({
                            "code": "UKB_TEMPORAL_LEAKAGE",
                            "message": (
                                f"Feature '{col}' is from instance {instance} "
                                f"(later than target instance {target_instance}). "
                                f"This is temporal leakage — feature measured AFTER the "
                                f"prediction timepoint."
                            ),
                            "column": col,
                            "severity": "critical",
                            "field_id": fid,
                        })

            # ── Check 2: Risk-category-based leakage detection ──
            risk = info.get("risk_category") or "baseline"
            if risk in ("outcome_derived", "death_registry"):
                issues.append({
                    "code": "UKB_OUTCOME_AS_FEATURE",
                    "message": (
                        f"Feature '{col}' ({info['title']}) is classified as "
                        f"risk={risk} (domain={domain}). This is a registry-derived "
                        f"outcome variable — using it as a predictor is leakage."
                    ),
                    "column": col,
                    "severity": "critical",
                    "field_id": fid,
                })
            elif risk == "hospital_derived":
                issues.append({
                    "code": "UKB_DERIVED_OUTCOME_FIELD",
                    "message": (
                        f"Feature '{col}' ({info['title']}) is from '{domain}' "
                        f"(risk=hospital_derived). Contains post-baseline data. "
                        f"Verify temporal eligibility."
                    ),
                    "column": col,
                    "severity": "warning",
                    "field_id": fid,
                })
            elif risk == "online_followup":
                issues.append({
                    "code": "UKB_DERIVED_OUTCOME_FIELD",
                    "message": (
                        f"Feature '{col}' ({info['title']}) is post-baseline "
                        f"online follow-up data (risk=online_followup)."
                    ),
                    "column": col,
                    "severity": "warning",
                    "field_id": fid,
                })

            # ── Check 4: Duplicate field across instances ──
            if fid in seen_fields:
                issues.append({
                    "code": "UKB_DUPLICATE_FIELD",
                    "message": (
                        f"Field {fid} appears as both '{seen_fields[fid]}' and '{col}'. "
                        f"Multiple instances of the same field — ensure this is intentional."
                    ),
                    "column": col,
                    "severity": "info",
                    "field_id": fid,
                })
            else:
                seen_fields[fid] = col

        return {
            "total_columns": len(columns),
            "recognized": sum(1 for fs in field_summary if fs.get("recognized")),
            "field_summary": field_summary,
            "issues": issues,
            "domain_breakdown": domain_counts,
        }

    # ── Encoding decode ──────────────────────────────────────────────────

    def decode_value(self, field_id: int, code: str) -> Optional[str]:
        """Decode a categorical value for a given field."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT f.encoding_id FROM fields f WHERE f.field_id = ?",
            (field_id,),
        ).fetchone()
        if not row or not row["encoding_id"]:
            return None
        meaning = conn.execute(
            "SELECT meaning FROM encoding_values WHERE encoding_id = ? AND code = ?",
            (row["encoding_id"], str(code)),
        ).fetchone()
        return meaning["meaning"] if meaning else None

    # ── Stats ────────────────────────────────────────────────────────────

    @property
    def variable_count(self) -> int:
        """Number of fields in the codebook (gate-compatible property)."""
        conn = self._ensure_conn()
        return conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]

    def stats(self) -> Dict[str, int]:
        """Return database statistics."""
        conn = self._ensure_conn()
        return {
            "fields": conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0],
            "categories": conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
            "encodings": conn.execute("SELECT COUNT(*) FROM encodings").fetchone()[0],
            "encoding_values": conn.execute("SELECT COUNT(*) FROM encoding_values").fetchone()[0],
            "aliases": conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0],
        }

    # ── RAP field list generator ────────────────────────────────────────
    # Generates a .txt file in the exact format RAP Table Exporter accepts.

    def field_to_rap_names(
        self, field_id: int, instance: int = 0, all_instances: bool = False,
    ) -> List[str]:
        """Expand a single field_id into RAP column name(s).

        Rules (derived from RAP Table Exporter conventions):
          instanced=0, arrayed=0  → ["p{fid}"]
          instanced>0, arrayed=0  → ["p{fid}_i{inst}"]
          instanced>0, arrayed>0  → ["p{fid}_i{inst}_a0", ..., "p{fid}_i{inst}_a{arr_max}"]
          instanced=0, arrayed>0  → ["p{fid}_a0", ..., "p{fid}_a{arr_max}"]

        If all_instances=True, expands across all instances (instance_min..instance_max).
        """
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT instanced, arrayed, instance_min, instance_max, "
            "array_min, array_max, value_type "
            "FROM fields WHERE field_id = ?", (field_id,)
        ).fetchone()
        if not row:
            return [f"p{field_id}"]

        instanced = row["instanced"] or 0
        arrayed = row["arrayed"] or 0
        inst_min = row["instance_min"] or 0
        inst_max = row["instance_max"] or 0
        arr_min = row["array_min"] or 0
        arr_max = row["array_max"] or 0
        value_type = row["value_type"] or ""

        # RAP Table Exporter: multi-select fields are stored as embedded arrays,
        # so _a suffix is skipped. Only non-multi-select arrays need expansion.
        # See: UKB RAP docs "accessing-phenotypic-data"
        is_multiselect = value_type in ("categorical_multiple",)
        expand_array = arrayed > 0 and not is_multiselect

        instances = list(range(inst_min, inst_max + 1)) if all_instances else [instance]

        names = []
        if instanced == 0 and not expand_array:
            names.append(f"p{field_id}")
        elif instanced > 0 and not expand_array:
            for inst in instances:
                names.append(f"p{field_id}_i{inst}")
        elif instanced > 0 and expand_array:
            for inst in instances:
                for arr in range(arr_min, arr_max + 1):
                    names.append(f"p{field_id}_i{inst}_a{arr}")
        elif instanced == 0 and expand_array:
            for arr in range(arr_min, arr_max + 1):
                names.append(f"p{field_id}_a{arr}")

        return names

    def generate_field_list(
        self,
        disease: str,
        instance: int = 0,
        include_outcome_fields: bool = True,
        include_death: bool = True,
        include_cancer_register: bool = False,
        output_path: Optional[Path] = None,
    ) -> List[str]:
        """Generate a RAP-compatible field list for a disease study.

        Args:
            disease: Disease key (e.g., 'type_2_diabetes', 'hypertension').
            instance: Assessment instance for baseline predictors (default 0).
            include_outcome_fields: Include first-occurrence / outcome fields.
            include_death: Include death register fields (40000, 40001).
            include_cancer_register: Include cancer register fields (40005, 40006).
            output_path: If given, write to this .txt file.

        Returns:
            List of RAP column names, one per line, with 'eid' at top.
        """
        conn = self._ensure_conn()
        lines: List[str] = ["eid"]

        # ── 1. Standard demographics ────────────────────────────────
        _DEMOGRAPHICS = [21022, 31, 21000, 189, 709, 6138]
        # 709 = household size, 6138 = qualifications/education
        for fid in _DEMOGRAPHICS:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 1b. Genetic quality control fields ──────────────────────
        _GENETIC_QC = [22001, 22019, 22189]
        # 22001 = genetic sex, 22019 = sex chromosome aneuploidy
        # 22189 = Townsend (genetic principal component derived)
        for fid in _GENETIC_QC:
            lines.extend(self.field_to_rap_names(fid))

        # ── 2. Anthropometry ────────────────────────────────────────
        _ANTHRO = [21001, 50, 21002, 48, 49]
        for fid in _ANTHRO:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 3. Laboratory (common biomarkers) ───────────────────────
        _LAB_COMMON = [30750, 30740, 30690, 30780, 30760, 30870, 30710,
                       30700, 30600, 30620, 30650, 30020]
        for fid in _LAB_COMMON:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 4. Blood pressure ───────────────────────────────────────
        for fid in [4080, 4079]:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 5. Assessment date ──────────────────────────────────────
        lines.extend(self.field_to_rap_names(53, instance))

        # ── 6. Common self-report diagnosis & medication fields ──────
        # These are general-purpose fields present in most UKB studies.
        # NOT disease definitions — users must define outcomes separately.
        _SELF_REPORT_MEDICAL = [
            2443,   # Diabetes diagnosed by doctor
            2966,   # Age high BP diagnosed
            2976,   # Age diabetes diagnosed
            2986,   # Started insulin within 1yr
            4041,   # Gestational diabetes
            4056,   # Age stroke diagnosed
            6148,   # Eye problems/disorders
            6150,   # Vascular/heart problems diagnosed
            6153,   # Medication for BP/cholesterol/diabetes
            6177,   # Medication for BP/cholesterol/diabetes (touchscreen)
        ]
        for fid in _SELF_REPORT_MEDICAL:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 7. General self-report conditions & medications ─────────
        # 20002 = non-cancer illness codes (array)
        # 20003 = treatment/medication codes (array)
        # 20001 = cancer codes (array)
        for fid in [20002, 20003, 20001]:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 8. Smoking (detailed) ──────────────────────────────────
        _SMOKING = [20116, 20160, 3456, 2887, 3436, 2867, 2897, 20161, 20162]
        # 20116 = status, 20160 = ever smoked, 3456/2887 = cigs/day
        # 3436/2867 = age started, 2897 = age stopped, 20161-2 = pack years
        for fid in _SMOKING:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 8b. Alcohol (detailed) ─────────────────────────────────
        _ALCOHOL = [20117, 1558, 1568, 1578, 1588, 1598, 1608,
                    4407, 4418, 4429, 4440, 4451]
        # 20117 = status, 1558 = frequency
        # 1568-1608 = weekly intake by type, 4407-4451 = monthly intake by type
        for fid in _ALCOHOL:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 8c. Diet ───────────────────────────────────────────────
        _DIET = [1239, 1249]
        for fid in _DIET:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 8d. Dietary nutrients (estimated daily intake) ──────────
        _NUTRIENTS = [26002, 26005, 26008, 26013, 26014, 26017, 26018,
                      26019, 26020, 26021, 26022, 26023, 26024, 26025,
                      26026, 26027, 26028, 26029, 26030, 26033, 26034,
                      26035, 26036, 26037, 26038, 26039, 26040, 26041,
                      26043, 26047, 26051, 26054, 26057, 26058]
        for fid in _NUTRIENTS:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 9. Physical activity ────────────────────────────────────
        _ACTIVITY = [22032, 22035, 22036, 22037, 22038, 22039, 22040]
        for fid in _ACTIVITY:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 9b. Sedentary / screen time ────────────────────────────
        _SEDENTARY = [1070, 1080, 1090]
        # 1070 = TV, 1080 = computer, 1090 = driving
        for fid in _SEDENTARY:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 10. Sleep ───────────────────────────────────────────────
        _SLEEP = [1160, 1170, 1180, 1190, 1200, 1210, 1220]
        for fid in _SLEEP:
            lines.extend(self.field_to_rap_names(fid, instance))

        # ── 11. Outcome fields ──────────────────────────────────────
        # NOTE: We do NOT auto-select disease-specific outcome fields.
        # Users must add their own outcome definition fields separately.
        # We only include hospital diagnosis codes (for user to filter)
        # and generic date fields.
        if include_outcome_fields:
            # Hospital inpatient ICD-10 diagnoses (user filters for their disease)
            for fid in [41270, 41280]:  # ICD10 diagnoses + dates
                lines.extend(self.field_to_rap_names(fid))
            # Hospital inpatient OPCS-4 procedures
            for fid in [41272, 41282]:  # OPCS4 codes + dates
                lines.extend(self.field_to_rap_names(fid))

        # ── 12. Death register ──────────────────────────────────────
        if include_death:
            for fid in [40000, 40001]:
                lines.extend(self.field_to_rap_names(fid, all_instances=True))

        # ── 13. Cancer register ─────────────────────────────────────
        if include_cancer_register:
            for fid in [40005, 40006, 40008, 40009]:
                lines.extend(self.field_to_rap_names(fid, all_instances=True))
            for fid in [20001]:
                lines.extend(self.field_to_rap_names(fid, instance))

        # Deduplicate while preserving order
        seen = set()
        unique_lines = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)

        if output_path:
            Path(output_path).write_text("\n".join(unique_lines) + "\n", encoding="utf-8")
            print(f"Written {len(unique_lines)} fields to {output_path}")

        return unique_lines

    # ── Gate-compatible interface ────────────────────────────────────────
    # Returns List[Dict] with {code, message, details} matching the format
    # expected by cohort_definition_gate.py's codebook RAG integration.
    #
    # Uses risk_category from the SQLite DB (built by classify_field())
    # and per-field num_participants for MNAR detection.

    # UKB total baseline participants (used for MNAR ratio calculation)
    _BASELINE_N = 502412

    # Per-instance approximate participation (well-documented UKB facts).
    # num_participants in schema is cross-instance total, NOT per-instance.
    # These are the only reliable per-instance numbers without actual data access.
    # Source: UKB Resource 135, UKB documentation.
    _INSTANCE_APPROX_N = {
        0: 502412,   # Initial assessment (2006-2010): all participants
        1: 20346,    # First repeat assessment (2012-2013): ~4%
        2: 100000,   # Imaging visit (2014-ongoing): ~20%
        3: 60000,    # First repeat imaging (2019-ongoing): ~12%
    }

    def validate_columns_for_gate(
        self,
        column_names: List[str],
        target_col: Optional[str] = None,
        manual_registry: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate columns in gate-compatible format.

        Returns a list of issue dicts [{code, message, details}] matching
        the interface of NHANESCodebook.validate_columns().

        Uses the pre-computed risk_category from the SQLite DB:
          - outcome_derived  → CRITICAL: label leakage
          - death_registry   → CRITICAL: post-hoc outcome
          - hospital_derived → WARNING: verify temporal eligibility
          - imaging          → INFO: later-instance risk
          - online_followup  → WARNING: post-baseline data
          - genomics         → safe (time-invariant)
          - baseline         → safe

        Also checks:
          - Instance-participation MNAR using actual num_participants
          - Temporal leakage (feature instance > target instance)
        """
        conn = self._ensure_conn()
        issues: List[Dict[str, Any]] = []

        target_fid, target_instance = None, 0
        if target_col:
            parsed = parse_ukb_column(target_col)
            if parsed:
                target_fid, target_instance = parsed[0], parsed[1]

        for col in column_names:
            parsed = parse_ukb_column(col)
            if not parsed:
                continue
            fid, instance, array_idx = parsed

            if target_fid and fid == target_fid:
                continue

            try:
                row = conn.execute(
                    "SELECT field_id, title, domain, risk_category, "
                    "value_type, encoding_id, "
                    "num_participants, instanced, instance_max "
                    "FROM fields WHERE field_id = ?", (fid,)
                ).fetchone()
            except Exception:
                # Fallback for old DB schema without risk_category/value_type
                row = conn.execute(
                    "SELECT field_id, title, domain, "
                    "num_participants, instanced "
                    "FROM fields WHERE field_id = ?", (fid,)
                ).fetchone()
            if not row:
                continue

            title = row["title"]
            domain = row["domain"] or "other"
            risk = (row["risk_category"] if "risk_category" in row.keys() else None) or "baseline"
            num_participants = row["num_participants"] or 0

            # ── Check 1: Risk-category-based leakage detection ──
            if risk == "outcome_derived":
                issues.append({
                    "code": "CODEBOOK_OUTCOME_AS_FEATURE",
                    "message": (
                        f"Column '{col}' ({title}) is classified as '{domain}' "
                        f"(risk=outcome_derived). This is a registry-derived outcome "
                        f"variable. Using it as a predictor constitutes label leakage."
                    ),
                    "details": {
                        "column": col, "field_id": fid,
                        "domain": domain, "risk_category": risk,
                    },
                })
            elif risk == "death_registry":
                issues.append({
                    "code": "CODEBOOK_OUTCOME_AS_FEATURE",
                    "message": (
                        f"Column '{col}' ({title}) is from the death registry "
                        f"(risk=death_registry). This is a post-hoc outcome variable."
                    ),
                    "details": {
                        "column": col, "field_id": fid,
                        "domain": domain, "risk_category": risk,
                    },
                })
            elif risk == "hospital_derived":
                issues.append({
                    "code": "CODEBOOK_DERIVED_OUTCOME_FIELD",
                    "message": (
                        f"Column '{col}' ({title}) is from '{domain}' "
                        f"(risk=hospital_derived). These fields contain post-baseline "
                        f"hospital/GP record data. Verify temporal eligibility."
                    ),
                    "details": {
                        "column": col, "field_id": fid,
                        "domain": domain, "risk_category": risk,
                    },
                })
            elif risk == "online_followup":
                issues.append({
                    "code": "CODEBOOK_DERIVED_OUTCOME_FIELD",
                    "message": (
                        f"Column '{col}' ({title}) is from online follow-up "
                        f"(risk=online_followup). This is post-baseline data collection."
                    ),
                    "details": {
                        "column": col, "field_id": fid,
                        "domain": domain, "risk_category": risk,
                    },
                })

            # ── Check 2: Temporal leakage (instance > target) ──
            if target_fid and instance > target_instance:
                issues.append({
                    "code": "CODEBOOK_TEMPORAL_LEAKAGE",
                    "message": (
                        f"Column '{col}' ({title}) is from instance {instance}, "
                        f"measured AFTER target instance {target_instance}. "
                        f"Using post-baseline features to predict baseline outcomes "
                        f"is temporal leakage."
                    ),
                    "details": {
                        "column": col, "field_id": fid,
                        "feature_instance": instance,
                        "target_instance": target_instance,
                    },
                })

            # ── Check 3: Instance-participation MNAR ──
            # Uses per-instance approximate participation (schema num_participants
            # is cross-instance total and unreliable for MNAR at specific instances).
            if instance > 0:
                inst_n = self._INSTANCE_APPROX_N.get(instance)
                if inst_n is not None:
                    participation_rate = inst_n / self._BASELINE_N
                    if participation_rate < 0.5:
                        issues.append({
                            "code": "CODEBOOK_INSTANCE_PARTICIPATION_MNAR",
                            "message": (
                                f"Column '{col}' ({title}) is from instance {instance}. "
                                f"Only ~{inst_n:,}/{self._BASELINE_N:,} participants "
                                f"({participation_rate:.0%}) attended this visit. "
                                f"This is Missing Not At Random (MNAR) — attendance correlates "
                                f"with health status, geography, and socioeconomic factors. "
                                f"Standard imputation will introduce bias."
                            ),
                            "details": {
                                "column": col, "field_id": fid,
                                "instance": instance,
                                "instance_participants": inst_n,
                                "participation_rate": round(participation_rate, 3),
                                "mechanism": "MNAR_instance_participation",
                            },
                        })

            # ── Check 4: Categorical encoding type ──
            # UKB categorical fields (categorical_single, categorical_multiple)
            # should NOT be treated as numeric.  Numeric encoding of nominal
            # categories (e.g., ethnic_background codes 1/1001/1002/2/2001)
            # implies a false ordinal relationship.
            value_type = (row["value_type"] if "value_type" in row.keys() else None) or ""
            if value_type in ("categorical_single", "categorical_multiple"):
                encoding_id = row["encoding_id"] if "encoding_id" in row.keys() else None
                n_values = 0
                if encoding_id:
                    n_values = conn.execute(
                        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id = ?",
                        (encoding_id,),
                    ).fetchone()[0]
                # Only warn for fields with >2 categories (binary is OK as 0/1)
                if n_values > 2:
                    issues.append({
                        "code": "CODEBOOK_ENCODING_CHECK",
                        "message": (
                            f"Column '{col}' ({title}) is {value_type} with "
                            f"{n_values} categories. If stored as numeric, the "
                            f"model will learn a false ordinal relationship. "
                            f"Use one-hot encoding for nominal categories."
                        ),
                        "details": {
                            "column": col, "field_id": fid,
                            "value_type": value_type,
                            "n_categories": n_values,
                            "source": "ukb_codebook",
                        },
                    })

        return issues

    def task_aware_validate(
        self,
        column_names: List[str],
        target_col: Optional[str] = None,
        target_disease: str = "",
        disease_kb_path: str = "",
        manual_registry: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Cross-reference columns with disease knowledge base.

        For UKB, the main risk is using ICD-code-derived 'first occurrence'
        fields that define the target condition as features.
        """
        if not target_disease or not disease_kb_path:
            return []

        try:
            kb = json.loads(Path(disease_kb_path).read_text(encoding="utf-8"))
        except Exception:
            return []

        diseases = kb.get("diseases", kb)
        disease_entry = diseases.get(target_disease, {})
        if not disease_entry:
            # Fuzzy match: try case-insensitive / underscore-space normalization
            target_lower = target_disease.lower().replace("_", " ").replace("-", " ")
            for dk, dv in diseases.items():
                dk_lower = dk.lower().replace("_", " ")
                name_lower = (dv.get("name", "") if isinstance(dv, dict) else "").lower()
                if target_lower in dk_lower or target_lower in name_lower or dk_lower in target_lower:
                    disease_entry = dv
                    break
        if not disease_entry:
            return []

        # Get UKB-specific definition fields from disease KB
        ukb_def_fields = disease_entry.get("ukb_definition_fields", [])
        ukb_exclusion_fields = disease_entry.get("ukb_exclusion_fields", [])
        definition_set = set(ukb_def_fields + ukb_exclusion_fields)

        # P0-2: propagate KB provenance into each emitted issue
        from _kb_provenance import extract_kb_provenance
        kb_provenance, _prov_hint = extract_kb_provenance(disease_entry)

        # Build self-report leakage set from our own UKB encoding_values table.
        # No external dependency — uses encoding data already in our SQLite.
        # For self-report array fields (20002=illness, 20004=operation),
        # search encoding_values for terms matching the target disease.
        conn = self._ensure_conn()
        _SELF_REPORT_FIELDS = {20002: 6, 20004: 5}  # field_id → encoding_id
        _self_report_matches: Dict[int, List[Dict[str, str]]] = {}

        # Build precise search phrases from disease name and key.
        # Use full phrases to avoid false positives (e.g., "kidney" matching
        # "kidney stone" when predicting CKD).
        disease_name = disease_entry.get("name", target_disease).lower()
        _search_phrases = [
            target_disease.lower().replace("_", " "),  # "type_2_diabetes" → "type 2 diabetes"
        ]
        # Add the canonical short name if different
        # Map common disease keys to the exact UKB self-report wording
        _DISEASE_TO_SEARCH = {
            "type_2_diabetes": ["type 2 diabetes", "diabetes"],
            "hypertension": ["hypertension"],
            "coronary_heart_disease": ["heart attack", "angina", "coronary"],
            "chronic_kidney_disease": ["renal failure", "kidney failure"],
            "heart_failure": ["heart failure"],
            "stroke": ["stroke"],
            "copd": ["copd", "chronic obstructive"],
            "major_depressive_disorder": ["depression"],
            "cancer_any": ["cancer"],
            "atrial_fibrillation": ["atrial fibrillation", "atrial flutter"],
        }
        _search_phrases = _DISEASE_TO_SEARCH.get(target_disease, _search_phrases)

        for sr_fid, sr_enc_id in _SELF_REPORT_FIELDS.items():
            try:
                for phrase in _search_phrases:
                    rows = conn.execute(
                        "SELECT code, meaning FROM encoding_values "
                        "WHERE encoding_id = ? AND LOWER(meaning) LIKE ?",
                        (sr_enc_id, f"%{phrase}%"),
                    ).fetchall()
                    for r in rows:
                        _self_report_matches.setdefault(sr_fid, []).append({
                            "code": str(r["code"]),
                            "meaning": r["meaning"],
                        })
            except Exception:
                pass
        # Deduplicate
        for sr_fid in _self_report_matches:
            seen = set()
            unique = []
            for m in _self_report_matches[sr_fid]:
                if m["code"] not in seen:
                    seen.add(m["code"])
                    unique.append(m)
            _self_report_matches[sr_fid] = unique

        if not definition_set and not _self_report_matches:
            return []

        issues: List[Dict[str, Any]] = []
        for col in column_names:
            parsed = parse_ukb_column(col)
            if not parsed:
                continue
            fid = parsed[0]

            # Check 1: Direct definition field match
            if str(fid) in definition_set or fid in definition_set:
                row = conn.execute(
                    "SELECT title FROM fields WHERE field_id = ?", (fid,)
                ).fetchone()
                title = row["title"] if row else f"field {fid}"
                issues.append({
                    "code": "CODEBOOK_DEFINITION_VARIABLE",
                    "message": (
                        f"Column '{col}' ({title}) is a definition variable for "
                        f"'{target_disease}'. Using it as a predictor constitutes "
                        f"circular reasoning (label leakage).{_prov_hint}"
                    ),
                    "details": {
                        "column": col,
                        "field_id": fid,
                        "target_disease": target_disease,
                        "source": "disease_kb_x_ukb_codebook",
                        "kb_provenance": kb_provenance,
                    },
                })

            # Check 2: Self-report array field containing disease-relevant codes
            # Data source: our own UKB SQLite encoding_values (no external dependency)
            elif fid in _self_report_matches:
                matches = _self_report_matches[fid]
                code_strs = ", ".join(
                    f"{m['code']}={m['meaning']}" for m in matches[:5]
                )
                row = conn.execute(
                    "SELECT title FROM fields WHERE field_id = ?", (fid,)
                ).fetchone()
                title = row["title"] if row else f"field {fid}"
                issues.append({
                    "code": "CODEBOOK_SELF_REPORT_LEAKAGE",
                    "message": (
                        f"Column '{col}' ({title}) is a self-report array field "
                        f"that contains codes related to '{target_disease}': "
                        f"[{code_strs}]. If any array element holds these codes, "
                        f"the model can directly observe the outcome. Exclude "
                        f"this field or remove the disease-specific codes.{_prov_hint}"
                    ),
                    "details": {
                        "column": col,
                        "field_id": fid,
                        "target_disease": target_disease,
                        "matching_codes": matches,
                        "source": "ukb_encoding_values",
                        "kb_provenance": kb_provenance,
                    },
                })

        return issues


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="UK Biobank codebook lookup and column validator"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="Path to UKB codebook SQLite")
    parser.add_argument("--field", help="Look up a field by ID, column name, or alias")
    parser.add_argument("--search", help="Full-text search for fields")
    parser.add_argument("--data", type=Path, help="CSV file to validate columns")
    parser.add_argument("--target", help="Target column for leakage checks")
    parser.add_argument("--report", type=Path, help="Output JSON report path")
    parser.add_argument("--stats", action="store_true", help="Print database statistics")
    parser.add_argument("--generate", nargs="?", const="baseline",
                        help="Generate RAP field list with common baseline variables. "
                             "Does NOT define disease outcomes — add those separately.")
    parser.add_argument("--output", "-o", type=Path,
                        help="Output .txt file path for --generate")
    parser.add_argument("--instance", type=int, default=0,
                        help="Baseline instance for --generate (default: 0)")
    parser.add_argument("--no-death", action="store_true",
                        help="Exclude death register fields from --generate")
    parser.add_argument("--with-cancer", action="store_true",
                        help="Include cancer register fields in --generate")
    args = parser.parse_args()

    cb = UKBCodebook(args.db)

    try:
        if args.stats:
            s = cb.stats()
            for k, v in s.items():
                print(f"  {k}: {v:,}")
            return 0

        if args.field:
            info = cb.lookup(args.field)
            if info:
                print(json.dumps(info, indent=2, default=str))
            else:
                print(f"Field not found: {args.field}", file=sys.stderr)
                return 1
            return 0

        if args.search:
            results = cb.search(args.search)
            if results:
                for r in results:
                    print(f"  {r['field_id']:>6d}  {r['title'][:60]:60s}  [{r['domain']}]")
            else:
                print(f"No results for: {args.search}", file=sys.stderr)
            return 0

        if args.generate is not None:
            out = args.output or Path("ukb_baseline_fields.txt")
            fields = cb.generate_field_list(
                disease=args.generate,
                instance=args.instance,
                include_death=not args.no_death,
                include_cancer_register=args.with_cancer,
                output_path=out,
            )
            print(f"\n  Instance:   {args.instance} (baseline)")
            print(f"  Fields:     {len(fields)}")
            print(f"  Output:     {out}")
            print("\n  NOTE: This list contains common baseline variables only.")
            print("  You must add your own outcome definition fields separately")
            print("  (e.g., first-occurrence ICD fields from Category 1712,")
            print("   or ADO fields from Category 42).")
            print(f"\n  Usage on RAP: upload {out.name} and use with Table Exporter")
            return 0

        if args.data:
            import pandas as pd
            df = pd.read_csv(args.data, nrows=0)
            columns = list(df.columns)
            result = cb.validate_columns(columns, target_col=args.target)

            n_issues = len(result["issues"])
            n_critical = sum(1 for i in result["issues"] if i["severity"] == "critical")
            print(f"Validated {result['total_columns']} columns, "
                  f"{result['recognized']} recognized")
            print(f"Issues: {n_issues} total, {n_critical} critical")

            if result["domain_breakdown"]:
                print("\nDomain breakdown:")
                for domain, count in sorted(result["domain_breakdown"].items(),
                                            key=lambda x: -x[1]):
                    print(f"  {domain:40s} {count:4d}")

            if result["issues"]:
                print("\nIssues:")
                for issue in result["issues"]:
                    sev = issue["severity"].upper()
                    print(f"  [{sev}] {issue['code']}: {issue['message']}")

            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(
                    json.dumps(result, indent=2, default=str),
                    encoding="utf-8",
                )
                print(f"\nReport written to {args.report}")

            return 2 if n_critical > 0 else 0

        parser.print_help()
        return 0

    finally:
        cb.close()


if __name__ == "__main__":
    sys.exit(main())
