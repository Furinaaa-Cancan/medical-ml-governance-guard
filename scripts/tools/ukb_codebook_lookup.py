#!/usr/bin/env python3
"""UK Biobank codebook lookup and column validation tool.

Provides field lookup, column validation, and leakage detection for UKB datasets.
Analogous to nhanes_codebook_lookup.py but adapted to UKB's field/instance/encoding
structure.

Usage:
  # Single field lookup
  python3 scripts/tools/ukb_codebook_lookup.py --field 21001

  # Search by keyword
  python3 scripts/tools/ukb_codebook_lookup.py --search "blood pressure"

  # Validate CSV columns
  python3 scripts/tools/ukb_codebook_lookup.py --data my_ukb_extract.csv --report report.json

  # Lookup by common name
  python3 scripts/tools/ukb_codebook_lookup.py --field bmi
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "references" / "ukb_codebook" / "ukb_codebook.sqlite"

# ── UKB column name parser ──────────────────────────────────────────────────
# UKB columns follow pattern: <field_id>-<instance>.<array>
# Examples: 21001-0.0, 31-0.0, 4080-0.0, 4080-0.1

_UKB_COL_RE = re.compile(r"^(\d+)-(\d+)\.(\d+)$")


def parse_ukb_column(col: str) -> Optional[Tuple[int, int, int]]:
    """Parse UKB column name into (field_id, instance, array_index)."""
    m = _UKB_COL_RE.match(col.strip())
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # Try bare field ID
    try:
        return int(col.strip()), 0, 0
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
                    f"Run: python3 scripts/tools/fetch_ukb_showcase.py && "
                    f"python3 scripts/tools/build_ukb_codebook_db.py"
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
        # Sanitize FTS query
        safe_query = " ".join(
            w for w in re.sub(r"[^\w\s]", " ", query).split() if w
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

            # ── Check 2: Outcome/death fields as features ──
            title_lower = info["title"].lower()
            if any(kw in title_lower for kw in
                   ["date of death", "cause of death", "date of diagnosis",
                    "date of first", "age at death"]):
                issues.append({
                    "code": "UKB_OUTCOME_AS_FEATURE",
                    "message": (
                        f"Feature '{col}' ({info['title']}) appears to be an outcome or "
                        f"post-hoc variable. Using it as a predictor is likely leakage."
                    ),
                    "column": col,
                    "severity": "critical",
                    "field_id": fid,
                })

            # ── Check 3: Hospital episode / first occurrence fields ──
            if domain == "hospital_records" or domain == "summary":
                issues.append({
                    "code": "UKB_DERIVED_OUTCOME_FIELD",
                    "message": (
                        f"Feature '{col}' ({info['title']}) is from '{domain}' — "
                        f"these are derived from hospital records/registries and may "
                        f"contain post-baseline information. Verify temporal eligibility."
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
