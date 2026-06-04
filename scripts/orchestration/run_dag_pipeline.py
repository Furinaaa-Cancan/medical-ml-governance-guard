#!/usr/bin/env python3
"""
[RUNNER — PRIMARY] DAG-based pipeline executor for ml-governance-guard gates.

Called by mlgg_pixel.py and mlgg.py. Not invoked directly by users.

Replaces the hardcoded sequential run_strict_pipeline.py with a declarative
DAG-driven executor that provides:

  - Automatic parallelism within dependency layers
  - Incremental execution (skip gates whose inputs haven't changed)
  - Single-gate and subset re-runs
  - Checkpoint/resume after failures
  - Rich terminal progress output with severity-aware issue display
  - Unified JSON pipeline report

Usage examples:

  # Full strict pipeline
  python run_dag_pipeline.py --request request.json --strict

  # Re-run only failed gates from last checkpoint
  python run_dag_pipeline.py --request request.json --strict --resume

  # Run a single gate (with its dependencies)
  python run_dag_pipeline.py --request request.json --strict --only calibration_dca_gate

  # Run a single gate without dependencies (assumes deps already passed)
  python run_dag_pipeline.py --request request.json --strict --only calibration_dca_gate --no-deps

  # List the DAG structure
  python run_dag_pipeline.py --show-dag

  # Dry-run: validate all inputs without executing gates
  python run_dag_pipeline.py --request request.json --strict --dry-run
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import concurrent.futures
import json
import os
import shlex
import signal
import subprocess
import sys
import time as _time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from _gate_utils import (
    load_json_from_path as load_json,
    resolve_path,
    write_json,
)
from _gate_registry import (
    GATE_REGISTRY,
    GateLayer,
    GateSpec,
    get_execution_layers,
    get_runnable_subset,
    print_dag_summary,
    topological_sort,
    validate_dag,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_REPORT_VERSION = "dag_pipeline_report.v1"
CHECKPOINT_FILE = ".dag_checkpoint.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DAG-based pipeline executor for ml-governance-guard gates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --request request.json --strict
  %(prog)s --request request.json --strict --resume
  %(prog)s --request request.json --strict --only calibration_dca_gate
  %(prog)s --show-dag
  %(prog)s --request request.json --dry-run
        """,
    )

    run_group = parser.add_argument_group("Execution")
    run_group.add_argument("--request", help="Path to request JSON.")
    run_group.add_argument(
        "--evidence-dir", default="evidence",
        help="Directory for gate artifacts and reports (default: evidence).",
    )
    run_group.add_argument(
        "--strict", action="store_true", default=True,
        help="Run all gates in strict mode (default: True for publication-grade).",
    )
    run_group.add_argument(
        "--no-strict", dest="strict", action="store_false",
        help="Run in exploratory mode: warnings stay as warnings, not promoted to failures.",
    )
    run_group.add_argument(
        "--python", default=sys.executable,
        help="Python executable for running gate scripts.",
    )
    run_group.add_argument("--report", help="Pipeline summary report JSON path.")

    subset_group = parser.add_argument_group("Subset execution")
    subset_group.add_argument(
        "--only", nargs="+", metavar="GATE",
        help="Run only these gates (plus dependencies unless --no-deps).",
    )
    subset_group.add_argument(
        "--no-deps", action="store_true",
        help="With --only, skip dependency gates (assume they already passed).",
    )
    subset_group.add_argument(
        "--skip", nargs="+", metavar="GATE",
        help="Skip these gates (and anything that depends on them).",
    )
    subset_group.add_argument(
        "--from-gate", metavar="GATE",
        help="Start execution from this gate (skip all preceding gates).",
    )

    resume_group = parser.add_argument_group("Resume / incremental")
    resume_group.add_argument(
        "--resume", action="store_true",
        help="Resume from last checkpoint, skipping already-passed gates.",
    )
    resume_group.add_argument(
        "--rerun-failed", action="store_true",
        help="Re-run only gates that failed in the last checkpoint.",
    )
    resume_group.add_argument(
        "--force", action="store_true",
        help="Ignore checkpoint and run everything fresh.",
    )

    parallel_group = parser.add_argument_group("Parallelism")
    parallel_group.add_argument(
        "--parallel", action="store_true",
        help="Run independent gates concurrently within each layer.",
    )
    parallel_group.add_argument(
        "--max-workers", type=int, default=4,
        help="Maximum concurrent gate processes (default: 4).",
    )

    mode_group = parser.add_argument_group("Mode")
    mode_group.add_argument(
        "--continue-on-fail", action="store_true",
        help="Continue executing after gate failures (diagnostic mode).",
    )
    mode_group.add_argument(
        "--dry-run", action="store_true",
        help="Validate DAG and input files without running gates.",
    )
    mode_group.add_argument(
        "--show-dag", action="store_true",
        help="Print the DAG structure and exit.",
    )

    triage_group = parser.add_argument_group("Triage — intelligent gate routing")
    triage_group.add_argument(
        "--triage", action="store_true",
        help="Auto-skip gates whose input artifacts are missing (rule-based triage).",
    )
    triage_group.add_argument(
        "--triage-llm", action="store_true",
        help="Enable LLM-assisted triage for ambiguous cases (implies --triage).",
    )
    triage_group.add_argument(
        "--diagnose", action="store_true",
        help="On gate failure, generate LLM-powered actionable fix suggestions.",
    )

    manifest_group = parser.add_argument_group("Manifest comparison")
    manifest_group.add_argument("--compare-manifest", help="Baseline manifest JSON path.")
    manifest_group.add_argument(
        "--allow-missing-compare", action="store_true",
        help="Allow first-run bootstrap without manifest baseline.",
    )

    security_group = parser.add_argument_group("Security")
    security_group.add_argument(
        "--encrypt", action="store_true",
        help="Encrypt evidence JSON files after pipeline completion (AES-256-GCM).",
    )
    security_group.add_argument(
        "--sign-receipt", action="store_true",
        help="Generate HMAC-signed execution receipt for non-repudiation.",
    )
    security_group.add_argument(
        "--secure-cleanup", action="store_true",
        help="Securely delete temporary files after pipeline (zero-fill + unlink).",
    )
    security_group.add_argument(
        "--require-role", metavar="ROLE",
        help="Require the current user to have this RBAC role (admin/operator/auditor/viewer).",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Checkpoint management
# ---------------------------------------------------------------------------

def load_checkpoint(evidence_dir: Path) -> Dict[str, Any]:
    cp_path = evidence_dir / CHECKPOINT_FILE
    if not cp_path.exists():
        return {}
    try:
        # Use load_json (_gate_utils) which enforces the 100MB JSON cap
        # so a corrupted/tampered checkpoint can't OOM the pipeline.
        return load_json(cp_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def save_checkpoint(evidence_dir: Path, state: Dict[str, Any]) -> None:
    write_json(evidence_dir / CHECKPOINT_FILE, state)


# ---------------------------------------------------------------------------
# Gate execution
# ---------------------------------------------------------------------------

try:
    _SUBPROCESS_TIMEOUT = max(60, min(
        int(os.environ.get("MLGG_SUBPROCESS_TIMEOUT", "3600")),
        86400,
    ))
except (ValueError, TypeError):
    _SUBPROCESS_TIMEOUT = 3600


def run_gate_subprocess(
    gate_name: str,
    cmd: List[str],
    report_path: str = "",
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run a single gate as a subprocess and return structured result."""
    t0 = _time.time()
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        exit_code = 2
        stdout = ""
        stderr = f"TIMEOUT: {gate_name} exceeded {_SUBPROCESS_TIMEOUT}s subprocess limit."
    except (OSError, ValueError) as exc:
        exit_code = 2
        stdout = ""
        stderr = f"EXCEPTION: {type(exc).__name__}: {exc}"

    elapsed = _time.time() - t0
    status = "pass" if exit_code == 0 else "fail"

    # Tamper-evident audit log entry
    try:
        from _gate_utils import append_audit_entry
        audit_dir = evidence_dir or (Path(report_path).expanduser().resolve().parent if report_path else None)
        if audit_dir is not None and audit_dir.exists():
            append_audit_entry(
                evidence_dir=audit_dir,
                gate_name=gate_name,
                status=status,
                execution_time=elapsed,
            )
    except Exception:
        pass  # Audit logging is best-effort; never block pipeline

    return {
        "name": gate_name,
        "command": shlex.join(cmd),
        "exit_code": exit_code,
        "status": status,
        "execution_time_seconds": round(elapsed, 3),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "report_path": report_path,
    }


def build_gate_command(
    spec: GateSpec,
    args: argparse.Namespace,
    scripts_dir: Path,
    evidence_dir: Path,
    normalized: Dict[str, Any],
    report_paths: Dict[str, Path],
    split_paths: Dict[str, str],
) -> List[str]:
    """Build the CLI command for a gate based on its spec and the normalized request."""
    cmd: List[str] = [args.python, str(scripts_dir / spec.script)]

    if spec.name == "request_contract_gate":
        cmd.extend(["--request", str(Path(args.request).expanduser().resolve())])
    elif spec.name == "manifest_lock":
        cmd.extend(_build_manifest_cmd(args, normalized, scripts_dir, evidence_dir, report_paths))
        cmd.extend(["--output", str(report_paths[spec.name])])
        if args.compare_manifest:
            cmd.extend(["--compare-with", str(resolve_path(Path.cwd(), args.compare_manifest))])
        return cmd
    elif spec.name in ("publication_gate", "self_critique_gate"):
        cmd.extend(_build_aggregation_cmd(spec.name, report_paths, args))
    elif spec.name == "security_audit_gate":
        cmd.extend(["--evidence-dir", str(evidence_dir)])
    else:
        cmd.extend(_build_standard_gate_cmd(spec, normalized, split_paths, report_paths, evidence_dir=evidence_dir))

    cmd.extend(["--report", str(report_paths[spec.name])])

    if args.strict:
        cmd.append("--strict")

    return cmd


def _build_standard_gate_cmd(
    spec: GateSpec,
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
    report_paths: Dict[str, Path],
    evidence_dir: Optional[Path] = None,
) -> List[str]:
    """Build CLI args for a standard validation gate."""
    cmd: List[str] = []

    # Split file arguments (declared in GateSpec.requires_splits)
    if spec.requires_splits:
        if split_paths.get("train"):
            cmd.extend(["--train", split_paths["train"]])
        if split_paths.get("valid"):
            cmd.extend(["--valid", split_paths["valid"]])
        if split_paths.get("test"):
            cmd.extend(["--test", split_paths["test"]])

    # File path inputs from normalized request
    for req_field, cli_flag in spec.request_inputs.items():
        value = normalized.get(req_field)
        if value is not None:
            cmd.extend([cli_flag, str(value)])

    # String value inputs from normalized request.
    # Skip sentinel values that signal "not applicable" (e.g., cross-sectional
    # data has no time column). Prefix with __ to avoid collision with real column names.
    _SENTINEL_SKIP_VALUES = {"_no_time_column", "__no_time_column"}
    for req_field, cli_flag in spec.value_inputs.items():
        value = normalized.get(req_field)
        if value is not None and str(value) not in _SENTINEL_SKIP_VALUES:
            cmd.extend([cli_flag, str(value)])

    # Report input mappings (cross-gate dependencies)
    for dep_gate, cli_flag in spec.report_inputs.items():
        if dep_gate in report_paths:
            cmd.extend([cli_flag, str(report_paths[dep_gate])])

    # Gate-specific extra arguments (composite/conditional only)
    cmd.extend(_gate_specific_extras(spec.name, normalized, split_paths, evidence_dir=evidence_dir))

    return cmd


def _gate_specific_extras(
    gate_name: str,
    normalized: Dict[str, Any],
    split_paths: Dict[str, str],
    evidence_dir: Optional[Path] = None,
) -> List[str]:
    """Return gate-specific CLI arguments that require composite or conditional logic.

    Simple field→flag mappings are handled by GateSpec.value_inputs in the
    registry. This function only covers cases that need string concatenation,
    conditional presence, or nested field access.
    """
    extras: List[str] = []
    id_col = str(normalized.get("patient_id_col", ""))
    time_col = str(normalized.get("index_time_col", ""))
    valid = split_paths.get("valid", "")

    # Composite --ignore-cols (id_col + time_col concatenation)
    _ignore_cols_gates = {
        "covariate_shift_gate", "definition_variable_guard",
        "feature_lineage_gate", "missingness_policy_gate",
        "distribution_generalization_gate",
    }
    if gate_name in _ignore_cols_gates:
        extras.extend(["--ignore-cols", f"{id_col},{time_col}"])

    # Forward --cross-sectional flag to gates that support it, when the
    # request declares cross_sectional data (e.g., NHANES single-cycle).
    # Gates that then suppress temporal-related warnings:
    #   - definition_variable_guard: skip temporal_spec_missing warning
    #   - split_protocol_gate: skip cross_sectional_data warning (explicit ack)
    _cross_sectional_gates = {"definition_variable_guard", "split_protocol_gate"}
    if gate_name in _cross_sectional_gates and bool(normalized.get("cross_sectional")):
        extras.append("--cross-sectional")

    if gate_name == "cohort_definition_gate":
        # Use train split as input data (not a request field mapping)
        data = split_paths.get("train", "")
        if data:
            extras.extend(["--data", data])

    elif gate_name == "missingness_policy_gate":
        # Pass cohort report if available for codebook-confirmed MNAR
        _cohort_rpt = evidence_dir / "cohort_definition_report.json" if evidence_dir else None
        if _cohort_rpt is not None and _cohort_rpt.is_file():
            extras.extend(["--cohort-report", str(_cohort_rpt)])

    elif gate_name == "tuning_leakage_gate":
        if valid:
            extras.append("--has-valid-split")

    elif gate_name == "shap_interpretability_gate":
        if split_paths.get("train"):
            extras.extend(["--train-data", split_paths["train"]])
        if split_paths.get("test"):
            extras.extend(["--test-data", split_paths["test"]])
        prediction_trace = normalized.get("prediction_trace_file")
        if isinstance(prediction_trace, str) and prediction_trace:
            extras.extend(["--prediction-trace", prediction_trace])

    elif gate_name == "metric_consistency_gate":
        extras.extend(["--required-evaluation-split", "test"])
        eval_metric_path = normalized.get("evaluation_metric_path")
        if isinstance(eval_metric_path, str) and eval_metric_path:
            extras.extend(["--metric-path", eval_metric_path])

    elif gate_name == "evaluation_quality_gate":
        thresholds = normalized.get("thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}
        extras.extend([
            "--min-resamples", str(int(float(thresholds.get("ci_min_resamples", 200)))),
            "--min-baseline-delta", str(float(thresholds.get("min_baseline_delta", 0.0))),
            "--max-ci-width", str(float(thresholds.get("ci_max_width", 0.50))),
        ])
        eval_metric_path = normalized.get("evaluation_metric_path")
        if isinstance(eval_metric_path, str) and eval_metric_path:
            extras.extend(["--metric-path", eval_metric_path])

    elif gate_name == "permutation_significance_gate":
        thresholds = normalized.get("thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}
        extras.extend([
            "--alpha", str(float(thresholds.get("alpha", 0.01))),
            "--min-delta", str(float(thresholds.get("min_delta", 0.03))),
        ])

    return extras


def _build_manifest_cmd(
    args: argparse.Namespace,
    normalized: Dict[str, Any],
    scripts_dir: Path,
    evidence_dir: Path,
    report_paths: Dict[str, Path],
) -> List[str]:
    """Build manifest_lock.py --inputs list."""
    cmd: List[str] = ["--inputs"]

    split_paths = normalized.get("split_paths", {})
    if isinstance(split_paths, dict):
        for key in ("train", "valid", "test"):
            val = split_paths.get(key)
            if isinstance(val, str) and val:
                cmd.append(val)

    path_fields = [
        "phenotype_definition_spec", "feature_lineage_spec", "split_protocol_spec",
        "imbalance_policy_spec", "missingness_policy_spec", "tuning_protocol_spec",
        "reporting_bias_checklist_spec", "performance_policy_spec", "feature_group_spec",
        "model_selection_report_file", "feature_engineering_report_file",
        "distribution_report_file", "robustness_report_file",
        "seed_sensitivity_report_file", "evaluation_report_file",
        "prediction_trace_file", "external_cohort_spec",
        "external_validation_report_file", "ci_matrix_report_file",
        "permutation_null_metrics_file", "execution_attestation_spec",
    ]
    for field in path_fields:
        val = normalized.get(field)
        if isinstance(val, str) and val:
            cmd.append(val)

    cmd.append(str(Path(args.request).expanduser().resolve()))

    for name in sorted(GATE_REGISTRY.keys()):
        spec = GATE_REGISTRY[name]
        cmd.append(str(scripts_dir / spec.script))

    cmd.append(str(scripts_dir / "orchestration/run_dag_pipeline.py"))

    return cmd


def _build_aggregation_cmd(
    gate_name: str,
    report_paths: Dict[str, Path],
    args: argparse.Namespace,
) -> List[str]:
    """Build CLI args for publication_gate and self_critique_gate.

    The flag mapping is read from GateSpec.aggregation_flag in the registry
    so that new gates are automatically included without manual dict updates.
    """
    cmd: List[str] = []

    target_spec = GATE_REGISTRY.get(gate_name)
    for dep_name, spec in GATE_REGISTRY.items():
        if dep_name == gate_name:
            continue
        flag = spec.aggregation_flag
        if not flag:
            continue
        # For gates with explicit dependency lists, only forward reports
        # from declared deps.  self_critique_gate also needs peers
        # registered after it (e.g. security_audit_gate) that share
        # the same layer, so we allow same-layer gates through.
        if target_spec and dep_name not in target_spec.depends_on:
            dep_spec = GATE_REGISTRY.get(dep_name)
            if not dep_spec or dep_spec.layer != target_spec.layer:
                continue
        if dep_name in report_paths and report_paths[dep_name].exists():
            cmd.extend([flag, str(report_paths[dep_name])])

    if gate_name == "self_critique_gate":
        cmd.extend(["--min-score", "95"])
        if getattr(args, "allow_missing_compare", False):
            cmd.append("--allow-missing-comparison")

    return cmd


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def print_layer_header(layer_idx: int, gate_names: List[str], parallel: bool) -> None:
    layer_name = GateLayer(layer_idx).name if layer_idx < len(GateLayer) else f"LAYER_{layer_idx}"
    mode = "parallel" if parallel and len(gate_names) > 1 else "sequential"
    color = _use_color()
    if color:
        print(f"\n\033[1;36m{'─' * 60}\033[0m")
        print(f"\033[1;36m  Layer {layer_idx} ({layer_name}) [{mode}] — {len(gate_names)} gate(s)\033[0m")
        print(f"\033[1;36m{'─' * 60}\033[0m")
    else:
        print(f"\n{'─' * 60}")
        print(f"  Layer {layer_idx} ({layer_name}) [{mode}] — {len(gate_names)} gate(s)")
        print(f"{'─' * 60}")


def print_gate_start(gate_name: str, cmd: List[str]) -> None:
    color = _use_color()
    if color:
        print(f"\n  \033[1m▶ {gate_name}\033[0m")
    else:
        print(f"\n  > {gate_name}")
    print(f"    $ {shlex.join(cmd)}")


def print_gate_result(result: Dict[str, Any]) -> None:
    color = _use_color()
    name = result["name"]
    status = result["status"]
    elapsed = result.get("execution_time_seconds", 0)

    if color:
        if status == "pass":
            icon = "\033[32m✓\033[0m"
        elif status == "skip":
            icon = "\033[33m⊘\033[0m"
        else:
            icon = "\033[1;31m✗\033[0m"
        print(f"    {icon} {name}  ({elapsed:.1f}s)")
    else:
        icon = "OK" if status == "pass" else ("SKIP" if status == "skip" else "FAIL")
        print(f"    [{icon}] {name}  ({elapsed:.1f}s)")

    stderr_tail = result.get("stderr_tail", "").strip()
    if status == "fail" and stderr_tail:
        for line in stderr_tail.split("\n")[-5:]:
            print(f"      {line}")

    # Auto-explain: show top failures with remediation from the gate report
    if status == "fail":
        report_path = result.get("report_path", "")
        if report_path and Path(report_path).exists():
            try:
                # Size-capped load (load_json enforces MAX_JSON_FILE_SIZE).
                # Prevents a runaway / malicious gate report from OOM-ing
                # the orchestrator when summarizing failures.
                _rpt_data = load_json(Path(report_path))
                _failures = _rpt_data.get("failures", [])
                for _f in _failures[:3]:
                    _code = _f.get("code", "?")
                    _msg = _f.get("message", "")[:100]
                    _rem = _f.get("remediation", "")
                    print(f"      \u2192 {_code}: {_msg}")
                    if _rem:
                        print(f"        Fix: {_rem[:120]}")
                if len(_failures) > 3:
                    print(f"      ... and {len(_failures) - 3} more failure(s)")
            except Exception:
                pass


def print_pipeline_summary(steps: List[Dict[str, Any]], elapsed: float) -> None:
    color = _use_color()
    passed = sum(1 for s in steps if s["status"] == "pass")
    failed = sum(1 for s in steps if s["status"] == "fail")
    skipped = sum(1 for s in steps if s["status"] == "skip")
    total = len(steps)

    print(f"\n{'═' * 60}")
    if color:
        status_str = (
            "\033[1;32mALL PASSED\033[0m" if failed == 0
            else f"\033[1;31m{failed} FAILED\033[0m"
        )
        print(f"  Pipeline: {status_str}  ({passed}/{total} passed, {skipped} skipped, {elapsed:.1f}s)")
    else:
        status_str = "ALL PASSED" if failed == 0 else f"{failed} FAILED"
        print(f"  Pipeline: {status_str}  ({passed}/{total} passed, {skipped} skipped, {elapsed:.1f}s)")
    print(f"{'═' * 60}")

    if failed > 0:
        print("\n  Failed gates:")
        for s in steps:
            if s["status"] == "fail":
                print(f"    ✗ {s['name']}")

    timed = sorted(
        [s for s in steps if s.get("execution_time_seconds", 0) > 0],
        key=lambda s: s["execution_time_seconds"],
        reverse=True,
    )
    if timed:
        print("\n  Slowest gates:")
        for s in timed[:5]:
            print(f"    {s['execution_time_seconds']:7.1f}s  {s['name']}")
    print()


def _print_prioritized_issues(
    steps: List[Dict[str, Any]],
    evidence_dir: Path,
) -> None:
    """Aggregate issues from all gate reports and print a priority-sorted list."""
    severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    all_issues: List[Dict[str, Any]] = []

    for step in steps:
        if step.get("status") not in ("fail", "pass"):
            continue
        report_path = step.get("report_path", "")
        if not report_path:
            continue
        rp = Path(report_path)
        if not rp.exists():
            continue
        try:
            # Size-capped load — same rationale as above.
            report = load_json(rp)
            for issue in report.get("issues", []):
                sev = issue.get("severity", "info")
                if sev in ("critical", "error", "warning"):
                    all_issues.append({
                        "gate": step["name"],
                        "severity": sev,
                        "code": issue.get("code", ""),
                        "message": issue.get("message", ""),
                        "remediation": issue.get("remediation", ""),
                    })
        except (json.JSONDecodeError, OSError):
            continue

    if not all_issues:
        return

    all_issues.sort(key=lambda i: severity_order.get(i["severity"], 99))

    color = _use_color()
    sev_colors = {
        "critical": "\033[1;31m",
        "error": "\033[31m",
        "warning": "\033[33m",
    }
    reset = "\033[0m" if color else ""

    print(f"\n{'─' * 60}")
    print("  PRIORITIZED FIX LIST")
    print(f"{'─' * 60}")
    for i, issue in enumerate(all_issues, 1):
        sev = issue["severity"].upper()
        gate = issue["gate"]
        msg = issue["message"]
        if color:
            sev_c = sev_colors.get(issue["severity"], "")
            print(f"  {i:2d}. {sev_c}[{sev}]{reset} {gate}: {msg}")
        else:
            print(f"  {i:2d}. [{sev}] {gate}: {msg}")
        if issue["remediation"]:
            print(f"      Fix: {issue['remediation']}")
    print(f"{'─' * 60}")
    crit = sum(1 for i in all_issues if i["severity"] == "critical")
    err = sum(1 for i in all_issues if i["severity"] == "error")
    warn = sum(1 for i in all_issues if i["severity"] == "warning")
    print(f"  Total: {crit} critical, {err} error, {warn} warning")
    print("  Fix critical issues first, then errors.\n")


# ---------------------------------------------------------------------------
# Main execution engine
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    if args.show_dag:
        dag_errors = validate_dag()
        if dag_errors:
            for err in dag_errors:
                print(f"[DAG ERROR] {err}", file=sys.stderr)
            return 2
        print_dag_summary()
        return 0

    if not args.request:
        print("[FAIL] --request is required.", file=sys.stderr)
        return 2

    # Run-binding (P0.1b): issue ONE run_id for the whole pipeline and export it
    # so every gate subprocess stamps the same id into its report envelope.
    # publication_gate's P0.1a check then fails closed on a mixed-run set.
    # Respect an externally-pinned id (outer orchestrator / test) via setdefault.
    run_id = os.environ.setdefault("MLGG_RUN_ID", uuid.uuid4().hex)
    print(f"[RUN] run_id={run_id}")

    # RBAC role check (optional)
    if getattr(args, "require_role", None):
        try:
            from _security import AccessControl, get_current_user, SecurityError as _SE
            ac = AccessControl()
            user = get_current_user()
            ac.require_permission(user, "pipeline.run")
            print(f"[RBAC] User '{user}' authorized (role: {ac.get_role(user)})")
        except _SE as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        except ImportError:
            print("[WARN] _security module not available; skipping RBAC check.", file=sys.stderr)

    if not args.strict:
        print(
            "[INFO] Running in exploratory mode (--no-strict). "
            "Warnings will not be promoted to failures. "
            "Use --strict (default) for publication-grade validation.",
            file=sys.stderr,
        )

    request_path = Path(args.request).expanduser().resolve()
    if not request_path.exists():
        print(f"[FAIL] Request file not found: {request_path}", file=sys.stderr)
        return 2

    scripts_dir = Path(__file__).resolve().parent.parent
    cwd = Path.cwd()
    evidence_dir = resolve_path(cwd, args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Graceful shutdown on SIGINT/SIGTERM — save checkpoint before exit
    _interrupt_received = False

    def _handle_interrupt(signum: int, frame: Any) -> None:
        nonlocal _interrupt_received
        if _interrupt_received:
            sys.exit(2)  # Second signal → force exit
        _interrupt_received = True
        sig_name = signal.Signals(signum).name
        print(f"\n[{sig_name}] Saving checkpoint and shutting down...", file=sys.stderr)

    signal.signal(signal.SIGINT, _handle_interrupt)
    signal.signal(signal.SIGTERM, _handle_interrupt)

    # Validate DAG
    dag_errors = validate_dag()
    if dag_errors:
        for err in dag_errors:
            print(f"[DAG ERROR] {err}", file=sys.stderr)
        return 2

    # Step 1: Run request_contract_gate to get normalized request
    report_paths: Dict[str, Path] = {}
    for name, spec in GATE_REGISTRY.items():
        if spec.report_output:
            report_paths[name] = evidence_dir / spec.report_output

    request_cmd = [
        args.python,
        str(scripts_dir / "gates/request_contract_gate.py"),
        "--request", str(request_path),
        "--report", str(report_paths["request_contract_gate"]),
    ]
    if args.strict:
        request_cmd.append("--strict")

    steps: List[Dict[str, Any]] = []
    pipeline_t0 = _time.time()

    print_gate_start("request_contract_gate", request_cmd)
    result = run_gate_subprocess(
        "request_contract_gate", request_cmd,
        report_path=str(report_paths["request_contract_gate"]),
        evidence_dir=evidence_dir,
    )
    steps.append(result)
    print_gate_result(result)

    if result["exit_code"] != 0:
        print("[FAIL] request_contract_gate failed. Cannot proceed.", file=sys.stderr)
        return _finalize(args, evidence_dir, steps, False, pipeline_t0)

    # Load normalized request
    request_report = load_json(report_paths["request_contract_gate"])
    normalized = request_report.get("normalized_request", {})
    if not isinstance(normalized, dict):
        print("[FAIL] request_contract_report missing normalized_request.", file=sys.stderr)
        return _finalize(args, evidence_dir, steps, False, pipeline_t0)

    claim_tier = str(normalized.get("claim_tier_target", ""))
    _ALLOWED_STRICT_TIERS = {"publication-grade", "leakage-audited"}
    if claim_tier not in _ALLOWED_STRICT_TIERS and args.strict:
        print(
            f"[FAIL] Strict mode requires claim_tier_target in {sorted(_ALLOWED_STRICT_TIERS)} (got: {claim_tier!r}).",
            file=sys.stderr,
        )
        return _finalize(args, evidence_dir, steps, False, pipeline_t0)
    if claim_tier not in _ALLOWED_STRICT_TIERS:
        print(
            f"[INFO] Exploratory mode: claim_tier_target={claim_tier!r} "
            f"(publication-grade or leakage-audited required for --strict).",
            file=sys.stderr,
        )

    split_paths_raw = normalized.get("split_paths", {})
    split_paths: Dict[str, str] = {}
    if isinstance(split_paths_raw, dict):
        for key in ("train", "valid", "test"):
            val = split_paths_raw.get(key)
            if isinstance(val, str) and val:
                split_paths[key] = val

    # Load checkpoint for resume
    checkpoint = load_checkpoint(evidence_dir) if (args.resume or args.rerun_failed) and not args.force else {}
    passed_gates: Set[str] = set(checkpoint.get("passed_gates", []))

    # Validate checkpoint: remove gates whose report files are missing
    if passed_gates:
        invalidated: List[str] = []
        for pg in sorted(passed_gates):
            if pg in report_paths and not report_paths[pg].exists():
                invalidated.append(pg)
        if invalidated:
            print(f"[WARN] Checkpoint reports missing for: {', '.join(invalidated)}. "
                  f"These gates will be re-run.", file=sys.stderr)
            passed_gates -= set(invalidated)

    # Determine which gates to run
    all_gates = topological_sort()
    gates_to_run = _compute_gates_to_run(args, all_gates, passed_gates)

    # Triage: intelligently skip gates based on project characteristics.
    # When enabled, triage subsumes the legacy auto-skip logic below.
    _triage_active = getattr(args, "triage", False) or getattr(args, "triage_llm", False)
    if _triage_active:
        try:
            from triage import triage_gates as _triage
            use_llm = getattr(args, "triage_llm", False)
            triage_skip = _triage(normalized, split_paths, use_llm=use_llm)
            if triage_skip:
                gates_to_run = [g for g in gates_to_run if g not in triage_skip]
        except ImportError:
            print("[WARN] triage module not found, falling back to legacy auto-skip.", file=sys.stderr)
            _triage_active = False

    # Auto-skip gates that require a test split when none exists.
    # These gates declare --test required=True or need test-split artifacts;
    # without a test set, they crash on argparse or produce meaningless results.
    #
    # Triage handles most of this (it skips the non-mandatory members of this
    # set), so when triage is active we only need to cover the MANDATORY gates
    # that triage forces to "run" but which still cannot execute without --test.
    # split_protocol_gate is mandatory AND declares --test required=True, so
    # under triage it would otherwise reach the command builder, which omits
    # --test when absent, causing an argparse error (exit 2) — a hard crash
    # for what is advertised as a safe intelligent skip. We must auto-skip it.
    if "test" not in split_paths:
        if _triage_active:
            # Triage already skipped the optional no-test gates; only the
            # mandatory-but-test-required gates need an explicit carve-out here.
            _no_test_gates = {
                "split_protocol_gate",   # mandatory; --test required=True → would crash
            }
        else:
            _no_test_gates = {
                "split_protocol_gate",       # validates train/valid/test consistency
                "covariate_shift_gate",      # detects train→test distribution shift
                "imbalance_policy_gate",     # checks class balance across splits
                "missingness_policy_gate",   # checks missingness across splits
                "distribution_generalization_gate",  # JSD/classifier shift on test
                "shap_interpretability_gate",  # SHAP explanations on test data
                "robustness_gate",           # time-slice/group robustness on test
            }
        _auto_skipped = sorted(g for g in gates_to_run if g in _no_test_gates)
        if _auto_skipped:
            print(f"[INFO] No test split — auto-skipping {len(_auto_skipped)} gate(s): "
                  f"{', '.join(_auto_skipped)}", file=sys.stderr)
            gates_to_run = [g for g in gates_to_run if g not in _no_test_gates]

    if args.dry_run:
        print("\n[DRY-RUN] Would execute these gates:")
        for g in gates_to_run:
            spec = GATE_REGISTRY.get(g)
            if spec:
                print(f"  Layer {spec.layer.value}: {g}")
                steps.append({
                    "name": g, "command": "(dry-run)", "exit_code": -1,
                    "status": "skip", "execution_time_seconds": 0,
                    "stdout_tail": "", "stderr_tail": "dry-run: not executed",
                    "report_path": "",
                })
        return _finalize(args, evidence_dir, steps, True, pipeline_t0)

    # Execute gates layer by layer
    had_failure = False
    continue_on_fail = bool(args.continue_on_fail)
    newly_passed: Set[str] = {"request_contract_gate"}  # Already passed above

    execution_layers = get_execution_layers()
    for layer_idx, layer_gates in execution_layers:
        if _interrupt_received:
            print("\n[INTERRUPT] Saving progress and exiting...", file=sys.stderr)
            _save_progress(evidence_dir, passed_gates | newly_passed, steps)
            return _finalize(args, evidence_dir, steps, False, pipeline_t0)

        runnable_in_layer = [g for g in layer_gates if g in gates_to_run and g != "request_contract_gate"]
        if not runnable_in_layer:
            continue

        # Check if all dependencies have passed
        # In continue-on-fail mode, accept dependency reports written
        # during this pipeline run (mtime within threshold).
        _STALE_REPORT_SECONDS = 28800  # 8 hours — covers long-running pipelines
        def _dep_report_current(dep_name: str) -> bool:
            if dep_name not in GATE_REGISTRY:
                return True
            rp = evidence_dir / GATE_REGISTRY[dep_name].report_output
            if not rp.exists():
                return False
            return (_time.time() - rp.stat().st_mtime) < _STALE_REPORT_SECONDS

        blocked: List[str] = []
        ready: List[str] = []
        for gate_name in runnable_in_layer:
            spec = GATE_REGISTRY[gate_name]
            if continue_on_fail:
                deps_met = all(
                    (d not in gates_to_run)
                    or (d in passed_gates or d in newly_passed)
                    or _dep_report_current(d)
                    for d in spec.depends_on
                )
            else:
                deps_met = all(
                    (d in passed_gates or d in newly_passed or d not in gates_to_run)
                    and (d not in gates_to_run
                         or (evidence_dir / GATE_REGISTRY[d].report_output).exists()
                         if d in GATE_REGISTRY else True)
                    for d in spec.depends_on
                )
            if deps_met:
                ready.append(gate_name)
            else:
                blocked.append(gate_name)

        if blocked:
            for bg in blocked:
                steps.append({
                    "name": bg, "command": "", "exit_code": -1,
                    "status": "skip", "execution_time_seconds": 0,
                    "stdout_tail": "", "stderr_tail": "Skipped: dependency not met",
                    "report_path": "",
                })

        if not ready:
            continue

        use_parallel = args.parallel and len(ready) > 1
        print_layer_header(layer_idx, ready, use_parallel)

        if use_parallel:
            layer_results = _run_parallel(
                ready, args, scripts_dir, evidence_dir, normalized,
                report_paths, split_paths, args.max_workers,
            )
        else:
            layer_results = _run_sequential(
                ready, args, scripts_dir, evidence_dir, normalized,
                report_paths, split_paths,
            )

        for r in layer_results:
            steps.append(r)
            print_gate_result(r)
            if r["status"] == "pass":
                newly_passed.add(r["name"])
            elif r["status"] == "fail":
                had_failure = True
            # Save checkpoint after each gate to minimize data loss on SIGINT
            _save_progress(evidence_dir, passed_gates | newly_passed, steps)
            if r["status"] == "fail":
                if getattr(args, "diagnose", False):
                    try:
                        from failure_diagnosis import diagnose_failure
                        rp = report_paths.get(r["name"])
                        if rp:
                            diagnose_failure(r["name"], rp, normalized)
                    except ImportError:
                        pass
                if not continue_on_fail:
                    return _finalize(args, evidence_dir, steps, False, pipeline_t0)

    # Save final checkpoint
    all_passed = passed_gates | newly_passed
    _save_progress(evidence_dir, all_passed, steps)

    success = not had_failure
    return _finalize(args, evidence_dir, steps, success, pipeline_t0)


def _compute_gates_to_run(
    args: argparse.Namespace,
    all_gates: List[str],
    passed_gates: Set[str],
) -> List[str]:
    """Compute which gates should be executed based on CLI flags."""
    if args.only:
        include_deps = not args.no_deps
        return get_runnable_subset(args.only, include_dependencies=include_deps)

    if args.rerun_failed:
        return [g for g in all_gates if g not in passed_gates]

    if args.resume:
        return [g for g in all_gates if g not in passed_gates]

    gates = list(all_gates)

    if args.from_gate:
        try:
            idx = gates.index(args.from_gate)
            gates = gates[idx:]
        except ValueError:
            print(f"[WARN] --from-gate '{args.from_gate}' not found, running all.", file=sys.stderr)

    if args.skip:
        skip_set = set(args.skip)
        # Also skip anything that transitively depends on skipped gates
        from _gate_registry import get_dependents
        to_skip: Set[str] = set()
        queue = list(skip_set)
        while queue:
            current = queue.pop(0)
            if current in to_skip:
                continue
            to_skip.add(current)
            for dep in get_dependents(current):
                if dep not in to_skip:
                    queue.append(dep)
        gates = [g for g in gates if g not in to_skip]

    return gates


def _run_sequential(
    gate_names: List[str],
    args: argparse.Namespace,
    scripts_dir: Path,
    evidence_dir: Path,
    normalized: Dict[str, Any],
    report_paths: Dict[str, Path],
    split_paths: Dict[str, str],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    failed = False
    for i, gate_name in enumerate(gate_names):
        if failed:
            results.append({
                "name": gate_name, "command": "", "exit_code": -1,
                "status": "skip", "execution_time_seconds": 0,
                "stdout_tail": "", "stderr_tail": "Skipped: earlier gate in layer failed",
                "report_path": "",
            })
            continue
        spec = GATE_REGISTRY[gate_name]
        cmd = build_gate_command(spec, args, scripts_dir, evidence_dir, normalized, report_paths, split_paths)
        print_gate_start(gate_name, cmd)
        result = run_gate_subprocess(
            gate_name, cmd,
            report_path=str(report_paths.get(gate_name, "")),
            evidence_dir=evidence_dir,
        )
        results.append(result)
        if result["exit_code"] != 0 and not args.continue_on_fail:
            failed = True
    return results


def _run_parallel(
    gate_names: List[str],
    args: argparse.Namespace,
    scripts_dir: Path,
    evidence_dir: Path,
    normalized: Dict[str, Any],
    report_paths: Dict[str, Path],
    split_paths: Dict[str, str],
    max_workers: int,
) -> List[Dict[str, Any]]:
    tasks: List[Tuple[str, List[str], str]] = []
    for gate_name in gate_names:
        spec = GATE_REGISTRY[gate_name]
        cmd = build_gate_command(spec, args, scripts_dir, evidence_dir, normalized, report_paths, split_paths)
        tasks.append((gate_name, cmd, str(report_paths.get(gate_name, ""))))

    results: List[Dict[str, Any]] = [{} for _ in range(len(tasks))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        future_map = {
            pool.submit(
                run_gate_subprocess, name, cmd,
                report_path=rpath, evidence_dir=evidence_dir,
            ): i
            for i, (name, cmd, rpath) in enumerate(tasks)
        }
        for future in concurrent.futures.as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                name = tasks[idx][0]
                results[idx] = {
                    "name": name, "command": shlex.join(tasks[idx][1]),
                    "exit_code": 2, "status": "fail", "execution_time_seconds": 0,
                    "stdout_tail": "", "stderr_tail": f"EXCEPTION in parallel runner: {exc}",
                    "report_path": tasks[idx][2],
                }

    return results


def _save_progress(
    evidence_dir: Path,
    passed_gates: Set[str],
    steps: List[Dict[str, Any]],
) -> None:
    save_checkpoint(evidence_dir, {
        "passed_gates": sorted(passed_gates),
        "last_run_utc": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "step_summary": [
            {"name": s["name"], "status": s["status"]}
            for s in steps
        ],
    })


def _finalize(
    args: argparse.Namespace,
    evidence_dir: Path,
    steps: List[Dict[str, Any]],
    success: bool,
    pipeline_t0: float,
) -> int:
    elapsed = _time.time() - pipeline_t0

    print_pipeline_summary(steps, elapsed)

    # Aggregate issues from all gate reports, sorted by severity
    _print_prioritized_issues(steps, evidence_dir)

    summary = {
        "contract_version": PIPELINE_REPORT_VERSION,
        "status": "pass" if success else "fail",
        "strict_mode": bool(args.strict),
        "diagnostic_only": bool(args.continue_on_fail),
        "publication_eligible": bool(args.strict and not args.continue_on_fail and success),
        "failure_count": sum(1 for s in steps if s.get("status") == "fail"),
        "pass_count": sum(1 for s in steps if s.get("status") == "pass"),
        "skip_count": sum(1 for s in steps if s.get("status") == "skip"),
        "total_execution_time_seconds": round(elapsed, 3),
        "steps": steps,
        "evidence_dir": str(evidence_dir),
    }

    out_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else (evidence_dir / "dag_pipeline_report.json")
    )
    write_json(out_path, summary)
    print(f"Pipeline report: {out_path}")

    # --- Security post-processing ---
    if getattr(args, "sign_receipt", False):
        try:
            from _security import sign_execution_receipt
            gate_results = {
                s["name"]: s.get("status", "unknown")
                for s in steps if "name" in s
            }
            receipt_path = sign_execution_receipt(
                evidence_dir, gate_results,
                "pass" if success else "fail",
            )
            print(f"Execution receipt: {receipt_path}")
        except Exception as exc:
            print(f"[WARN] Failed to sign execution receipt: {exc}", file=sys.stderr)

    if getattr(args, "encrypt", False):
        try:
            from _security import encrypt_file
            enc_count = 0
            for fpath in sorted(evidence_dir.glob("*.json")):
                if fpath.is_file() and not fpath.name.startswith("."):
                    encrypt_file(fpath)
                    enc_count += 1
            print(f"Encrypted {enc_count} evidence file(s) in {evidence_dir}")
        except Exception as exc:
            print(f"[WARN] Failed to encrypt evidence: {exc}", file=sys.stderr)

    if getattr(args, "secure_cleanup", False):
        try:
            from _security import secure_cleanup_dir
            cleaned = secure_cleanup_dir(evidence_dir, "*.tmp")
            cleaned += secure_cleanup_dir(evidence_dir, "*.log")
            if cleaned:
                print(f"Securely deleted {cleaned} temporary file(s)")
        except Exception as exc:
            print(f"[WARN] Failed to secure-cleanup: {exc}", file=sys.stderr)

    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
