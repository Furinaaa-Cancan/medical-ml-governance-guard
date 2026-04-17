#!/usr/bin/env python3
"""
Fail-closed guard against disease-definition-variable leakage in medical prediction.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import add_issue


register_remediations({
    "definition_variable_leakage": "Predictor column directly matches a disease-definition variable. Remove it.",
    "definition_proxy_leakage": "Predictor column matches a forbidden proxy pattern. Remove or rename.",
    "definition_spec_missing": "Provide a valid phenotype_definition_spec JSON with target definitions.",
    "circular_definition_dependency": (
        "Defining variables form a circular dependency — variable A defines B and B defines A. "
        "Review the phenotype definition and break the cycle."
    ),
    "temporal_spec_missing": (
        "Publication-grade models must document prediction_time and follow_up_window "
        "in the phenotype definition spec. Add these fields to the target block."
    ),
    "post_prediction_feature_leakage": (
        "Predictor column is listed as post_prediction_features — data collected after "
        "the prediction time point. Remove it or justify why it is available at prediction time."
    ),
    "input_error": "Verify that all split CSV files exist and are readable.",
    "column_mismatch": "Ensure all split CSVs share identical column headers.",
    "missing_definition_spec": "Provide the phenotype definition spec JSON file at the specified path.",
    "invalid_definition_spec": "Fix the definition spec so it is a valid JSON object with correct field types.",
    "target_not_found": "Add the requested target to the definition spec targets block, or use --allow-missing-target.",
    "empty_forbidden_rules": "Define at least one forbidden variable or pattern in the definition spec for strict mode.",
    "invalid_forbidden_pattern": "Fix the invalid regex in forbidden_patterns so it compiles without errors.",
    "no_features_checked": "Reduce the ignore-cols list so at least one predictor column is checked.",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Block predictors that are used to define the same disease endpoint."
    )
    parser.add_argument("--target", required=True, help="Target name in definition spec, e.g. sepsis.")
    parser.add_argument("--definition-spec", required=True, help="Path to phenotype definition JSON.")
    parser.add_argument("--train", required=True, help="Training CSV.")
    parser.add_argument("--valid", help="Validation CSV.")
    parser.add_argument("--test", help="Test CSV.")
    parser.add_argument("--target-col", default="y", help="Target column to ignore from predictor checks.")
    parser.add_argument(
        "--ignore-cols",
        default="",
        help="Comma-separated non-predictor columns to ignore (ids/timestamps/etc).",
    )
    parser.add_argument("--report", help="Optional JSON report path.")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings.")
    parser.add_argument(
        "--cross-sectional",
        action="store_true",
        help="Declare data as cross-sectional (no temporal dimension). "
        "Suppresses temporal_spec_missing warning since prediction_time/"
        "follow_up_window do not apply to single-cycle cross-sectional data.",
    )
    parser.add_argument(
        "--allow-missing-target",
        action="store_true",
        help="Allow missing target in spec and use only global forbidden rules.",
    )
    return parser.parse_args()


def read_csv_header(path: str) -> List[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"Missing header row: {path}")
        return [h.strip() for h in header]


def parse_comma_set(raw: str) -> Set[str]:
    return {x.strip() for x in raw.split(",") if x.strip()}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def resolve_target_block(spec: Dict[str, Any], target: str) -> Optional[Dict[str, Any]]:
    targets = spec.get("targets")
    if not isinstance(targets, dict):
        return None
    if target in targets and isinstance(targets[target], dict):
        return targets[target]
    lowered = target.lower()
    for key, value in targets.items():
        if isinstance(key, str) and key.lower() == lowered and isinstance(value, dict):
            return value
    return None


def list_from(spec: Dict[str, Any], key: str) -> List[str]:
    raw = spec.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"Field '{key}' must be a list.")
    out: List[str] = []
    for item in raw:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
    return out


def compile_patterns(patterns: Iterable[str]) -> Tuple[List[re.Pattern[str]], List[str]]:
    compiled: List[re.Pattern[str]] = []
    errors: List[str] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, flags=re.IGNORECASE))
        except re.error as exc:
            errors.append(f"Invalid regex '{pattern}': {exc}")
    return compiled, errors


def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    split_paths = {"train": args.train}
    if args.valid:
        split_paths["valid"] = args.valid
    if args.test:
        split_paths["test"] = args.test

    try:
        headers_by_split = {}
        for name, path in split_paths.items():
            headers_by_split[name] = read_csv_header(path)
    except Exception as exc:
        _err_name = name if "name" in dir() else "unknown"
        _err_path = str(path) if "path" in dir() else "unknown"
        add_issue(failures, "input_error", f"Failed to read split headers for '{_err_name}'.", {"error": str(exc), "path": _err_path})
        return finish(args, failures, warnings, {}, [], [], [])

    header_sets = {name: set(cols) for name, cols in headers_by_split.items()}
    union_headers = set().union(*header_sets.values())
    intersection_headers = set.intersection(*header_sets.values()) if header_sets else set()
    if union_headers != intersection_headers:
        add_issue(
            warnings,
            "column_mismatch",
            "Split files have non-identical headers.",
            {"union_count": len(union_headers), "intersection_count": len(intersection_headers)},
        )

    spec_path = Path(args.definition_spec).expanduser().resolve()
    if not spec_path.exists():
        add_issue(
            failures,
            "missing_definition_spec",
            "Definition spec not found.",
            {"path": str(spec_path)},
        )
        return finish(args, failures, warnings, headers_by_split, [], [], [])

    try:
        with spec_path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except Exception as exc:
        add_issue(
            failures,
            "invalid_definition_spec",
            "Unable to parse definition spec JSON.",
            {"error": str(exc), "path": str(spec_path)},
        )
        return finish(args, failures, warnings, headers_by_split, [], [], [])

    if not isinstance(spec, dict):
        add_issue(
            failures,
            "invalid_definition_spec",
            "Definition spec must be a JSON object.",
            {"path": str(spec_path)},
        )
        return finish(args, failures, warnings, headers_by_split, [], [], [])

    target_block = resolve_target_block(spec, args.target)
    if target_block is None and not args.allow_missing_target:
        add_issue(
            failures,
            "target_not_found",
            "Target not found in definition spec.",
            {"target": args.target, "path": str(spec_path)},
        )
        return finish(args, failures, warnings, headers_by_split, [], [], [])
    target_block = target_block or {}

    try:
        global_forbidden_vars = list_from(spec, "global_forbidden_variables")
        global_patterns = list_from(spec, "global_forbidden_patterns")
        target_defining_vars = list_from(target_block, "defining_variables")
        target_forbidden_vars = list_from(target_block, "forbidden_variables")
        target_patterns = list_from(target_block, "forbidden_patterns")
    except ValueError as exc:
        add_issue(
            failures,
            "invalid_definition_spec",
            "Definition spec fields have invalid type.",
            {"error": str(exc)},
        )
        return finish(args, failures, warnings, headers_by_split, [], [], [])

    forbidden_exact = (
        global_forbidden_vars + target_defining_vars + target_forbidden_vars
    )
    forbidden_patterns = global_patterns + target_patterns

    if args.strict and not forbidden_exact and not forbidden_patterns:
        add_issue(
            failures,
            "empty_forbidden_rules",
            "No forbidden variables or patterns defined for strict mode.",
            {"target": args.target},
        )

    compiled_patterns, regex_errors = compile_patterns(forbidden_patterns)
    for err in regex_errors:
        add_issue(failures, "invalid_forbidden_pattern", "Invalid forbidden regex.", {"error": err})

    ignore_cols = parse_comma_set(args.ignore_cols)
    ignore_cols.add(args.target_col)

    forbidden_exact_norm = {norm(x): x for x in forbidden_exact}
    checked_features = sorted([h for h in union_headers if h not in ignore_cols])

    if not checked_features:
        add_issue(
            warnings,
            "no_features_checked",
            "No predictor columns were checked after applying ignore columns.",
            {"ignored_columns": sorted(ignore_cols)},
        )

    exact_hits: List[Dict[str, str]] = []
    pattern_hits: List[Dict[str, str]] = []

    for feature in checked_features:
        feature_norm = norm(feature)
        if feature_norm in forbidden_exact_norm:
            exact_hits.append({"feature": feature, "matched_rule": forbidden_exact_norm[feature_norm]})
        for pattern in compiled_patterns:
            if pattern.search(feature):
                pattern_hits.append({"feature": feature, "matched_pattern": pattern.pattern})

    if exact_hits:
        add_issue(
            failures,
            "definition_variable_leakage",
            "Detected predictor columns that are explicitly forbidden by disease definition rules.",
            {"hits": exact_hits},
        )
    if pattern_hits:
        add_issue(
            failures,
            "definition_proxy_leakage",
            "Detected predictor columns matching forbidden proxy patterns.",
            {"hits": pattern_hits},
        )

    # ── Circular definition detection ─────────────────────────────
    # Detect two types of circularity:
    # 1. Self-reference: target A's defining_variables include A itself
    # 2. Cross-reference: target A's defining_variables include target B
    targets_block = spec.get("targets")
    if isinstance(targets_block, dict) and len(targets_block) >= 1:
        all_target_names_norm = {norm(t) for t in targets_block}
        for t_name, t_block in targets_block.items():
            if not isinstance(t_block, dict):
                continue
            t_defining = list_from(t_block, "defining_variables")
            for dv in t_defining:
                dv_norm = norm(dv)
                if dv_norm == norm(t_name):
                    # Self-reference: defining variable is the target itself
                    add_issue(
                        failures,
                        "circular_definition_dependency",
                        f"Target '{t_name}' uses itself as a defining variable. "
                        f"This is a self-referential circular definition.",
                        {"target": t_name, "defining_variable": dv},
                    )
                elif dv_norm in all_target_names_norm:
                    # Cross-reference: defining variable is another target
                    add_issue(
                        failures,
                        "circular_definition_dependency",
                        f"Target '{t_name}' uses defining variable '{dv}' which is "
                        f"itself another target endpoint. This creates a circular dependency.",
                        {"target": t_name, "defining_variable": dv},
                    )

    # ── Temporal specification enforcement ─────────────────────────
    # Publication-grade models must document when the prediction is made
    # and how long the follow-up window is. Skipped for cross-sectional
    # data where these concepts do not apply (no temporal dimension exists
    # at the cohort level).
    if target_block and not getattr(args, "cross_sectional", False):
        has_prediction_time = bool(target_block.get("prediction_time"))
        has_follow_up = bool(target_block.get("follow_up_window"))
        if not has_prediction_time or not has_follow_up:
            missing_fields = []
            if not has_prediction_time:
                missing_fields.append("prediction_time")
            if not has_follow_up:
                missing_fields.append("follow_up_window")
            add_issue(
                warnings,
                "temporal_spec_missing",
                "Phenotype definition should document prediction_time and follow_up_window.",
                {
                    "target": args.target,
                    "missing_fields": missing_fields,
                    "hint": (
                        "Example: prediction_time='admission' follow_up_window='30 days'. "
                        "This enables temporal leakage detection."
                    ),
                },
            )

    # ── Post-prediction feature leakage ───────────────────────────
    # If spec lists features that are only available after the prediction
    # time point, check that none appear in the actual predictor columns.
    post_pred_features = []
    if target_block:
        post_pred_features = list_from(target_block, "post_prediction_features")
    if not post_pred_features:
        post_pred_features = list_from(spec, "post_prediction_features")
    if post_pred_features:
        post_pred_norm = {norm(f): f for f in post_pred_features}
        post_pred_hits: List[Dict[str, str]] = []
        for feature in checked_features:
            if norm(feature) in post_pred_norm:
                post_pred_hits.append({
                    "feature": feature,
                    "matched_rule": post_pred_norm[norm(feature)],
                })
        if post_pred_hits:
            add_issue(
                failures,
                "post_prediction_feature_leakage",
                "Predictor columns include features only available after the prediction time point.",
                {"hits": post_pred_hits},
            )

    return finish(
        args,
        failures,
        warnings,
        headers_by_split,
        sorted(forbidden_exact),
        forbidden_patterns,
        checked_features,
    )


def finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    headers_by_split: Dict[str, List[str]],
    forbidden_exact: List[str],
    forbidden_patterns: List[str],
    checked_features: List[str],
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_report

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    input_files = {
        "definition_spec": str(Path(args.definition_spec).expanduser().resolve()),
        "train": str(Path(args.train).expanduser().resolve()),
    }
    if getattr(args, "valid", None):
        input_files["valid"] = str(Path(args.valid).expanduser().resolve())
    if getattr(args, "test", None):
        input_files["test"] = str(Path(args.test).expanduser().resolve())

    report = build_report_envelope(
        gate_name="definition_variable_guard",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary={
            "target": args.target,
            "splits": {k: {"column_count": len(v), "columns": v} for k, v in headers_by_split.items()},
            "forbidden_exact_count": len(forbidden_exact),
            "forbidden_pattern_count": len(forbidden_patterns),
            "checked_feature_count": len(checked_features),
            "checked_features": checked_features,
        },
        input_files=input_files,
    )

    if args.report:
        _write_report(Path(args.report).expanduser().resolve(), report)

    print_gate_summary(
        gate_name="definition_variable_guard",
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
