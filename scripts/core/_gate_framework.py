"""
Unified gate framework for ml-governance-guard.

Provides standardized report envelope (v2.0.0), severity levels (GateIssue),
remediation hint registry, and CLI helpers for the 33 fail-closed gates.

All gates use the legacy pattern: standalone parse_args() + main() + finish().
GateBase abstract class was removed (no gate subclassed it).
"""

from __future__ import annotations

import argparse
import enum
import itertools
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from _gate_utils import add_timeout_argument, get_gate_elapsed
except ImportError:
    from scripts.core._gate_utils import add_timeout_argument, get_gate_elapsed  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

class Severity(enum.Enum):
    """Issue severity levels, ordered from most to least critical."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {
            Severity.CRITICAL: 0,
            Severity.ERROR: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3,
        }[self]

    def __lt__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


# ---------------------------------------------------------------------------
# Structured issue
# ---------------------------------------------------------------------------

class GateIssue:
    """A single validation issue with severity and optional remediation."""

    __slots__ = (
        "code",
        "severity",
        "message",
        "details",
        "remediation",
        "source_file",
    )

    def __init__(
        self,
        code: str,
        severity: Severity,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        remediation: Optional[str] = None,
        source_file: Optional[str] = None,
    ) -> None:
        self.code = code
        self.severity = severity
        self.message = message
        self.details = details or {}
        self.remediation = remediation
        self.source_file = source_file

    def __repr__(self) -> str:
        return f"GateIssue({self.code!r}, {self.severity.value}, {self.message!r})"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
        }
        if self.remediation:
            d["remediation"] = self.remediation
        if self.source_file:
            d["source_file"] = self.source_file
        return d

    @staticmethod
    def from_legacy(
        legacy: Dict[str, Any],
        severity: Severity,
    ) -> "GateIssue":
        """Convert a legacy issue dict (code/message/details) to GateIssue."""
        return GateIssue(
            code=str(legacy.get("code", "unknown")),
            severity=severity,
            message=str(legacy.get("message", "")),
            details=d if isinstance((d := legacy.get("details")), dict) else {},
        )


# ---------------------------------------------------------------------------
# Remediation hint registry
# ---------------------------------------------------------------------------

import threading as _threading

_REMEDIATION_REGISTRY: Dict[str, str] = {}
_REMEDIATION_LOCK = _threading.Lock()


def register_remediation(code: str, hint: str) -> None:
    """Register a remediation hint for a failure code (thread-safe)."""
    with _REMEDIATION_LOCK:
        _REMEDIATION_REGISTRY[code] = hint


def get_remediation(code: str) -> Optional[str]:
    """Retrieve a registered remediation hint, or None."""
    return _REMEDIATION_REGISTRY.get(code)


def register_remediations(mapping: Dict[str, str]) -> None:
    """Bulk-register remediation hints (thread-safe)."""
    with _REMEDIATION_LOCK:
        _REMEDIATION_REGISTRY.update(mapping)


# ---------------------------------------------------------------------------
# Built-in remediation hints (cross-gate common codes)
# ---------------------------------------------------------------------------

_COMMON_REMEDIATIONS: Dict[str, str] = {
    "file_not_found": "Verify the file path in your request JSON. Ensure the file exists and is readable.",
    "invalid_json": "Fix JSON syntax errors in the input file. Use a JSON linter to validate.",
    "json_root_not_object": "Ensure the JSON file root is a {} object, not an array or primitive.",
    "missing_required_field": "Add the missing field to the input file. Check the gate documentation for required schema.",
    "hash_mismatch": "Re-generate the artifact. The file content has changed since the hash was recorded.",
    "metric_mismatch": "Re-run model evaluation to produce consistent metrics. Check for non-determinism in the pipeline.",
    "threshold_violation": "Adjust model/data to meet the threshold, or review whether the threshold in performance_policy is appropriate.",
    "strict_mode_warning_as_failure": "This warning is promoted to failure under --strict. Fix the underlying issue or run without --strict for exploratory mode.",
    "gate_timeout": "Increase --timeout value or optimize the gate's input data size.",
    "patient_id_overlap": "Remove overlapping patient IDs between train/valid/test splits. Check split_protocol_spec.",
    "temporal_leakage": "Ensure all training data timestamps precede validation/test timestamps. Review split boundaries.",
    "row_hash_overlap": "Deduplicate identical rows across splits. This likely indicates a split generation bug.",
    "feature_name_suspicious": "Rename or remove features matching the forbidden pattern. They may encode future information.",
    "signature_verification_failed": "Re-sign the artifact with the correct private key. Ensure the public key matches.",
    "key_revoked": "The signing key has been revoked. Re-sign with a non-revoked key.",
    "manifest_comparison_missing": "Provide --compare-manifest with a baseline manifest, or use --allow-missing-compare for first-run bootstrap.",
    "claim_tier_below_publication": "Set claim_tier_target to 'publication-grade' in request JSON for publication-grade validation.",
    "primary_metric_not_pr_auc": "Publication-grade requires primary_metric='pr_auc'. Update your request JSON.",
    "clinical_floor_below_baseline": "Increase clinical floor values to meet publication-grade minimums defined in PUBLICATION_POLICY_BASELINES.",
    "cross_period_missing": "Add at least one cross_period cohort to external validation. This is required for publication-grade.",
    "cross_institution_missing": "Add at least one cross_institution cohort to external validation. This is required for publication-grade.",
    "checklist_incomplete": "Complete all required TRIPOD+AI / PROBAST+AI / STARD-AI checklist items in your checklist spec.",
    "bias_risk_not_low": "Address bias risk factors until overall_bias_risk is 'low'. Review PROBAST+AI domains.",
    "seed_instability": "Model shows excessive variation across random seeds. Consider ensemble methods or more stable architectures.",
    "calibration_poor": "Recalibrate the model (e.g., Platt scaling, isotonic regression) to improve ECE and calibration slope.",
    "ci_width_excessive": "Confidence intervals are too wide. Increase bootstrap resamples or collect more data.",
    "permutation_not_significant": "Model performance is not statistically significant vs. permuted null. Review model validity.",
}

register_remediations(_COMMON_REMEDIATIONS)


# ---------------------------------------------------------------------------
# Report envelope
# ---------------------------------------------------------------------------

REPORT_ENVELOPE_VERSION = "2.0.0"


def build_report_envelope(
    gate_name: str,
    status: str,
    strict_mode: bool,
    failures: List[GateIssue],
    warnings: List[GateIssue],
    summary: Optional[Dict[str, Any]] = None,
    input_files: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, Any]] = None,
    gate_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Build a standardized gate report envelope.

    All gate reports share this top-level structure, making downstream
    parsing (publication_gate, self_critique, render_user_summary)
    uniform and reliable.
    """
    now_utc = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    failure_dicts = [
        f.to_dict() for f in sorted(failures, key=lambda i: i.severity.rank)
    ]
    warning_dicts = [
        w.to_dict() for w in sorted(warnings, key=lambda i: i.severity.rank)
    ]

    envelope: Dict[str, Any] = {
        "envelope_version": REPORT_ENVELOPE_VERSION,
        "gate_name": gate_name,
        "gate_version": gate_version,
        "status": status,
        "strict_mode": strict_mode,
        "execution_timestamp_utc": now_utc,
        "execution_time_seconds": round(get_gate_elapsed(), 3),
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "failures": failure_dicts,
        "warnings": warning_dicts,
    }

    if summary is not None:
        envelope["summary"] = summary

    if input_files:
        envelope["input_files"] = input_files

    if extra:
        _RESERVED = {
            "envelope_version", "gate_name", "gate_version", "status",
            "strict_mode", "execution_timestamp_utc", "execution_time_seconds",
            "failure_count", "warning_count", "failures", "warnings",
        }
        for k, v in extra.items():
            if k not in _RESERVED:
                envelope[k] = v

    # Always include peer_review_context for deterministic report schema.
    # Empty list when no failures/warnings or KB unavailable.
    #
    # 2026-04-17 fix: previously this block only ran on `failures`, leaving
    # warning-only "failed" gates (strict-mode-upgrade pattern: cohort,
    # split, definition, missingness) with no backing evidence. Also
    # switched from `retrieve_by_gate` (severity-only sort, ~20% precision
    # on failure-specific relevance) to `retrieve_for_failure` which re-ranks
    # by issue-code keyword overlap with concern tags/text.
    _peer_ctx: list = []
    if failures or warnings:
        try:
            from _peer_review_retrieval import retrieve_for_failure
            _issue_codes = [i.code for i in failures] + [i.code for i in warnings]
            peer_results = retrieve_for_failure(gate_name, _issue_codes, limit=5)
            if peer_results:
                _peer_ctx = [
                    {
                        "concern_id": c.get("concern_id", ""),
                        "paper_id": c.get("_paper_id", c.get("paper_id", c.get("concern_id", "")[:6])),
                        "severity": c.get("severity", ""),
                        "concern": c.get("concern_text", "")[:200],
                        "fix": c.get("author_response", "")[:200],
                        "tags": c.get("tags", []),
                    }
                    for c in peer_results
                ]
        except (ImportError, FileNotFoundError):
            pass
    envelope["peer_review_context"] = _peer_ctx

    return envelope


# ---------------------------------------------------------------------------
# CLI argument helpers
# ---------------------------------------------------------------------------

def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by all gates: --report, --strict, --timeout, --dry-run."""
    common = parser.add_argument_group("Common gate options")
    common.add_argument(
        "--report",
        help="Path to write the JSON gate report.",
    )
    common.add_argument(
        "--strict",
        action="store_true",
        help="Promote warnings to failures (required for publication-grade).",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and arguments only; do not run gate logic.",
    )
    add_timeout_argument(parser)


def add_input_file_argument(
    group: argparse._ArgumentGroup,
    flag: str,
    help_text: str,
    required: bool = True,
) -> None:
    """Add an input file argument with consistent naming."""
    group.add_argument(flag, required=required, help=help_text)


_MAX_CLI_ARG_LENGTH = 4096  # max characters per CLI string argument


def sanitize_cli_args(args: argparse.Namespace) -> List[str]:
    """Validate CLI argument lengths and content. Returns list of issues."""
    issues: List[str] = []
    for attr, value in vars(args).items():
        if isinstance(value, str):
            if len(value) > _MAX_CLI_ARG_LENGTH:
                issues.append(
                    f"Argument --{attr} exceeds {_MAX_CLI_ARG_LENGTH} chars "
                    f"({len(value)} chars)"
                )
            if "\x00" in value:
                issues.append(f"Argument --{attr} contains null byte")
    return issues


def validate_input_files(
    args: argparse.Namespace,
    file_args: Sequence[str],
) -> List[GateIssue]:
    """Pre-validate that all specified input file arguments point to existing files.

    Returns a list of GateIssue for any missing files.
    """
    issues: List[GateIssue] = []
    for arg_name in file_args:
        value = getattr(args, arg_name.lstrip("-").replace("-", "_"), None)
        if value is None:
            continue
        p = Path(str(value)).expanduser().resolve()
        if not p.exists():
            issues.append(GateIssue(
                code="file_not_found",
                severity=Severity.CRITICAL,
                message=f"Input file not found: {p}",
                details={"argument": arg_name, "path": str(p)},
                remediation=get_remediation("file_not_found"),
            ))
        elif not p.is_file():
            issues.append(GateIssue(
                code="path_not_file",
                severity=Severity.CRITICAL,
                message=f"Path is not a regular file: {p}",
                details={"argument": arg_name, "path": str(p)},
                remediation="Ensure the path points to a file, not a directory.",
            ))
    return issues


# ---------------------------------------------------------------------------
# Terminal output formatting
# ---------------------------------------------------------------------------

_SEVERITY_PREFIXES = {
    Severity.CRITICAL: "\033[1;31m[CRIT]\033[0m",
    Severity.ERROR: "\033[31m[FAIL]\033[0m",
    Severity.WARNING: "\033[33m[WARN]\033[0m",
    Severity.INFO: "\033[36m[INFO]\033[0m",
}

_SEVERITY_PREFIXES_PLAIN = {
    Severity.CRITICAL: "[CRIT]",
    Severity.ERROR: "[FAIL]",
    Severity.WARNING: "[WARN]",
    Severity.INFO: "[INFO]",
}


def _use_color() -> bool:
    """Decide whether to emit ANSI color codes."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def format_issue_line(issue: GateIssue) -> str:
    """Format a single issue for terminal output."""
    prefixes = _SEVERITY_PREFIXES if _use_color() else _SEVERITY_PREFIXES_PLAIN
    prefix = prefixes.get(issue.severity, "[????]")
    line = f"{prefix} {issue.code}: {issue.message}"
    if issue.remediation:
        line += f"\n       \u2192 Fix: {issue.remediation}"
    return line


def print_gate_summary(
    gate_name: str,
    status: str,
    failures: List[GateIssue],
    warnings: List[GateIssue],
    strict: bool,
    elapsed: float,
) -> None:
    """Print a structured gate summary to stdout."""
    use_color = _use_color()

    if use_color:
        status_str = (
            "\033[32mPASS\033[0m" if status == "pass"
            else "\033[1;31mFAIL\033[0m"
        )
    else:
        status_str = status.upper()

    print(f"\n{'=' * 60}")
    print(f"Gate: {gate_name}")
    print(f"Status: {status_str}  |  Failures: {len(failures)}  |  Warnings: {len(warnings)}  |  Strict: {strict}  |  Time: {elapsed:.1f}s")
    print(f"{'=' * 60}")

    all_issues = sorted(
        itertools.chain(
            ((issue, True) for issue in failures),
            ((issue, False) for issue in warnings),
        ),
        key=lambda pair: pair[0].severity.rank,
    )

    if all_issues:
        print()
        for issue, _is_failure in all_issues:
            print(format_issue_line(issue))
        print()

    critical_count = sum(1 for f in failures if f.severity == Severity.CRITICAL)
    if critical_count > 0:
        print(f"  \u26a0  {critical_count} CRITICAL issue(s) require immediate attention.")
        print()

    # Peer Review RAG context — show similar issues from NC papers
    if failures:
        try:
            from _peer_review_retrieval import format_gate_peer_context
            peer_ctx = format_gate_peer_context(gate_name)
            if peer_ctx:
                print(peer_ctx)
                print()
        except (ImportError, FileNotFoundError):
            pass  # Peer review KB not available — skip silently


