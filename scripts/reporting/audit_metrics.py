#!/usr/bin/env python3
"""Audit ML model metrics against publication-oriented reporting standards."""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

STANDARD_METRICS: Tuple[str, ...] = (
    "roc_auc", "pr_auc", "sensitivity", "specificity", "ppv", "npv", "f1",
    "f2_beta", "mcc", "brier", "accuracy", "lr_positive", "lr_negative",
    "calibration_slope",
)
SECTION_ORDER: Tuple[str, ...] = (
    "SUMMARY", "METRIC_COMPLETENESS", "SAMPLE_SIZE", "CALIBRATION",
    "CLINICAL_FLAGS", "TRIPOD_AI_GAPS", "JOURNAL_SPECIFIC_GAPS",
)
STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}

SIGNAL_GROUPS: Dict[str, Dict[str, Sequence[str]]] = {
    "calibration": {"exact": ("calibration_slope", "calibration_intercept", "ece", "o_e_ratio"), "prefixes": ()},
    "external_validation": {"exact": ("external_validation", "external_validation_note", "temporal_validation", "geographic_validation"), "prefixes": ()},
    "subgroup": {"exact": ("subgroup_analysis", "subgroup_auc", "subgroup_sensitivity", "subgroup_specificity"), "prefixes": ("subgroup_",)},
    "fairness": {"exact": ("fairness_assessment", "bias_assessment", "equalized_odds", "demographic_parity", "disparate_impact"), "prefixes": ("fairness_", "bias_")},
    "uncertainty": {"exact": ("uncertainty_quantification", "prediction_interval", "standard_error", "std_error"), "prefixes": ("uncertainty_",)},
    "model_card": {"exact": ("model_card", "intended_use", "intended_use_statement", "use_case"), "prefixes": ()},
    "tripod": {"exact": ("tripod_checklist", "tripod_ai_checklist", "tripod_ai_2024"), "prefixes": ()},
    "dca": {"exact": ("dca", "decision_curve_analysis", "decision_curve", "net_benefit"), "prefixes": ()},
    "net_benefit": {"exact": ("net_benefit",), "prefixes": ()},
}
JOURNAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "nature_medicine": {"label": "Nature Medicine", "requirements": ["calibration_required", "dca_required", "external_validation_required"]},
    "lancet_digital_health": {"label": "Lancet Digital Health", "requirements": ["calibration_required", "subgroup_analysis_required"]},
    "jama": {"label": "JAMA", "requirements": ["tripod_checklist_required"]},
    "bmj": {"label": "BMJ", "requirements": ["calibration_required", "net_benefit_required"]},
    "npj_digital_medicine": {"label": "npj Digital Medicine", "requirements": ["calibration_recommended"]},
}
JOURNAL_RULES: Dict[str, Dict[str, str]] = {
    "calibration_required": {"context_key": "has_calibration", "missing_status": "FAIL", "label": "Calibration evidence required", "missing_message": "No calibration evidence detected.", "present_message": "Calibration evidence detected."},
    "calibration_recommended": {"context_key": "has_calibration", "missing_status": "WARN", "label": "Calibration recommended", "missing_message": "No calibration evidence detected.", "present_message": "Calibration evidence detected."},
    "dca_required": {"context_key": "has_dca", "missing_status": "FAIL", "label": "Decision curve analysis required", "missing_message": "No DCA or net benefit signal detected in provided inputs.", "present_message": "DCA or net benefit signal detected."},
    "external_validation_required": {"context_key": "has_external_validation", "missing_status": "FAIL", "label": "External validation note required", "missing_message": "No external validation signal detected.", "present_message": "External validation signal detected."},
    "subgroup_analysis_required": {"context_key": "has_subgroup", "missing_status": "FAIL", "label": "Subgroup analysis required", "missing_message": "No subgroup analysis signal detected.", "present_message": "Subgroup analysis signal detected."},
    "tripod_checklist_required": {"context_key": "has_tripod", "missing_status": "FAIL", "label": "TRIPOD checklist required", "missing_message": "No explicit TRIPOD checklist signal detected.", "present_message": "Explicit TRIPOD checklist signal detected."},
    "net_benefit_required": {"context_key": "has_net_benefit", "missing_status": "FAIL", "label": "Net benefit evidence required", "missing_message": "No net benefit signal detected.", "present_message": "Net benefit signal detected."},
}
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit ML model metrics against publication standards.",
        allow_abbrev=False,
    )
    parser.add_argument("--metrics", required=True, help="JSON string or @file.json with metric key-value pairs.")
    parser.add_argument("--n-train", required=True, type=positive_int, help="Training sample size.")
    parser.add_argument("--n-test", required=True, type=positive_int, help="Test sample size.")
    parser.add_argument("--n-features", required=True, type=positive_int, help="Number of model features.")
    parser.add_argument("--prevalence", required=True, type=prevalence_float, help="Outcome prevalence in (0, 1).")
    parser.add_argument("--target-journal", required=True, choices=sorted(JOURNAL_PRESETS), help="Journal preset.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    parser.add_argument(
        "--ci",
        default=None,
        help="Optional JSON string or @file with CI info, e.g. '{roc_auc: [0.81, 0.85]}'.",
    )
    return parser.parse_args()
def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed
def prevalence_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 < parsed < 1.0:
        raise argparse.ArgumentTypeError("value must be between 0 and 1 (exclusive)")
    return parsed
def load_metrics(raw_value: str) -> Dict[str, Any]:
    payload = parse_mapping_text(load_text_arg(raw_value, "metrics"), "metrics")
    return {str(key).strip(): coerce_scalar(value) for key, value in payload.items()}
def load_text_arg(raw_value: str, label: str) -> str:
    if raw_value.startswith("@"):
        path = Path(raw_value[1:]).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"unable to read {label} file '{path}': {exc}") from exc
    return raw_value
def parse_mapping_text(text: str, label: str) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError(f"{label} payload is empty")
    candidates = [text]
    quoted = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', text)
    if quoted != text:
        candidates.append(quoted)
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                raise ValueError(f"{label} payload must decode to an object")
            return {str(key): value for key, value in parsed.items()}
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
        try:
            parsed = ast.literal_eval(candidate)
            if not isinstance(parsed, dict):
                raise ValueError(f"{label} payload must evaluate to a dict")
            return {str(key): value for key, value in parsed.items()}
        except (SyntaxError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"unable to parse {label} payload: {last_error}")
def load_ci(raw_value: Optional[str]) -> Tuple[Optional[Dict[str, List[float]]], List[str]]:
    if raw_value is None:
        return None, []
    payload = parse_mapping_text(load_text_arg(raw_value, "ci"), "ci")
    valid: Dict[str, List[float]] = {}
    invalid: List[str] = []
    for key, value in payload.items():
        pair: Optional[Sequence[Any]] = None
        if isinstance(value, Mapping):
            if "lower" in value and "upper" in value:
                pair = [value["lower"], value["upper"]]
            elif "lo" in value and "hi" in value:
                pair = [value["lo"], value["hi"]]
        elif isinstance(value, (list, tuple)):
            pair = value
        if pair is None or len(pair) != 2:
            invalid.append(str(key))
            continue
        lo, hi = coerce_scalar(pair[0]), coerce_scalar(pair[1])
        if not is_number(lo) or not is_number(hi) or float(lo) > float(hi):
            invalid.append(str(key))
            continue
        valid[str(key)] = [float(lo), float(hi)]
    return valid, invalid
def coerce_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            number = float(text)
        except ValueError:
            return value
        return number if math.isfinite(number) else value
    return value
def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
def has_value(metrics: Mapping[str, Any], key: str) -> bool:
    if key not in metrics:
        return False
    value = metrics[key]
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True
def detect_keys(metrics: Mapping[str, Any], group: str) -> List[str]:
    spec = SIGNAL_GROUPS[group]
    found = [key for key in spec["exact"] if has_value(metrics, key)]
    for key in metrics:
        for prefix in spec["prefixes"]:
            if key.startswith(prefix) and has_value(metrics, key):
                found.append(key)
                break
    return sorted(set(found))
def make_item(check: str, status: str, message: str) -> Dict[str, str]:
    return {"check": check, "status": status, "message": message}
def rollup_status(items: Sequence[Mapping[str, Any]]) -> str:
    worst = max((STATUS_RANK.get(str(item.get("status", "PASS")), 0) for item in items), default=0)
    return next(status for status, rank in STATUS_RANK.items() if rank == worst)
def format_float(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"
def check_completeness(
    metrics: Mapping[str, Any],
    ci: Optional[Mapping[str, List[float]]],
    invalid_ci_keys: Sequence[str],
) -> Dict[str, Any]:
    present = [metric for metric in STANDARD_METRICS if has_value(metrics, metric)]
    missing = [metric for metric in STANDARD_METRICS if metric not in present]
    numeric_metrics = sorted(key for key, value in metrics.items() if is_number(value))
    if not present:
        metric_item = make_item("required_metrics", "FAIL", "No standard publication metrics detected.")
    elif missing:
        metric_item = make_item(
            "required_metrics",
            "WARN",
            f"Detected {len(present)}/{len(STANDARD_METRICS)} standard metrics; missing: {', '.join(missing)}.",
        )
    else:
        metric_item = make_item("required_metrics", "PASS", f"All {len(STANDARD_METRICS)} standard metrics are present.")
    if ci is None:
        ci_item = make_item("confidence_intervals", "WARN", "No confidence interval payload provided via --ci.")
        missing_ci = numeric_metrics
    else:
        missing_ci = [key for key in numeric_metrics if key not in ci]
        if missing_ci or invalid_ci_keys:
            parts = []
            if missing_ci:
                parts.append("missing CI for: " + ", ".join(missing_ci))
            if invalid_ci_keys:
                parts.append("invalid CI format for: " + ", ".join(sorted(invalid_ci_keys)))
            ci_item = make_item("confidence_intervals", "WARN", "Confidence interval coverage is incomplete; " + "; ".join(parts) + ".")
        else:
            ci_item = make_item("confidence_intervals", "PASS", f"Confidence intervals supplied for all {len(numeric_metrics)} numeric reported metrics.")
    items = [metric_item, ci_item]
    return {
        "status": rollup_status(items),
        "items": items,
        "present_metrics": present,
        "missing_metrics": missing,
        "ci_covered_metrics": sorted(ci) if ci else [],
        "ci_missing_metrics": missing_ci,
        "ci_invalid_metrics": sorted(invalid_ci_keys),
    }
def check_sample_size(n_train: int, n_test: int, n_features: int, prevalence: float) -> Dict[str, Any]:
    events = n_test * prevalence
    epv = events / float(n_features)
    shrinkage = 1.0 - ((n_features + 2.0) / (2.0 * n_test * prevalence * (1.0 - prevalence)))
    items = [
        make_item("cohort_context", "PASS", f"Training n={n_train}, test n={n_test}, features={n_features}, expected events={format_float(events)}."),
        make_item(
            "epv",
            "WARN" if epv < 10.0 else "PASS",
            f"EPV = {format_float(epv)} using ({n_test} * {format_float(prevalence, 4)}) / {n_features}; "
            + ("below recommended threshold of 10." if epv < 10.0 else "meets recommended threshold of 10."),
        ),
        make_item(
            "riley_shrinkage",
            "WARN" if shrinkage < 0.90 else "PASS",
            f"Riley shrinkage factor = {format_float(shrinkage)}; "
            + ("below recommended threshold of 0.90." if shrinkage < 0.90 else "meets recommended threshold of 0.90."),
        ),
    ]
    return {
        "status": rollup_status(items),
        "items": items,
        "epv": round(epv, 6),
        "riley_shrinkage": round(shrinkage, 6),
        "expected_events": round(events, 6),
    }
def check_calibration(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    present = detect_keys(metrics, "calibration")
    item = make_item(
        "calibration_presence",
        "PASS" if present else "WARN",
        ("Calibration evidence detected via: " + ", ".join(present) + ".")
        if present
        else "No calibration_slope, calibration_intercept, ece, or o_e_ratio detected.",
    )
    return {"status": item["status"], "items": [item], "present_keys": present}
def check_clinical(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    items: List[Dict[str, str]] = []
    ppv = metrics.get("ppv")
    if not is_number(ppv):
        items.append(make_item("screening_ppv", "WARN", "PPV missing; unable to assess screening-context threshold of 0.50."))
    elif float(ppv) < 0.50:
        items.append(make_item("screening_ppv", "FAIL", f"PPV = {format_float(float(ppv))}; below screening-context threshold of 0.50."))
    else:
        items.append(make_item("screening_ppv", "PASS", f"PPV = {format_float(float(ppv))}; meets screening-context threshold of 0.50."))
    sensitivity = metrics.get("sensitivity")
    if not is_number(sensitivity):
        items.append(make_item("diagnosis_sensitivity", "WARN", "Sensitivity missing; unable to assess diagnosis-context threshold of 0.80."))
    elif float(sensitivity) < 0.80:
        items.append(make_item("diagnosis_sensitivity", "FAIL", f"Sensitivity = {format_float(float(sensitivity))}; below diagnosis-context threshold of 0.80."))
    else:
        items.append(make_item("diagnosis_sensitivity", "PASS", f"Sensitivity = {format_float(float(sensitivity))}; meets diagnosis-context threshold of 0.80."))
    dca_present = detect_keys(metrics, "dca")
    dca_message = (
        "DCA-related keys detected (" + ", ".join(dca_present) + "), but journal-grade decision curve adequacy cannot be confirmed from scalar metrics alone."
        if dca_present else
        "Decision curve analysis or net benefit evidence is not detectable from metrics alone."
    )
    items.append(make_item("decision_curve_analysis", "WARN", dca_message))
    return {"status": rollup_status(items), "items": items, "present_dca_keys": dca_present}
def check_tripod(metrics: Mapping[str, Any], ci: Optional[Mapping[str, List[float]]]) -> Dict[str, Any]:
    external = detect_keys(metrics, "external_validation")
    subgroup = detect_keys(metrics, "subgroup")
    fairness = detect_keys(metrics, "fairness")
    uncertainty = detect_keys(metrics, "uncertainty")
    model_card = detect_keys(metrics, "model_card")
    uncertainty_detected = bool(ci) or bool(uncertainty)
    items = [
        make_item("external_validation_note", "PASS" if external else "WARN", "External validation note detected via: " + ", ".join(external) + "." if external else "No external validation note detected."),
        make_item("subgroup_analysis", "PASS" if subgroup else "WARN", "Subgroup analysis signal detected via: " + ", ".join(subgroup) + "." if subgroup else "No subgroup analysis detected."),
        make_item("fairness_bias_assessment", "PASS" if fairness else "WARN", "Fairness or bias assessment signal detected via: " + ", ".join(fairness) + "." if fairness else "No fairness or bias assessment detected."),
        make_item("uncertainty_quantification", "PASS" if uncertainty_detected else "WARN", "Uncertainty quantification detected via confidence intervals and/or explicit uncertainty fields." if uncertainty_detected else "No uncertainty quantification detected."),
        make_item("model_card_intended_use", "PASS" if model_card else "WARN", "Model card or intended use signal detected via: " + ", ".join(model_card) + "." if model_card else "No model card or intended use statement detected."),
    ]
    return {
        "status": rollup_status(items),
        "items": items,
        "detected": {
            "external_validation": external,
            "subgroup_analysis": subgroup,
            "fairness_bias": fairness,
            "uncertainty": uncertainty,
            "model_card_intended_use": model_card,
        },
    }
def check_journal(target_journal: str, metrics: Mapping[str, Any]) -> Dict[str, Any]:
    preset = JOURNAL_PRESETS[target_journal]
    context = {
        "has_calibration": bool(detect_keys(metrics, "calibration")),
        "has_external_validation": bool(detect_keys(metrics, "external_validation")),
        "has_subgroup": bool(detect_keys(metrics, "subgroup")),
        "has_tripod": bool(detect_keys(metrics, "tripod")),
        "has_dca": bool(detect_keys(metrics, "dca")),
        "has_net_benefit": bool(detect_keys(metrics, "net_benefit")),
    }
    items = []
    for rule_id in preset["requirements"]:
        rule = JOURNAL_RULES[rule_id]
        present = bool(context[rule["context_key"]])
        items.append(
            make_item(
                rule_id,
                "PASS" if present else rule["missing_status"],
                f"{rule['label']}; " + (rule["present_message"] if present else rule["missing_message"]),
            )
        )
    return {"status": rollup_status(items), "journal": target_journal, "journal_label": preset["label"], "items": items}
def build_summary(args: argparse.Namespace, metrics: Mapping[str, Any], sections: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for name, section in sections.items():
        if name == "SUMMARY":
            continue
        for item in section.get("items", []):
            counts[str(item.get("status", "PASS"))] += 1
    overall = "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] else "PASS"
    items = [
        make_item("overall", overall, f"Audit completed for {JOURNAL_PRESETS[args.target_journal]['label']}: {counts['FAIL']} FAIL, {counts['WARN']} WARN, {counts['PASS']} PASS."),
        make_item("inputs", "PASS", f"Train n={args.n_train}, test n={args.n_test}, features={args.n_features}, prevalence={format_float(args.prevalence, 4)}."),
        make_item("metric_payload", "PASS", f"Received {len(metrics)} metric fields and {sum(1 for value in metrics.values() if is_number(value))} numeric metric values."),
    ]
    return {"status": overall, "items": items, "counts": counts}
def format_report(report: Mapping[str, Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for section_name in SECTION_ORDER:
        section = report[section_name]
        title = section_name.replace("_", " ")
        lines.extend([title, "=" * len(title), f"Status: {section.get('status', 'PASS')}"])
        for item in section.get("items", []):
            lines.append(f"[{item['status']}] {item['check']}: {item['message']}")
        if section_name == "METRIC_COMPLETENESS":
            lines.append("Present standard metrics: " + (", ".join(section.get("present_metrics", [])) or "none"))
            lines.append("Missing standard metrics: " + (", ".join(section.get("missing_metrics", [])) or "none"))
            lines.append("CI-covered metrics: " + (", ".join(section.get("ci_covered_metrics", [])) or "none"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
def format_json_report(report: Mapping[str, Mapping[str, Any]]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=True)
def main() -> None:
    args = parse_args()
    try:
        metrics = load_metrics(args.metrics)
        ci, invalid_ci_keys = load_ci(args.ci)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    report: Dict[str, Any] = {
        "METRIC_COMPLETENESS": check_completeness(metrics, ci, invalid_ci_keys),
        "SAMPLE_SIZE": check_sample_size(args.n_train, args.n_test, args.n_features, args.prevalence),
        "CALIBRATION": check_calibration(metrics),
        "CLINICAL_FLAGS": check_clinical(metrics),
        "TRIPOD_AI_GAPS": check_tripod(metrics, ci),
        "JOURNAL_SPECIFIC_GAPS": check_journal(args.target_journal, metrics),
    }
    report["SUMMARY"] = build_summary(args, metrics, report)
    ordered = {section_name: report[section_name] for section_name in SECTION_ORDER}
    print(format_json_report(ordered) if args.json else format_report(ordered), end="")
if __name__ == "__main__":
    main()
