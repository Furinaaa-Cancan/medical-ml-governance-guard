#!/usr/bin/env python3
"""
Record a test session entry to session_log.md from evidence directory.

Reads existing reports (user_summary.json, dag_pipeline_report.json,
onboarding_report.json, evaluation_report.json) and appends a structured
Markdown entry to evidence/session_log.md.

Usage:
    python3 scripts/reporting/record_session.py \
      --evidence-dir /tmp/mlgg_nhanes/evidence \
      --intent "Test NHANES diabetes dataset end-to-end" \
      --notes "First clean run, 16/33 gates pass"
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file, return None if missing or invalid."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _extract_dataset(onboarding: Optional[Dict], evidence_dir: Path) -> str:
    """Extract dataset name and row count from onboarding report or request.json."""
    if onboarding:
        for step in onboarding.get("steps", []):
            cmd = step.get("command", "")
            # Look for --input-csv or --input in split/onboarding commands
            for flag in ("--input-csv", "--input"):
                if flag in cmd:
                    parts = cmd.split()
                    for i, p in enumerate(parts):
                        if p == flag and i + 1 < len(parts):
                            csv_path = parts[i + 1]
                            name = Path(csv_path).name
                            split = _load_json(evidence_dir / "split_report.json")
                            if split:
                                total = sum(
                                    s.get("rows", 0)
                                    for s in split.get("splits", {}).values()
                                    if isinstance(s, dict)
                                )
                                return f"{name} ({total:,} rows)" if total else name
                            return name

    # Fallback: try request.json
    configs_dir = evidence_dir.parent / "configs"
    request = _load_json(configs_dir / "request.json")
    if request:
        return request.get("study_id", "unknown dataset")

    return "unknown dataset"


def _extract_command(onboarding: Optional[Dict]) -> str:
    """Extract the top-level invocation command."""
    if not onboarding:
        return "(not recorded)"
    # Check for copy_ready_commands (has the canonical command)
    crc = onboarding.get("copy_ready_commands", {})
    if isinstance(crc, dict) and "workflow_bootstrap" in crc:
        cmd = crc["workflow_bootstrap"]
        # Trim absolute paths for readability
        parts = cmd.split()
        for i, p in enumerate(parts):
            if "mlgg" in p.lower():
                return " ".join(parts[i:])
    # Fallback: scan steps for onboarding/mlgg command
    for step in onboarding.get("steps", []):
        cmd = step.get("command", "")
        if "onboarding" in cmd.lower() or "mlgg" in cmd.lower():
            parts = cmd.split()
            for i, p in enumerate(parts):
                if "mlgg" in p.lower() or "onboarding" in p.lower():
                    return " ".join(parts[i:])
    return "(not recorded)"


def _format_metrics_table(metrics: Dict[str, Any]) -> str:
    """Format key metrics as a Markdown table."""
    keys = ["roc_auc", "pr_auc", "sensitivity", "specificity", "ppv", "npv", "mcc", "brier", "f1"]
    rows = []
    for k in keys:
        v = metrics.get(k)
        if isinstance(v, (int, float)):
            rows.append(f"| {k} | {v:.4f} |")
    if not rows:
        return "*No metrics available*"
    return "| Metric | Value |\n|--------|-------|\n" + "\n".join(rows)


def _format_failed_gates(dag: Optional[Dict]) -> str:
    """Format failed gates as a bullet list."""
    if not dag:
        return "*No DAG report available*"
    lines = []
    for step in dag.get("steps", []):
        if step.get("status") == "fail":
            name = step.get("name", "?")
            # Try to get failure reason from the gate report
            rp = step.get("report_path")
            reason = ""
            if rp:
                report = _load_json(Path(rp))
                if report:
                    failures = report.get("failures", [])
                    warnings = report.get("warnings", [])
                    if failures:
                        reason = failures[0].get("code", "")
                    elif warnings:
                        reason = f"warning: {warnings[0].get('code', '')}"
                    # Check for peer review context
                    peer = report.get("peer_review_context", [])
                    if peer:
                        reason += f" | {len(peer)} NC paper citations"
            suffix = f" ({reason})" if reason else ""
            lines.append(f"- `{name}`{suffix}")
    return "\n".join(lines) if lines else "*No failures*"


def _format_onboarding_steps(onboarding: Optional[Dict]) -> str:
    """Format onboarding step results."""
    if not onboarding:
        return ""
    lines = []
    for step in onboarding.get("steps", []):
        marker = "pass" if step.get("status") == "pass" else "FAIL"
        lines.append(f"  {marker}: {step.get('name', '?')}")
    return "\n".join(lines)


def build_entry(evidence_dir: Path, intent: str, notes: str) -> str:
    """Build a Markdown session log entry from evidence files."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    user_summary = _load_json(evidence_dir / "user_summary.json")
    dag = _load_json(evidence_dir / "dag_pipeline_report.json")
    # Onboarding report lives at project root, not evidence/
    project_root = evidence_dir.parent
    onboarding = (
        _load_json(evidence_dir / "onboarding_report.json")
        or _load_json(project_root / "onboarding_report.json")
        or _load_json(project_root / "report.json")
    )
    evaluation = _load_json(evidence_dir / "evaluation_report.json")

    # Run ID
    run_id = "unknown"
    if onboarding:
        run_id = onboarding.get("run_id", "unknown")
    elif user_summary:
        run_id = user_summary.get("run_id", "unknown")

    # Dataset
    dataset = _extract_dataset(onboarding, evidence_dir)

    # Command
    command = _extract_command(onboarding)

    # Overall status
    status = "unknown"
    if onboarding:
        status = onboarding.get("status", "unknown")

    # Model
    model = "unknown"
    if user_summary:
        model = user_summary.get("selected_model_id", "unknown")
    if model == "unknown" and evaluation:
        model = evaluation.get("model_id", "unknown")

    # DAG counts
    pass_count = dag.get("pass_count", 0) if dag else 0
    fail_count = dag.get("failure_count", 0) if dag else 0
    skip_count = dag.get("skip_count", 0) if dag else 0

    # Metrics
    metrics = {}
    if evaluation:
        metrics = evaluation.get("metrics", {})
    elif user_summary:
        metrics = user_summary.get("test_metrics", {})

    # Build entry
    lines = [
        "",
        "---",
        "",
        f"## Session {now}",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Dataset**: {dataset}",
        f"- **Intent**: {intent}",
        f"- **Command**: `{command}`",
        "",
        "### Result",
        f"- **Status**: {status}",
        f"- **Model**: `{model}`",
        f"- **DAG**: {pass_count} pass / {fail_count} fail / {skip_count} skip",
        "",
        "### Key Metrics (test)",
        _format_metrics_table(metrics),
        "",
        "### Failed Gates",
        _format_failed_gates(dag),
        "",
    ]

    if notes:
        lines.extend(["### Notes", notes, ""])

    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append a session log entry from evidence directory.",
    )
    parser.add_argument(
        "--evidence-dir", required=True, type=Path,
        help="Path to evidence directory containing report JSONs.",
    )
    parser.add_argument(
        "--intent", default="(not recorded)",
        help="User's intent or prompt for this test session.",
    )
    parser.add_argument(
        "--notes", default="",
        help="Optional freeform notes about this session.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output path for session_log.md (default: <evidence-dir>/session_log.md).",
    )

    args = parser.parse_args(argv)
    evidence_dir = args.evidence_dir.resolve()

    if not evidence_dir.is_dir():
        print(f"[FAIL] Evidence directory not found: {evidence_dir}", file=sys.stderr)
        return 1

    output_path = args.output or (evidence_dir / "session_log.md")

    # Build entry
    entry = build_entry(evidence_dir, args.intent, args.notes)

    # Create header if file doesn't exist
    if not output_path.exists():
        header = "# MLGG Session Log\n\nAppend-only record of test sessions.\n"
        output_path.write_text(header, encoding="utf-8")

    # Append
    with output_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(f"Session recorded: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
