#!/usr/bin/env python3
"""
Fail-closed split protocol gate for publication-grade medical prediction studies.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import _check_json_file_size, add_issue, try_parse_time as _shared_try_parse_time, epoch_to_iso as _shared_epoch_to_iso, _normalize_unicode


register_remediations({
    # -- Protocol spec validation --
    "split_protocol_missing": "Provide a valid split_protocol_spec JSON describing the splitting strategy.",
    "missing_protocol_spec": "Split protocol spec file not found. Verify --protocol-spec path.",
    "invalid_protocol_spec": "Split protocol spec JSON is malformed. Fix JSON syntax.",
    "invalid_protocol_field": "A required field in the split protocol spec is invalid or missing.",
    "protocol_id_col_mismatch": "Protocol id_col does not match --id-col. Align protocol spec with CLI args.",
    "protocol_time_col_mismatch": "Protocol time_col does not match --time-col. Align protocol spec with CLI args.",
    # -- Split integrity --
    "split_not_frozen": "Split protocol requires frozen splits but split_frozen is not true.",
    "split_seed_not_locked": "Random seed must be locked for reproducible splitting.",
    "split_io_error": "Cannot read a split CSV file. Verify file paths and permissions.",
    "empty_split": "A split file is empty (no data rows). Regenerate splits.",
    "invalid_labels": "Target column contains values other than 0/1. Ensure binary labels.",
    "single_class_split": "A split contains only one class. Use stratified splitting.",
    # -- Overlap and temporal --
    "id_overlap_between_splits": "Patient IDs overlap between splits. Use strict patient-level splitting.",
    "temporal_ordering_violation": "Temporal ordering violated between splits. Ensure train < valid < test in time.",
    "entity_overlap": "Entity (patient) IDs overlap between train and test splits. Use grouped splitting.",
    "temporal_boundary_violation": "Temporal boundary violated: test data precedes train data in time.",
    "missing_entity_ids": "ID column missing or empty in split data. Verify --id-col.",
    "no_parseable_times": "No parseable time values found. Verify --time-col format.",
    "invalid_time_values": "Time column contains unparseable values. Check date format.",
    # -- Policy warnings --
    "group_disjoint_not_required": "Protocol does not require group-disjoint splits. Consider enabling for medical data.",
    "temporal_order_not_required": "Protocol does not require temporal ordering. Consider enabling for longitudinal data.",
    "patient_overlap_allowed": "Protocol allows patient overlap between splits. This is unusual for medical data.",
    "time_overlap_allowed": "Protocol allows temporal overlap between splits. Consider requiring temporal ordering.",
    "cross_sectional_data": "Cross-sectional data has no temporal structure. Use --cross-sectional flag and document in TRIPOD+AI limitations.",
    # -- Sample adequacy --
    "missing_target_col": "Target column not found in split CSV. Verify --target-col matches your data.",
    "missing_time_col": "Time column missing or unparseable in split data. Verify --time-col.",
    "missing_id_col": "ID column missing in split data. Verify --id-col.",
    "prevalence_too_low": "Label prevalence is critically low. Consider stratified splitting or oversampling.",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate split protocol spec against observed split files.")
    parser.add_argument("--protocol-spec", required=True, help="Path to split protocol JSON.")
    parser.add_argument("--train", required=True, help="Path to train CSV.")
    parser.add_argument("--valid", help="Path to valid CSV.")
    parser.add_argument("--test", required=True, help="Path to test CSV.")
    parser.add_argument("--id-col", required=True, help="Entity ID column name.")
    parser.add_argument("--time-col", default="", help="Index/prediction time column name (optional for cross-sectional data).")
    parser.add_argument("--cross-sectional", action="store_true", help="Flag data as cross-sectional (no temporal structure). Skips temporal ordering checks.")
    parser.add_argument("--target-col", default="y", help="Target/label column name.")
    parser.add_argument("--report", help="Optional output JSON report path.")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings.")
    return parser.parse_args()


def parse_bool(spec: Dict[str, Any], key: str, failures: List[Dict[str, Any]]) -> Optional[bool]:
    value = spec.get(key)
    if isinstance(value, bool):
        return value
    add_issue(
        failures,
        "invalid_protocol_field",
        "Protocol field must be boolean.",
        {"field": key, "actual_type": type(value).__name__ if value is not None else None},
    )
    return None


def parse_non_empty_str(spec: Dict[str, Any], key: str, failures: List[Dict[str, Any]]) -> Optional[str]:
    value = spec.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    add_issue(
        failures,
        "invalid_protocol_field",
        "Protocol field must be a non-empty string.",
        {"field": key, "actual_type": type(value).__name__ if value is not None else None},
    )
    return None


def parse_label(raw: str) -> Optional[int]:
    s = raw.strip()
    if not s:
        return None
    if s in {"0", "0.0"}:
        return 0
    if s in {"1", "1.0"}:
        return 1
    try:
        parsed = float(s)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    if parsed == 0.0:
        return 0
    if parsed == 1.0:
        return 1
    return None


def try_parse_time(value: str) -> Optional[float]:
    return _shared_try_parse_time(value)


def epoch_to_iso(ts: Optional[float]) -> Optional[str]:
    return _shared_epoch_to_iso(ts)


def read_split(
    path: str,
    split_name: str,
    id_col: str,
    time_col: str,
    target_col: str,
) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"{split_name}: file not found: {path}")

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{split_name}: missing CSV header.")
        headers = [(h or "").strip() for h in reader.fieldnames]

        if id_col not in headers:
            raise ValueError(f"{split_name}: missing id_col '{id_col}'.")
        if time_col and time_col not in headers:
            raise ValueError(f"{split_name}: missing time_col '{time_col}'.")
        if target_col not in headers:
            raise ValueError(f"{split_name}: missing target_col '{target_col}'.")

        ids: Set[str] = set()
        missing_id_rows = 0
        invalid_label_rows = 0
        positive = 0
        negative = 0
        time_values: List[float] = []
        missing_time_rows = 0
        invalid_time_rows = 0
        row_count = 0

        for row in reader:
            row_count += 1

            id_val = _normalize_unicode(row.get(id_col) or "").strip()
            if id_val:
                ids.add(id_val)
            else:
                missing_id_rows += 1

            label = parse_label((row.get(target_col) or ""))
            if label is None:
                invalid_label_rows += 1
            elif label == 1:
                positive += 1
            else:
                negative += 1

            if time_col:
                t_raw = (row.get(time_col) or "").strip()
                if not t_raw:
                    missing_time_rows += 1
                else:
                    t_parsed = try_parse_time(t_raw)
                    if t_parsed is None:
                        invalid_time_rows += 1
                    else:
                        time_values.append(t_parsed)

    prevalence = None
    denom = positive + negative
    if denom > 0:
        prevalence = positive / float(denom)

    return {
        "path": str(Path(path).expanduser().resolve()),
        "headers": headers,
        "row_count": row_count,
        "id_count": len(ids),
        "ids": ids,
        "missing_id_rows": missing_id_rows,
        "positive_count": positive,
        "negative_count": negative,
        "invalid_label_rows": invalid_label_rows,
        "prevalence": prevalence,
        "time_min": min(time_values) if time_values else None,
        "time_max": max(time_values) if time_values else None,
        "time_parsed_count": len(time_values),
        "missing_time_rows": missing_time_rows,
        "invalid_time_rows": invalid_time_rows,
    }


def main() -> int:
    args = parse_args()
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    spec_path = Path(args.protocol_spec).expanduser().resolve()
    if not spec_path.exists():
        add_issue(
            failures,
            "missing_protocol_spec",
            "Split protocol spec file not found.",
            {"path": str(spec_path)},
        )
        return finish(args, failures, warnings, {}, {})

    try:
        _check_json_file_size(spec_path)
        with spec_path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
        if not isinstance(spec, dict):
            raise ValueError("Split protocol spec root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_protocol_spec",
            "Failed to parse split protocol spec JSON.",
            {"path": str(spec_path), "error": str(exc)},
        )
        return finish(args, failures, warnings, {}, {})

    split_strategy = parse_non_empty_str(spec, "split_strategy", failures)
    split_reference = parse_non_empty_str(spec, "split_reference", failures)
    protocol_id_col = parse_non_empty_str(spec, "id_col", failures)
    is_cross_sectional = bool(getattr(args, "cross_sectional", False)) or not args.time_col
    if is_cross_sectional:
        protocol_time_col = spec.get("index_time_col", "")
    else:
        protocol_time_col = parse_non_empty_str(spec, "index_time_col", failures)

    frozen_before_modeling = parse_bool(spec, "frozen_before_modeling", failures)
    requires_group_disjoint = parse_bool(spec, "requires_group_disjoint", failures)
    requires_temporal_order = parse_bool(spec, "requires_temporal_order", failures)
    allow_patient_overlap = parse_bool(spec, "allow_patient_overlap", failures)
    allow_time_overlap = parse_bool(spec, "allow_time_overlap", failures)
    split_seed_locked = parse_bool(spec, "split_seed_locked", failures)

    if protocol_id_col and protocol_id_col != args.id_col:
        add_issue(
            failures,
            "protocol_id_col_mismatch",
            "Protocol id_col does not match runtime id-col.",
            {"protocol_id_col": protocol_id_col, "runtime_id_col": args.id_col},
        )
    if protocol_time_col and args.time_col and protocol_time_col != args.time_col:
        add_issue(
            failures,
            "protocol_time_col_mismatch",
            "Protocol index_time_col does not match runtime time-col.",
            {"protocol_time_col": protocol_time_col, "runtime_time_col": args.time_col},
        )

    if frozen_before_modeling is not None and frozen_before_modeling is not True:
        add_issue(
            failures,
            "split_not_frozen",
            "Split protocol must be frozen before model development.",
            {},
        )
    if split_seed_locked is not None and split_seed_locked is not True:
        add_issue(
            failures,
            "split_seed_not_locked",
            "split_seed_locked must be true for reproducible split assignment.",
            {},
        )
    if requires_group_disjoint is not None and requires_group_disjoint is not True:
        add_issue(
            warnings,
            "group_disjoint_not_required",
            "requires_group_disjoint is not set to true. Recommended for medical "
            "entity-level prediction to prevent patient overlap across splits.",
            {},
        )
    if is_cross_sectional:
        # Only emit when the user has NOT explicitly acknowledged the
        # cross-sectional nature via --cross-sectional flag. Implicit
        # detection (no time_col + not explicitly declared) still warns
        # to prompt the user to document in TRIPOD+AI S03. Explicit
        # --cross-sectional is treated as acknowledgement.
        # (2026-04-17: preserves 42 existing tests while allowing onboarding
        # to pass --cross-sectional in request.cross_sectional=True runs.)
        if not bool(getattr(args, "cross_sectional", False)):
            add_issue(
                warnings,
                "cross_sectional_data",
                "Data flagged as cross-sectional. Temporal ordering checks skipped. "
                "Document this in limitations per TRIPOD+AI S03.",
                {"time_col": args.time_col or "(none)"},
            )
    elif requires_temporal_order is not None and requires_temporal_order is not True:
        add_issue(
            warnings,
            "temporal_order_not_required",
            "requires_temporal_order is not set to true. Recommended for longitudinal "
            "data to prevent future information leaking into training.",
            {},
        )
    if allow_patient_overlap is not None and allow_patient_overlap is not False:
        add_issue(
            failures,
            "patient_overlap_allowed",
            "allow_patient_overlap must be false.",
            {},
        )
    if allow_time_overlap is not None and allow_time_overlap is not False:
        add_issue(
            failures,
            "time_overlap_allowed",
            "allow_time_overlap must be false.",
            {},
        )

    splits: Dict[str, Dict[str, Any]] = {}
    split_paths = {"train": args.train, "test": args.test}
    if args.valid:
        split_paths["valid"] = args.valid

    try:
        for split_name, path in split_paths.items():
            splits[split_name] = read_split(path, split_name, args.id_col, args.time_col, args.target_col)
    except Exception as exc:
        add_issue(
            failures,
            "split_io_error",
            "Failed to parse split file.",
            {"error": str(exc)},
        )
        return finish(args, failures, warnings, spec, splits)

    for split_name, stats in splits.items():
        if stats["row_count"] <= 0:
            add_issue(
                failures,
                "empty_split",
                "Split must not be empty.",
                {"split": split_name},
            )
        if stats["invalid_label_rows"] > 0:
            add_issue(
                failures,
                "invalid_labels",
                "Split contains non-binary or invalid labels.",
                {"split": split_name, "invalid_label_rows": stats["invalid_label_rows"]},
            )
        if stats["positive_count"] == 0 or stats["negative_count"] == 0:
            add_issue(
                failures,
                "single_class_split",
                "Split must contain both positive and negative labels.",
                {
                    "split": split_name,
                    "positive_count": stats["positive_count"],
                    "negative_count": stats["negative_count"],
                },
            )
        if not is_cross_sectional:
            if stats["time_parsed_count"] <= 0:
                add_issue(
                    failures,
                    "no_parseable_times",
                    "Split has no parseable time values.",
                    {"split": split_name},
                )
            if stats["invalid_time_rows"] > 0:
                add_issue(
                    failures,
                    "invalid_time_values",
                    "Split contains unparseable time values.",
                    {"split": split_name, "invalid_time_rows": stats["invalid_time_rows"]},
                )
        if stats["missing_id_rows"] > 0:
            add_issue(
                failures,
                "missing_entity_ids",
                "Rows with missing entity IDs prevent reliable overlap leakage audit.",
                {"split": split_name, "missing_id_rows": stats["missing_id_rows"]},
            )
        if stats["prevalence"] is not None and stats["prevalence"] < 0.02:
            add_issue(
                warnings,
                "prevalence_too_low",
                "Label prevalence below 2% may degrade model reliability.",
                {
                    "split": split_name,
                    "prevalence": round(stats["prevalence"], 4),
                    "positive_count": stats["positive_count"],
                },
            )
        elif stats["positive_count"] > 0 and stats["positive_count"] < 5:
            add_issue(
                warnings,
                "prevalence_too_low",
                "Fewer than 5 positive cases in split; statistical reliability is limited.",
                {
                    "split": split_name,
                    "positive_count": stats["positive_count"],
                },
            )

    # Entity overlap
    for left, right in (("train", "valid"), ("train", "test"), ("valid", "test")):
        if left not in splits or right not in splits:
            continue
        overlap = splits[left]["ids"] & splits[right]["ids"]
        if overlap:
            add_issue(
                failures,
                "entity_overlap",
                "Entity IDs overlap across splits.",
                {"left_split": left, "right_split": right, "overlap_count": len(overlap)},
            )

    # Temporal ordering
    def check_order(left: str, right: str) -> None:
        if left not in splits or right not in splits:
            return
        left_max = splits[left]["time_max"]
        right_min = splits[right]["time_min"]
        if left_max is None or right_min is None:
            return
        # Strict inequality: allow equal timestamps at split boundaries.
        # See leakage_gate.py for rationale.
        if left_max > right_min:
            add_issue(
                failures,
                "temporal_boundary_violation",
                "Temporal order across splits is violated.",
                {
                    "left_split": left,
                    "right_split": right,
                    "left_max": epoch_to_iso(left_max),
                    "right_min": epoch_to_iso(right_min),
                },
            )

    if not is_cross_sectional:
        check_order("train", "valid")
        check_order("valid", "test")
        if "valid" not in splits:
            check_order("train", "test")

    return finish(args, failures, warnings, spec, splits, split_strategy=split_strategy, split_reference=split_reference)


def finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    spec: Dict[str, Any],
    splits: Dict[str, Dict[str, Any]],
    split_strategy: Optional[str] = None,
    split_reference: Optional[str] = None,
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_report

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    split_summary = {}
    for split_name, stats in splits.items():
        split_summary[split_name] = {
            "path": stats.get("path"),
            "row_count": stats.get("row_count"),
            "id_count": stats.get("id_count"),
            "positive_count": stats.get("positive_count"),
            "negative_count": stats.get("negative_count"),
            "prevalence": stats.get("prevalence"),
            "invalid_label_rows": stats.get("invalid_label_rows"),
            "time_min": epoch_to_iso(stats.get("time_min")),
            "time_max": epoch_to_iso(stats.get("time_max")),
            "time_parsed_count": stats.get("time_parsed_count"),
            "missing_time_rows": stats.get("missing_time_rows"),
            "invalid_time_rows": stats.get("invalid_time_rows"),
            "missing_id_rows": stats.get("missing_id_rows"),
        }

    input_files = {
        "protocol_spec": str(Path(args.protocol_spec).expanduser().resolve()),
        "train": str(Path(args.train).expanduser().resolve()),
        "test": str(Path(args.test).expanduser().resolve()),
    }
    if getattr(args, "valid", None):
        input_files["valid"] = str(Path(args.valid).expanduser().resolve())

    _cs_ack = bool(getattr(args, "cross_sectional", False)) or not getattr(args, "time_col", "")
    report = build_report_envelope(
        gate_name="split_protocol_gate",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary={
            "split_strategy": split_strategy,
            "split_reference": split_reference,
            "protocol_fields_present": sorted(spec.keys()) if isinstance(spec, dict) else [],
            "splits": split_summary,
            "cross_sectional_acknowledged": _cs_ack,
        },
        input_files=input_files,
    )

    if args.report:
        _write_report(Path(args.report).expanduser().resolve(), report)

    print_gate_summary(
        gate_name="split_protocol_gate",
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
