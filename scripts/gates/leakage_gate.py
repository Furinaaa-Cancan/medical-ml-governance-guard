#!/usr/bin/env python3
"""
Leakage gate for supervised prediction CSV splits.

Checks:
1. Row-level overlap across splits.
2. Entity ID overlap across splits.
3. Temporal ordering consistency (if time column is provided).
4. Suspicious feature names that often indicate target leakage.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import csv
import hashlib
import itertools

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from _gate_utils import add_issue, check_csv_file_size, try_parse_time as _shared_try_parse_time, epoch_to_iso as _shared_epoch_to_iso, _normalize_unicode
from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)


register_remediations({
    "io_error": "Verify the CSV file path exists and is readable. Check file encoding (expected UTF-8).",
    "column_mismatch": "Ensure all split CSV files have identical column headers. Regenerate splits from the same source.",
    "missing_target_column": "The target column specified by --target-col is missing from the split CSV. Check column names.",
    "suspicious_feature_names": "Features matching leakage patterns detected. Rename or remove columns that encode future/target information.",
    "immortal_time_bias_pattern":
        "Feature name suggests a post-index treatment/intervention event "
        "(received_*, prescribed_*, administered_*, underwent_*, started_*, "
        "initiated_*, treated_with_*). Using this as a predictor creates "
        "IMMORTAL TIME BIAS: to 'receive' the treatment, the patient must "
        "survive to the treatment window; non-survivors are systematically "
        "assigned to the untreated group, artificially inflating the "
        "treatment group's survival. "
        "Fix: restrict cohort to patients who survived the landmark period, "
        "OR use a time-dependent covariate / landmark analysis, OR clone-"
        "censor-weight. "
        "Ref: Suissa 2008 Am J Epidemiol; Hernán 2016 J Clin Epidemiol.",
    "discharge_finalized_icd_as_feature":
        "Feature name embeds an ICD-10 code that is only assignable AT or "
        "AFTER discharge (palliative-care encounter Z51.5, DNR status Z66, "
        "brain death G93.82, ill-defined mortality R99, unspecified cardiac "
        "arrest I46.9). Presence of such a code as an admission-time "
        "predictor implies the outcome is already known, producing "
        "artificially inflated discrimination. "
        "Ramadan et al. (JAMA Netw Open 2025-12 "
        "doi:10.1001/jamanetworkopen.2025.50454) audited MIMIC mortality "
        "models and found 40.2% used discharge-finalized ICD codes as "
        "features, yielding AUROC 0.97-0.98. "
        "Fix: drop these columns, OR restrict ICD features to codes present "
        "on admission (POA flag=Y), OR move to a prospective design where "
        "the prediction timepoint precedes coding.",
    "row_overlap": "Identical rows found across splits. This indicates a split generation bug. Regenerate splits with proper deduplication.",
    "missing_id_columns": "ID columns specified by --id-cols are missing from the split CSV. Check column names.",
    "id_overlap": "Patient/entity IDs overlap between splits. Fix split generation to ensure strict ID separation.",
    "incomplete_id_rows": "Some rows have missing ID values. These were excluded from overlap checks. Verify data completeness.",
    "missing_time_column": "Time column specified by --time-col is missing. Check column names or omit --time-col.",
    "invalid_time_values": "Some time values couldn't be parsed. Check timestamp format consistency.",
    "no_parseable_time_values": "No valid timestamps found. Cannot perform temporal leakage checks.",
    "temporal_overlap": "Training data timestamps overlap with validation/test. Ensure strict temporal ordering in split boundaries.",
})


# Immortal time bias — post-index treatment/intervention patterns that
# leak survival information because receiving the intervention implies
# surviving to the intervention window. Kept separate from the generic
# suspicious-feature regex so the diagnostic points at the specific
# methodological error (Suissa 2008; Hernán 2016).
#
# False-positive guard: exempt columns whose names include
# pre-index / historical markers (e.g., ever_received_vaccine,
# started_on_drug_before_enrollment, history_prescribed_statin) —
# those are valid baseline covariates, not immortal time leakage.
# Also exempts demographic identifier suffixes like _name to avoid
# matching "patient_given_name".
IMMORTAL_TIME_RE = re.compile(
    r"(?:^|_)("
    r"received|prescribed|administered|treated_with|underwent|"
    r"started_on|initiated|assigned_to|given"
    r")_",
    re.IGNORECASE,
)

# If any of these tokens appear in the column name, treat the column as
# a baseline/historical/demographic indicator and do NOT flag as
# immortal time. Case-insensitive.
_IMMORTAL_TIME_EXEMPTIONS = re.compile(
    # Pre-index / historical tokens as whole words
    r"(?:^|_)(ever|history|hx|prior|past|baseline|pre[_-]?index|"
    r"before|at_birth|lifetime|previously)(?:$|_)"
    # Demographic identifier suffixes (e.g., patient_given_name, last_name)
    r"|_name$",
    re.IGNORECASE,
)


def is_immortal_time_suspect(col_name: str) -> bool:
    """Return True if a column name triggers the immortal-time regex
    AND is not exempted as a pre-index / historical / demographic marker."""
    if not IMMORTAL_TIME_RE.search(col_name):
        return False
    if _IMMORTAL_TIME_EXEMPTIONS.search(col_name):
        return False
    return True


# Discharge-finalized ICD-10 codes — only assignable at or after discharge,
# so their presence as admission-time predictors implies the outcome is
# already known (Ramadan et al. JAMA Netw Open 2025-12
# doi:10.1001/jamanetworkopen.2025.50454 — 40% of audited MIMIC mortality
# models used these, yielding AUROC 0.97-0.98).
#
# Scope is intentionally narrow: only codes whose definition is effectively
# "outcome-adjacent at the encounter level". Broader ICD codes (e.g., I21
# acute MI) may legitimately be on-admission (POA=Y) and are out of scope.
DISCHARGE_FINALIZED_ICD_CODES = (
    # Palliative-care / end-of-life encounters
    "Z51_5", "Z515", "Z51.5",
    # DNR / code-status
    "Z66",
    # Ill-defined / unknown cause of mortality (postmortem-only)
    "R99",
    # Unspecified cardiac arrest
    "I46_9", "I469", "I46.9",
    # Brain death (ICD-10-CM)
    "G93_82", "G9382", "G93.82",
)

_DISCHARGE_ICD_RE = re.compile(
    r"(?:^|[_\-\.])(?:"
    + "|".join(re.escape(c).replace(r"\.", r"\.") for c in DISCHARGE_FINALIZED_ICD_CODES)
    + r")(?:[_\-\.]|$)",
    re.IGNORECASE,
)

# Suffixes declaring that a feature is scoped to admission-time / present-on-
# admission, i.e., the coder affirms the value is knowable BEFORE the
# discharge-finalized coding happens. Trusting these suffixes is consistent
# with how POA flags work in CMS UB-04 and AHRQ data dictionaries. If a user
# abuses this declaration, that is a data-provenance issue upstream of the
# gate, not a regex-widening problem.
_ADMISSION_SCOPED_SUFFIX_RE = re.compile(
    r"(?:^|[_\-])(?:"
    r"admission|admit|"
    r"poa|present_on_admission|on_admission|at_admission|"
    r"baseline|preindex|pre_index|index|indexdate|"
    r"onset|at_onset|pre_admission"
    r")(?:[_\-](?:flag|ind|indicator))?$",
    re.IGNORECASE,
)


def is_discharge_finalized_icd_column(col_name: str) -> bool:
    """Return True if a column name embeds an ICD-10 code that is only
    assignable at or after discharge.

    Detects variants commonly produced by one-hot encoding of ICD codes,
    e.g., ``icd10_Z51_5``, ``dx_code_R99``, ``diagnosis_I46.9``,
    ``has_G93_82_braindeath``.

    Returns False when the column name carries an explicit admission-time
    scope suffix (e.g., ``_admission_flag``, ``_poa``, ``_on_admission``,
    ``_at_onset``). Those declarations override the discharge hit because
    POA-coded conditions ARE legitimately known at admission.
    """
    if not _DISCHARGE_ICD_RE.search(col_name):
        return False
    if _ADMISSION_SCOPED_SUFFIX_RE.search(col_name):
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strict anti-leakage checks on CSV splits.")
    parser.add_argument("--train", required=True, help="Path to training CSV.")
    parser.add_argument("--valid", help="Path to validation CSV.")
    parser.add_argument("--test", help="Path to test CSV.")
    parser.add_argument("--id-cols", default="", help="Comma-separated entity ID columns.")
    parser.add_argument("--time-col", help="Timestamp column for temporal leakage checks.")
    parser.add_argument("--target-col", help="Target column name.")
    parser.add_argument(
        "--ignore-cols",
        default="",
        help="Comma-separated columns to ignore in row-hash overlap checks.",
    )
    parser.add_argument(
        "--forbidden-feature-regex",
        default=(
            # `_`-aware word boundary: Python's \b treats `_` as a word
            # character, so \bleak\b FAILS to match `leak_flag` (no boundary
            # between `leak` and `_`). Use alnum-only lookarounds so the token
            # matches when delimited by start/end OR by `_`/`-`/`.`, while still
            # rejecting substrings like `leakage_score` or `postal` (`post`).
            r"(?<![A-Za-z0-9])(future|leak)(?![A-Za-z0-9])"
            r"|(?:^|_)(target|label)(?:_|$)"
            r"|(?:^|_)outcome(?!_date|_time|_period)(?:_|$)"
            r"|(?:^|_)(pred|predicted|actual|confirmed|diagnosed)(?:_|$)"
            r"|(?:^|_)(staging|stage_at)(?:_|$)"
            r"|(?:^|_)(pathology|biopsy_result|histology)(?:_|$)"
            # `next_` removed: false-positives on benign names like
            # `next_visit_count` (a legitimate baseline schedule count).
            # `future_`/`post_`/`after_` retained as true temporal-leak prefixes.
            r"|(?:^|_)(future_|post_|after_)"
            r"|(?:^|_)(diagnosis_date|dx_date|diag_date|death_date|event_date|outcome_date|discharge_date)"
            r"|(?:^|_)(readmit|mortality_flag|survival_status|los_days)"
            # Post-index / in-stay features (added 2026-04-17 after diabetes_130
            # dogfood run). These are outcomes of the hospitalization itself,
            # not predictors available at admission time:
            #  - time_in_hospital / length_of_stay / los — stay duration
            #  - num_medications / num_procedures / num_lab_procedures — in-stay counts
            #  - discharge / discharged_to / discharged_home — discharge disposition
            #  - ventilation_hours / vasopressor_* — ICU in-stay
            # SKILL.md §"Feature Timeline Audit" explicitly lists these as
            # Diabetes 130 / MIMIC classic leakage patterns.
            r"|(?:^|_)(time_in_hospital|length_of_stay|los)(?:_|$)"
            r"|(?:^|_)(num_medications|num_procedures|num_lab_procedures)(?:_|$)"
            r"|(?:^|_)(discharge|discharged)(?:_|$)"
            r"|(?:^|_)(ventilation_hours|ventilation_duration)(?:_|$)"
            r"|(?:^|_)(vasopressor)(?:_|$)"
        ),
        help="Regex for suspicious feature names. Covers: explicit markers (future, leak), target aliases, post-outcome variables (pred_, confirmed_, staging), temporal leakage (next_, post_, time_in_hospital, num_medications, etc.), outcome dates, derived outcome indicators, and ICU in-stay features (ventilation, vasopressor). Note: 'outcome' allows _date/_time/_period suffixes to reduce false positives on legitimate date columns.",
    )
    parser.add_argument("--report", help="Optional path to write JSON report.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings in addition to hard failures.",
    )
    args = parser.parse_args()
    if not args.valid and not args.test:
        parser.error("Provide at least one of --valid or --test.")
    return args


def parse_csv(path: str, split_name: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{split_name}: file not found: {path}")
    check_csv_file_size(Path(path))

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"{split_name}: missing CSV header row.")

            headers = [h.strip() if h else "" for h in reader.fieldnames]
            rows: List[Dict[str, str]] = []
            for raw in reader:
                clean: Dict[str, str] = {}
                for k, v in raw.items():
                    key = (k or "").strip()
                    clean[key] = (v or "").strip()
                rows.append(clean)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{split_name}: CSV file is not UTF-8 encoded ({path}). "
            f"Convert to UTF-8: iconv -f latin1 -t utf-8 {path} > {path}.utf8 — "
            f"Detail: {exc}"
        ) from exc

    return {"path": path, "headers": headers, "rows": rows}


def parse_comma_set(raw: str) -> Set[str]:
    return {x.strip() for x in raw.split(",") if x.strip()}


def row_signature(
    row: Dict[str, str],
    ignore_cols: Set[str],
    restrict_cols: Optional[Set[str]] = None,
) -> str:
    """Hash a CSV row into a deterministic signature.

    Uses length-prefixed encoding to prevent delimiter injection:
    each field is encoded as ``len(col):col:len(val):val`` so that
    no combination of column names and values can produce a collision.

    Args:
        restrict_cols: If provided, only hash these columns (used when
            splits have mismatched schemas to ensure comparable hashes).
    """
    parts = []
    for col in sorted(row.keys()):
        if col in ignore_cols:
            continue
        if restrict_cols is not None and col not in restrict_cols:
            continue
        val = row.get(col, "")
        parts.append(f"{len(col)}:{col}:{len(val)}:{val}")
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def try_parse_time(value: str) -> Optional[float]:
    return _shared_try_parse_time(value)


def bounds_for_time(rows: Iterable[Dict[str, str]], time_col: str) -> Dict[str, Any]:
    parsed: List[float] = []
    invalid = 0
    missing = 0
    for row in rows:
        raw = row.get(time_col, "").strip()
        if not raw:
            missing += 1
            continue
        ts = try_parse_time(raw)
        if ts is None:
            invalid += 1
            continue
        parsed.append(ts)

    if not parsed:
        return {
            "count": 0,
            "missing": missing,
            "invalid": invalid,
            "min": None,
            "max": None,
        }
    return {
        "count": len(parsed),
        "missing": missing,
        "invalid": invalid,
        "min": min(parsed),
        "max": max(parsed),
    }


def epoch_to_iso(ts: Optional[float]) -> Optional[str]:
    return _shared_epoch_to_iso(ts)




def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    split_paths = [("train", args.train), ("valid", args.valid), ("test", args.test)]
    splits: Dict[str, Dict[str, Any]] = {}
    try:
        for name, path in split_paths:
            if path:
                splits[name] = parse_csv(path, name)
    except Exception as exc:
        add_issue(failures, "io_error", f"Failed to read CSV input for '{name}' split.", {"error": str(exc), "path": str(path)})
        return finish(args, splits, failures, warnings)

    ignore_cols = parse_comma_set(args.ignore_cols)
    id_cols = [c for c in (x.strip() for x in args.id_cols.split(",")) if c]
    feature_name_re = re.compile(args.forbidden_feature_regex, flags=re.IGNORECASE)

    # Column consistency.
    column_sets = {k: set(v["headers"]) for k, v in splits.items()}
    union_cols = set().union(*column_sets.values()) if column_sets else set()
    intersection_cols = set.intersection(*column_sets.values()) if column_sets else set()
    if union_cols != intersection_cols:
        add_issue(
            warnings,
            "column_mismatch",
            "Split files have non-identical column sets.",
            {
                "union_count": len(union_cols),
                "intersection_count": len(intersection_cols),
            },
        )

    if args.target_col:
        for split_name, split in splits.items():
            if args.target_col not in split["headers"]:
                # Check for case mismatch before reporting missing
                lower_map = {h.lower(): h for h in split["headers"]}
                if args.target_col.lower() in lower_map:
                    actual = lower_map[args.target_col.lower()]
                    add_issue(
                        failures,
                        "missing_target_column",
                        f"Target column '{args.target_col}' not found in {split_name}, "
                        f"but '{actual}' exists (case mismatch). Use --target-col={actual}",
                        {"split": split_name, "target_col": args.target_col,
                         "actual_column": actual, "case_mismatch": True},
                    )
                else:
                    add_issue(
                        failures,
                        "missing_target_column",
                        "Target column missing in split.",
                        {"split": split_name, "target_col": args.target_col},
                    )

    # Suspicious headers.
    canonical_headers = splits["train"]["headers"] if "train" in splits else []
    suspicious = []
    for h in canonical_headers:
        if args.target_col and h == args.target_col:
            continue
        if feature_name_re.search(h):
            suspicious.append(h)
    if suspicious:
        add_issue(
            warnings,
            "suspicious_feature_names",
            "Feature names match leakage-prone patterns.",
            {"columns": suspicious},
        )

    # Immortal time bias — treatment/intervention events as predictors.
    # Orthogonal to generic suspicious patterns: here the concern is that a
    # "received X" flag implies the patient survived long enough to receive X,
    # leaking outcome information (Suissa 2008; Hernán 2016).
    immortal_hits = []
    for h in canonical_headers:
        if args.target_col and h == args.target_col:
            continue
        if is_immortal_time_suspect(h):
            immortal_hits.append(h)
    if immortal_hits:
        add_issue(
            failures,
            "immortal_time_bias_pattern",
            "Feature names indicate post-index treatment/intervention events.",
            {"columns": immortal_hits},
        )

    # Discharge-finalized ICD codes as features — Ramadan et al. 2025-12.
    # Scan every split's headers, not only train: a leak isolated to valid /
    # test headers (e.g., when holdout comes from a different ETL) still
    # compromises the evaluation.
    discharge_icd_hits_by_split: Dict[str, List[str]] = {}
    seen: set = set()
    for split_name, split_data in splits.items():
        for h in split_data["headers"]:
            if args.target_col and h == args.target_col:
                continue
            key = (split_name, h)
            if key in seen:
                continue
            if is_discharge_finalized_icd_column(h):
                discharge_icd_hits_by_split.setdefault(split_name, []).append(h)
                seen.add(key)
    if discharge_icd_hits_by_split:
        flat_hits = sorted({h for hits in discharge_icd_hits_by_split.values() for h in hits})
        add_issue(
            failures,
            "discharge_finalized_icd_as_feature",
            "Feature names embed ICD-10 codes only assignable at/after discharge.",
            {
                "columns": flat_hits,
                "columns_by_split": discharge_icd_hits_by_split,
            },
        )

    # Row overlap.
    # When columns differ between splits, restrict hashing to shared columns
    # so that extra columns don't defeat the overlap check.
    restrict = intersection_cols - ignore_cols if union_cols != intersection_cols else None
    # Guard: if shared columns (after ignoring IDs) are empty, skip row overlap
    # to avoid false positives from hashing empty payloads.
    if restrict is not None and not restrict:
        add_issue(
            warnings,
            "row_overlap_skipped",
            "No shared feature columns across splits after excluding ID/time columns. "
            "Row overlap check skipped to avoid false positives.",
            {"intersection_cols": sorted(intersection_cols), "ignore_cols": sorted(ignore_cols)},
        )
        restrict = None  # fall through to skip row overlap
        signature_sets: Dict[str, Set[str]] = {}
    else:
        signature_sets: Dict[str, Set[str]] = {}
        for split_name, split in splits.items():
            signature_sets[split_name] = {
                row_signature(row, ignore_cols, restrict_cols=restrict)
                for row in split["rows"]
            }

    for a, b in itertools.combinations(signature_sets.keys(), 2):
        overlap = signature_sets[a] & signature_sets[b]
        if overlap:
            add_issue(
                failures,
                "row_overlap",
                "Identical rows detected across splits.",
                {"pair": [a, b], "overlap_count": len(overlap)},
            )

    # Entity overlap.
    if id_cols:
        for split_name, split in splits.items():
            missing_cols = [c for c in id_cols if c not in split["headers"]]
            if missing_cols:
                add_issue(
                    failures,
                    "missing_id_columns",
                    "ID columns missing in split.",
                    {"split": split_name, "missing": missing_cols},
                )

        id_sets: Dict[str, Set[Tuple[str, ...]]] = {}
        for split_name, split in splits.items():
            keys: Set[Tuple[str, ...]] = set()
            null_key_rows = 0
            for row in split["rows"]:
                key: List[str] = []
                incomplete = False
                for col in id_cols:
                    val = _normalize_unicode(row.get(col, "")).strip()
                    if not val:
                        incomplete = True
                        break
                    key.append(val)
                if incomplete:
                    null_key_rows += 1
                    continue
                keys.add(tuple(key))
            id_sets[split_name] = keys
            if null_key_rows:
                add_issue(
                    warnings,
                    "incomplete_id_rows",
                    "Rows with missing ID columns were skipped in ID-overlap check.",
                    {"split": split_name, "skipped_rows": null_key_rows},
                )

        for a, b in itertools.combinations(id_sets.keys(), 2):
            overlap = id_sets[a] & id_sets[b]
            if overlap:
                add_issue(
                    failures,
                    "id_overlap",
                    "Entity IDs overlap across splits.",
                    {"pair": [a, b], "overlap_count": len(overlap), "id_cols": id_cols},
                )

    # Temporal ordering.
    time_bounds: Dict[str, Dict[str, Any]] = {}
    if args.time_col:
        for split_name, split in splits.items():
            if args.time_col not in split["headers"]:
                add_issue(
                    failures,
                    "missing_time_column",
                    "Time column missing in split.",
                    {"split": split_name, "time_col": args.time_col},
                )
                continue

            b = bounds_for_time(split["rows"], args.time_col)
            time_bounds[split_name] = b
            if b["invalid"] > 0:
                add_issue(
                    warnings,
                    "invalid_time_values",
                    "Some time values could not be parsed.",
                    {"split": split_name, "invalid_count": b["invalid"]},
                )
            if b["count"] == 0:
                add_issue(
                    failures,
                    "no_parseable_time_values",
                    "No parseable time values found for temporal checks.",
                    {"split": split_name},
                )

        def check_order(left: str, right: str) -> None:
            if left not in time_bounds or right not in time_bounds:
                return
            left_max = time_bounds[left]["max"]
            right_min = time_bounds[right]["min"]
            if left_max is None or right_min is None:
                return
            # Overlap requires train_max to be STRICTLY later than the next
            # split's min. An equal boundary (train_max == valid_min) across
            # DIFFERENT patients is NOT leakage: patient-disjointness is enforced
            # separately (S01), and shared index timestamps across patients are
            # common in clinical cohorts. (Reverted a W-audit over-correction
            # that used >=; canonical contract is tests/test_leakage_gate.py::
            # test_temporal_boundary_exact.)
            if left_max > right_min:
                add_issue(
                    failures,
                    "temporal_overlap",
                    "Temporal boundary violation detected.",
                    {
                        "left_split": left,
                        "right_split": right,
                        "left_max": epoch_to_iso(left_max),
                        "right_min": epoch_to_iso(right_min),
                    },
                )

        check_order("train", "valid")
        check_order("train", "test")
        check_order("valid", "test")

    return finish(args, splits, failures, warnings, time_bounds=time_bounds)


def finish(
    args: argparse.Namespace,
    splits: Dict[str, Dict[str, Any]],
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    time_bounds: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_json

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    summary = {
        "rows_per_split": {k: len(v["rows"]) for k, v in splits.items()},
        "columns_per_split": {k: len(v["headers"]) for k, v in splits.items()},
        "time_bounds": {
            k: {
                "min": epoch_to_iso(v.get("min")),
                "max": epoch_to_iso(v.get("max")),
                "parsed_count": v.get("count"),
                "missing_count": v.get("missing"),
                "invalid_count": v.get("invalid"),
            }
            for k, v in (time_bounds or {}).items()
        },
    }

    input_files = {"train": str(Path(args.train).expanduser().resolve())}
    if args.valid:
        input_files["valid"] = str(Path(args.valid).expanduser().resolve())
    if args.test:
        input_files["test"] = str(Path(args.test).expanduser().resolve())

    report = build_report_envelope(
        gate_name="leakage_gate",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary=summary,
        input_files=input_files,
    )

    if args.report:
        _write_json(Path(args.report).expanduser().resolve(), report)

    print_gate_summary(
        gate_name="leakage_gate",
        status=status,
        failures=fi,
        warnings=wi,
        strict=bool(args.strict),
        elapsed=get_gate_elapsed(),
    )

    return 2 if should_fail else 0


if __name__ == "__main__":
    from _gate_utils import start_gate_timer
    start_gate_timer()
    raise SystemExit(main())
