"""
Failure diagnosis: LLM-powered actionable fix suggestions when gates fail.

Reads the gate's JSON report (which contains GateIssue objects with severity,
code, message, details, and static remediation), then calls an LLM to generate
context-specific, actionable repair steps.

Usage:
    from failure_diagnosis import diagnose_failure
    diagnosis = diagnose_failure(gate_name, report_path, normalized_request)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _load_report(report_path: Path) -> Dict[str, Any]:
    """Load a gate report JSON file."""
    if not report_path.exists():
        return {}
    try:
        with open(report_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_issues(report: Dict[str, Any]) -> list:
    """Extract failure and warning issues from a gate report."""
    issues = []
    for issue in report.get("issues", []):
        sev = issue.get("severity", "info")
        if sev in ("critical", "error", "warning"):
            # Omit 'details' to avoid leaking PHI/data values into LLM prompts.
            # Only pass structural info: code, severity, message, remediation.
            issues.append({
                "code": issue.get("code", ""),
                "severity": sev,
                "message": issue.get("message", ""),
                "remediation": issue.get("remediation", ""),
            })
    return issues


def diagnose_failure(
    gate_name: str,
    report_path: Path,
    normalized: Optional[Dict[str, Any]] = None,
    verbose: bool = True,
) -> Optional[str]:
    """Generate actionable diagnosis for a gate failure.

    Args:
        gate_name: Name of the failed gate.
        report_path: Path to the gate's JSON report.
        normalized: The normalized request (for project context).
        verbose: Print diagnosis to stderr.

    Returns:
        Diagnosis text, or None if diagnosis failed.
    """
    report = _load_report(report_path)
    if not report:
        return None

    issues = _extract_issues(report)
    if not issues:
        return None

    # Build compact context
    project_ctx = ""
    if normalized:
        project_ctx = json.dumps({
            "target": normalized.get("target_name", ""),
            "claim_tier": normalized.get("claim_tier_target", ""),
            "primary_metric": normalized.get("primary_metric", ""),
            "splits": list((normalized.get("split_paths") or {}).keys()),
        }, indent=2)

    prompt = f"""You are a medical ML governance expert. A pipeline gate has failed.
Generate specific, actionable fix steps that a data scientist can follow immediately.

Gate: {gate_name}
Project context: {project_ctx or "not available"}

Failed issues:
{json.dumps(issues, indent=2)}

For EACH issue, output:
1. **What went wrong** (one sentence, plain language)
2. **Root cause** (most likely reason this happened)
3. **Fix steps** (numbered, concrete, copy-pasteable where possible)
4. **Verification** (how to confirm the fix worked)

Be specific to THIS failure, not generic. Reference actual field names, file paths,
and thresholds from the issue details. Keep it concise — this is a working engineer's
checklist, not an essay."""

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "text",
                "--max-budget-usd", "0.20",
                "--system-prompt",
                "You are a medical ML pipeline diagnosis assistant. Be specific and actionable.",
                prompt,
            ],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            if verbose:
                print(f"[DIAGNOSE] LLM call failed (exit {result.returncode})", file=sys.stderr)
            return None

        diagnosis = result.stdout.strip()
        if verbose and diagnosis:
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"  DIAGNOSIS: {gate_name}", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
            print(diagnosis, file=sys.stderr)
            print(f"{'='*60}\n", file=sys.stderr)

        return diagnosis

    except subprocess.TimeoutExpired:
        if verbose:
            print(f"[DIAGNOSE] LLM timed out for {gate_name}", file=sys.stderr)
        return None
    except FileNotFoundError:
        if verbose:
            print("[DIAGNOSE] 'claude' CLI not found, skipping diagnosis.", file=sys.stderr)
        return None
    except Exception as exc:
        if verbose:
            print(f"[DIAGNOSE] Unexpected error: {exc}", file=sys.stderr)
        return None
