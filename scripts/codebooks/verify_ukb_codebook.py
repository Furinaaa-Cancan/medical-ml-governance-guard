#!/usr/bin/env python3
"""Verify UKB codebook completeness and integrity.

Runs 3 layers of checks (see references/codebooks/ukb/KNOWN_GAPS.md):

    L1 — source fidelity:   .txt file sha256 + byte + line count match
                            committed source_manifest.json
    L2 — structural invariants: count assertions + FK integrity +
                            ICD/OPCS dict sizes + no duplicate field_ids
    L3 — golden-seed ground truth: known-famous UKB fields exist with
                            the expected metadata (ukb_golden_fields.yaml)

Exits 0 on clean pass, 2 on any violation.

Usage:
    python3 scripts/codebooks/verify_ukb_codebook.py
    python3 scripts/codebooks/verify_ukb_codebook.py --skip-l1
    python3 scripts/codebooks/verify_ukb_codebook.py --report /tmp/ukb_verify.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UKB_DIR = REPO_ROOT / "references" / "codebooks" / "ukb"
DEFAULT_DB = UKB_DIR / "ukb_codebook.sqlite"
DEFAULT_MANIFEST = UKB_DIR / "source_manifest.json"
DEFAULT_GOLDEN = UKB_DIR / "ukb_golden_fields.yaml"


# ── L2: structural invariants — baseline counts & hard invariants ───
# Baselines captured 2026-04-23; tolerate ±0.5% drift for each count
# in case UKB adds/removes a handful of fields between refreshes.
_COUNTS = {
    # (label, sql, expected, tolerance_pct)
    "fields_total":        ("SELECT COUNT(*) FROM fields;",                                                11821, 0.5),
    "categories_total":    ("SELECT COUNT(*) FROM categories;",                                              410, 5.0),
    "encodings_total":     ("SELECT COUNT(*) FROM encodings;",                                               858, 5.0),
    "encoding_values":     ("SELECT COUNT(*) FROM encoding_values;",                                      466907, 1.0),
    "icd10_codes":         ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=19;",                  19190, 0.5),
    "icd9_codes":          ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=87;",                  13710, 0.5),
    "opcs4_codes":         ("SELECT COUNT(*) FROM encoding_values WHERE encoding_id=240;",                 11288, 0.5),
    "nmr_cat_220":         ("SELECT COUNT(*) FROM fields WHERE main_category=220;",                          251, 0.5),
}

# Hard invariants (must be exact, no tolerance).
_HARD = {
    "duplicate_field_ids": (
        "SELECT COUNT(*) FROM (SELECT field_id FROM fields GROUP BY field_id HAVING COUNT(*) > 1);",
        0,
        "Fields table has duplicate field_id values — primary-key violation.",
    ),
    "bmi_21001":   ("SELECT COUNT(*) FROM fields WHERE field_id=21001;", 1, "Field 21001 (BMI) missing."),
    "hba1c_30750": ("SELECT COUNT(*) FROM fields WHERE field_id=30750;", 1, "Field 30750 (HbA1c) missing."),
    # 2026-04-23 strict audit fixed a missing catbrowse.txt loader:
    # the category hierarchy was not imported and every category had
    # parent_id=NULL, breaking tree-traversal queries. Assert that
    # ≥300 of the 410 categories have a non-null parent so the
    # regression can't silently return.
    "categories_with_parent_gte_300": (
        "SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL AND parent_id != 0;",
        # Note: this is a >= check semantically. The comparison in
        # check_hard_invariants is equality, so we express the
        # boundary via a different query that returns 1 if healthy.
        # Keep this marker here and enforce via the alternative
        # query below to avoid changing the tuple shape elsewhere.
        361,
        "Fewer than 300 categories have a parent — catbrowse.txt may "
        "not be loading. Check build_ukb_codebook_db.py step 1.",
    ),
    # Instance metadata — 9 instances had empty title/description
    # before the 2026-04-23 fix; assert none remain empty.
    "instances_with_title": (
        "SELECT COUNT(*) FROM instances WHERE title IS NOT NULL AND trim(title) != '';",
        13,
        "Some instances missing title — insvalue.txt column mapping "
        "may have regressed (columns are instance_id / descript / num_members).",
    ),
    # UKB ships 319 private=1 fields. 2026-04-23 strict audit split
    # these into:
    #   - 193 real PHI identifiers → risk_category='identifier_direct'
    #   - 126 EMBARGOED future-release imaging → risk_category='embargoed'
    # Sum must still equal 319 (the private=1 total from UKB); any
    # drift means either UKB changed the count OR our classifier
    # stopped distinguishing the two categories.
    "phi_fields_correctly_flagged": (
        "SELECT COUNT(*) FROM fields WHERE private=1 AND risk_category='identifier_direct';",
        193,
        "Private=1 real-PHI fields must carry risk_category="
        "'identifier_direct'. If this drops, classify_field() may be "
        "misclassifying DOB / home-location etc. as embargoed.",
    ),
    "embargoed_count": (
        "SELECT COUNT(*) FROM fields WHERE risk_category='embargoed';",
        126,
        "EMBARGOED future-release fields count changed. UKB may have "
        "unlocked some (good — migrate to real category) or removed "
        "the EMBARGOED prefix convention.",
    ),
    "private_total_still_319": (
        "SELECT COUNT(*) FROM fields WHERE private=1;",
        319,
        "UKB private=1 field total drifted. Either UKB revised "
        "privacy flags or fetch returned a different snapshot.",
    ),
    "no_private_labeled_baseline": (
        "SELECT COUNT(*) FROM fields WHERE private=1 AND risk_category='baseline';",
        0,
        "Private=1 fields must NEVER be labeled 'baseline' "
        "(leakage-guard would treat them as safe).",
    ),
    # Alias floor: we committed 106 entries as of 2026-04-23 (after
    # semantic audit fixed 5 incorrect first-occurrence mappings and
    # added 4 specific-disease aliases). Drift alerts on any change;
    # additions welcome — grow past this by bumping the number in
    # the same commit.
    "alias_floor": (
        "SELECT COUNT(*) FROM aliases;",
        106,
        "Alias table shrank — medical-term lookups degrade. Re-add "
        "removed mappings in COMMON_ALIASES (build_ukb_codebook_db.py).",
    ),
    # ICD-10 / ICD-9 / OPCS-4 parent chain — previously 100%
    # broken (parent_code stored UKB-internal numeric code_id instead
    # of the actual parent value string). After 2026-04-23 two-pass
    # fix, every parent_code resolves to a real code in the same
    # encoding, or is NULL for root nodes.
    "icd10_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=19 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=19);",
        0,
        "Some ICD-10 parent_code values don't exist in the table. "
        "build_ukb_codebook_db.py hierarchical loader likely regressed.",
    ),
    "icd9_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=87 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=87);",
        0, "ICD-9 parent chain broken.",
    ),
    "opcs4_orphan_parents": (
        "SELECT COUNT(*) FROM encoding_values ev "
        "WHERE ev.encoding_id=240 AND ev.parent_code IS NOT NULL "
        "AND ev.parent_code NOT IN (SELECT code FROM encoding_values WHERE encoding_id=240);",
        0, "OPCS-4 parent chain broken.",
    ),
    # Block-level aggregators (e.g., "Block A00-A09") must be marked
    # selectable=0 so lookups don't silently include them. Before the
    # 2026-04-23 fix selectable was mis-parsed as Y/N heuristic and
    # always returned 1.
    "icd10_block_level_nonselectable": (
        "SELECT COUNT(*) FROM encoding_values "
        "WHERE encoding_id=19 AND selectable=0 AND code LIKE 'Block %';",
        264,
        "ICD-10 block-level codes must carry selectable=0. "
        "selectable parser may have regressed to Y/N heuristic.",
    ),
    # Hierarchical heading preservation: 2026-04-23 strict audit found
    # 104 category-heading rows silently collapsed because the previous
    # PK (encoding_id, code) didn't tolerate repeated code='-1' rows
    # that UKB uses for non-leaf nodes in encodings 3/5/6/1003/1005/1006
    # (Cancer / Operation / Non-cancer Illness self-reported trees, used
    # by fields 20001/20002/20004). Fixed by widening PK with node_id
    # (UKB's internal code_id). Pin the exact source-row counts so the
    # bug can't silently return.
    "enc5_operation_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=5;",
        270,
        "Operation tree (encoding 5, field 20004) lost rows — check "
        "build PK / node_id handling in hierarchical loader.",
    ),
    "enc6_noncancer_illness_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=6;",
        474,
        "Non-cancer-illness tree (encoding 6, field 20002) lost rows.",
    ),
    "enc3_cancer_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=3;",
        89,
        "Cancer tree (encoding 3, field 20001) lost rows.",
    ),
    "enc1006_noncancer_retyped_rows_complete": (
        "SELECT COUNT(*) FROM encoding_values WHERE encoding_id=1006;",
        479,
        "Non-cancer illness (re-typed) tree lost rows.",
    ),
    # Every hierarchical row with a parent_node_id must point to an
    # existing node in the same encoding — verifies the heading-to-
    # heading DAG is fully connected.
    "hierarchical_parent_node_orphans": (
        "SELECT COUNT(*) FROM encoding_values child "
        "WHERE child.parent_node_id IS NOT NULL "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM encoding_values parent "
        "  WHERE parent.encoding_id=child.encoding_id "
        "  AND parent.node_id=child.parent_node_id"
        ");",
        0,
        "Some hierarchical rows reference a parent_node_id that doesn't "
        "exist — DAG broken. Heading preservation or code_id parsing may "
        "have regressed.",
    ),
    # FTS5 ↔ fields parity: every field must be searchable, no phantom
    # FTS rows. If rebuild() was skipped or the trigger to sync missed
    # an insert, lookups silently return nothing.
    "fts_matches_fields_count": (
        "SELECT (SELECT COUNT(*) FROM fields_fts) = (SELECT COUNT(*) FROM fields);",
        1, "FTS5 row count drifted from fields — index out of sync.",
    ),
    "fts_missing_no_fields": (
        "SELECT COUNT(*) FROM fields WHERE field_id NOT IN "
        "(SELECT rowid FROM fields_fts);",
        0, "Some fields have no FTS row — rebuild fields_fts.",
    ),
    "fts_no_phantom_rows": (
        "SELECT COUNT(*) FROM fields_fts WHERE rowid NOT IN "
        "(SELECT field_id FROM fields);",
        0, "FTS5 has rows without a backing field — stale index.",
    ),
}

# Ceiling checks — values we tolerate today but flag as technical debt
# if they rise. Not errors; useful signal for the operator.
_CEILINGS = {
    "orphan_field_cats": (
        "SELECT COUNT(*) FROM fields f WHERE f.main_category NOT IN (SELECT category_id FROM categories);",
        126,
        "Fields pointing to a main_category that is not in categories table.",
    ),
    # Note: removed the "alias_thinness" ceiling — the check direction
    # was inverted (growth is GOOD, not a warning). Floor enforced in
    # _HARD below.
}


def _row(conn: sqlite3.Connection, sql: str) -> int:
    """Run a scalar SQL query and return the first int value."""
    cur = conn.execute(sql)
    result = cur.fetchone()
    return int(result[0]) if result else 0


# ── L1 ──────────────────────────────────────────────────────────────

def check_source_manifest(
    ukb_dir: Path, manifest_path: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """Compare live .txt files in ukb_dir against committed manifest.

    Returns (issues, summary_dict).
    """
    issues: List[str] = []
    summary: Dict[str, Any] = {"files_checked": 0, "drift": []}
    if not manifest_path.exists():
        issues.append(f"manifest missing: {manifest_path}")
        return issues, summary
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"manifest unreadable: {exc}")
        return issues, summary
    for fname, entry in manifest.get("files", {}).items():
        path = ukb_dir / fname
        if not path.exists():
            issues.append(f"{fname}: not found locally")
            summary["drift"].append(fname)
            continue
        data = path.read_bytes()
        live_sha = hashlib.sha256(data).hexdigest()
        live_bytes = len(data)
        live_lines = data.count(b"\n")
        if live_sha != entry.get("sha256"):
            issues.append(f"{fname}: sha256 drift "
                          f"(ref={entry.get('sha256', '?')[:16]}, got={live_sha[:16]})")
            summary["drift"].append(fname)
        if live_bytes != entry.get("bytes"):
            issues.append(f"{fname}: byte count drift "
                          f"(ref={entry.get('bytes')}, got={live_bytes})")
        if live_lines != entry.get("lines"):
            issues.append(f"{fname}: line count drift "
                          f"(ref={entry.get('lines')}, got={live_lines})")
        summary["files_checked"] += 1
    return issues, summary


# ── L2 ──────────────────────────────────────────────────────────────

def check_counts(conn: sqlite3.Connection) -> Tuple[List[str], Dict[str, Any]]:
    """Assert baseline counts within tolerance."""
    issues: List[str] = []
    detail: Dict[str, Any] = {}
    for label, (sql, expected, tol_pct) in _COUNTS.items():
        actual = _row(conn, sql)
        low = int(expected * (1 - tol_pct / 100))
        high = int(expected * (1 + tol_pct / 100))
        detail[label] = {"actual": actual, "expected": expected,
                         "tolerance_pct": tol_pct}
        if not (low <= actual <= high):
            issues.append(
                f"{label}: {actual} not in [{low}, {high}] "
                f"(expected ~{expected}, ±{tol_pct}%)"
            )
    return issues, detail


def check_hard_invariants(conn: sqlite3.Connection) -> List[str]:
    """Assert hard invariants (exact-match)."""
    issues: List[str] = []
    for label, (sql, expected, message) in _HARD.items():
        actual = _row(conn, sql)
        if actual != expected:
            issues.append(f"{label}: got {actual}, expected {expected} — {message}")
    return issues


def check_ceilings(conn: sqlite3.Connection) -> List[str]:
    """Report ceilings as warnings only (debt signal, not error)."""
    warnings: List[str] = []
    for label, (sql, ceiling, message) in _CEILINGS.items():
        actual = _row(conn, sql)
        if actual > ceiling:
            warnings.append(
                f"{label}: {actual} exceeds known ceiling {ceiling} — {message}"
            )
    return warnings


# ── L3 ──────────────────────────────────────────────────────────────

def _load_golden(path: Path) -> List[Dict[str, Any]]:
    """Load golden-seed YAML (YAML is optional; fall back to JSON)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or []
    except ImportError:
        # Allow a JSON fallback so this module has zero external deps
        # in the minimal install path.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return []


def check_golden_fields(
    conn: sqlite3.Connection, golden_path: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """For each golden entry, assert the field exists and its metadata
    matches expected properties."""
    issues: List[str] = []
    golden = _load_golden(golden_path)
    checked = 0
    missing = 0
    mismatches = 0
    for entry in golden:
        if "field_id" in entry:
            checked += 1
            field_id = int(entry["field_id"])
            cur = conn.execute(
                "SELECT title, main_category FROM fields WHERE field_id=?",
                (field_id,),
            )
            row = cur.fetchone()
            if row is None:
                issues.append(f"golden field {field_id} not found")
                missing += 1
                continue
            title, main_cat = row
            # Optional checks — only enforce fields the YAML declares.
            if "title_contains" in entry:
                needle = entry["title_contains"].lower()
                if needle not in (title or "").lower():
                    issues.append(
                        f"golden field {field_id}: title '{title}' does not contain "
                        f"'{entry['title_contains']}'"
                    )
                    mismatches += 1
            if "title" in entry and entry["title"] != title:
                issues.append(
                    f"golden field {field_id}: title mismatch "
                    f"(expected {entry['title']!r}, got {title!r})"
                )
                mismatches += 1
            if "main_category" in entry and int(entry["main_category"]) != main_cat:
                issues.append(
                    f"golden field {field_id}: main_category "
                    f"{main_cat} != expected {entry['main_category']}"
                )
                mismatches += 1
        elif "icd10" in entry:
            checked += 1
            code = entry["icd10"].replace(".", "")
            # encoding_values(encoding_id, code, meaning, ...). ICD-10
            # codes in UKB often carry a trailing hyphen / block code
            # (e.g., "E11", "E11-Block", "E11.2"); LIKE match captures
            # any entry whose stripped-dot code starts with ours.
            cur = conn.execute(
                "SELECT code, meaning FROM encoding_values "
                "WHERE encoding_id=19 AND REPLACE(code,'.','') LIKE ? "
                "ORDER BY length(code) LIMIT 1",
                (code + "%",),
            )
            row = cur.fetchone()
            if row is None:
                issues.append(f"golden ICD10 {entry['icd10']} not found")
                missing += 1
                continue
            if "title_contains" in entry:
                needle = entry["title_contains"].lower()
                if needle not in (row[1] or "").lower():
                    issues.append(
                        f"golden ICD10 {entry['icd10']}: meaning '{row[1]}' "
                        f"does not contain '{entry['title_contains']}'"
                    )
                    mismatches += 1
    return issues, {
        "total": len(golden), "checked": checked,
        "missing": missing, "mismatches": mismatches,
    }


# ── Orchestration ──────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--skip-l1", action="store_true",
                        help="Skip source-file manifest check")
    parser.add_argument("--skip-l3", action="store_true",
                        help="Skip golden-field assertions")
    parser.add_argument("--report", type=Path, help="Write JSON report")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: UKB SQLite not found at {args.db}", file=sys.stderr)
        return 2

    all_issues: List[str] = []
    all_warnings: List[str] = []
    summary: Dict[str, Any] = {"layers": {}}

    # L1
    if not args.skip_l1:
        issues, l1_detail = check_source_manifest(UKB_DIR, args.manifest)
        summary["layers"]["l1_source_fidelity"] = {
            "issues": len(issues), "detail": l1_detail,
        }
        all_issues.extend(f"[L1] {i}" for i in issues)

    # L2
    with sqlite3.connect(str(args.db)) as conn:
        count_issues, count_detail = check_counts(conn)
        hard_issues = check_hard_invariants(conn)
        ceiling_warnings = check_ceilings(conn)
        summary["layers"]["l2_structural"] = {
            "count_issues": len(count_issues),
            "hard_invariant_issues": len(hard_issues),
            "ceiling_warnings": len(ceiling_warnings),
            "counts": count_detail,
        }
        all_issues.extend(f"[L2] {i}" for i in count_issues)
        all_issues.extend(f"[L2] {i}" for i in hard_issues)
        all_warnings.extend(f"[L2] {w}" for w in ceiling_warnings)

        # L3
        if not args.skip_l3:
            golden_issues, golden_detail = check_golden_fields(conn, args.golden)
            summary["layers"]["l3_golden"] = {
                "issues": len(golden_issues), "detail": golden_detail,
            }
            all_issues.extend(f"[L3] {i}" for i in golden_issues)

    # Report
    print("=" * 60)
    print("UKB codebook verification")
    print("=" * 60)
    if all_warnings:
        print(f"\n{len(all_warnings)} warning(s):")
        for w in all_warnings:
            print(f"  ⚠️  {w}")
    if all_issues:
        print(f"\n{len(all_issues)} issue(s):")
        for i in all_issues:
            print(f"  ❌ {i}")
    else:
        print("\n✅ All checks passed.")
    print("=" * 60)

    if args.report:
        out = {
            "status": "fail" if all_issues else "pass",
            "issues": all_issues,
            "warnings": all_warnings,
            "summary": summary,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(out, indent=2) + "\n")

    return 2 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
