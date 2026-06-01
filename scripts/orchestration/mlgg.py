#!/usr/bin/env python3
"""
[ENTRY POINT — PRIMARY] Unified CLI entrypoint for ml-governance-guard.

Registered as `mlgg` in pyproject.toml. All user commands go through here.

This is a thin wrapper that forwards subcommands to existing scripts, so users
can use one stable command surface in terminal workflows and agent automation.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# Subprocess timeout: gates can be slow (large datasets) but should not run forever.
# Per-subprocess wall-clock limit. Adjust via MLGG_SUBPROCESS_TIMEOUT env var.
try:
    _DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = max(60, min(
        int(os.environ.get("MLGG_SUBPROCESS_TIMEOUT", "3600")),
        86400,  # cap at 24 hours
    ))
except (ValueError, TypeError):
    _DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 3600

# Allowed --python executable names (basenames only).  Full-path executables
# matching these basenames are also accepted.
_ALLOWED_PYTHON_BASENAMES = frozenset(
    [
        "python", "python3", "python3.8", "python3.9", "python3.10",
        "python3.11", "python3.12", "python3.13",
    ]
)

# Maximum allowed byte-length for any single CLI argument to prevent
# memory exhaustion from absurdly long strings.
_MAX_ARG_BYTES = 8192


def _validate_python_bin(value: str) -> str:
    """
    Validate that --python points to a Python-like executable.

    Accepts:
    - sys.executable (always trusted)
    - Any path whose basename is in _ALLOWED_PYTHON_BASENAMES
    - Any path found via shutil.which that resolves to a python binary

    Raises SystemExit(2) with an informative message on failure.
    """
    if not value or not value.strip():
        return sys.executable
    candidate = value.strip()
    if candidate == sys.executable:
        return candidate
    import shutil
    basename = Path(candidate).name.lower()
    # Strip .exe suffix on Windows
    if basename.endswith(".exe"):
        basename = basename[:-4]
    if basename not in _ALLOWED_PYTHON_BASENAMES:
        print(
            f"[FAIL] invalid_python_executable: --python '{candidate}' is not a recognized "
            f"Python executable. Allowed basenames: {sorted(_ALLOWED_PYTHON_BASENAMES)}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    # Ensure it actually exists / is findable
    resolved = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
    if resolved is None:
        print(
            f"[FAIL] python_executable_not_found: --python '{candidate}' not found on PATH "
            f"or filesystem.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return resolved


# Forbidden path prefixes reused from _gate_utils._FORBIDDEN_PATH_PREFIXES.
# Duplicated here to avoid importing from scripts/ at module load time (circular risk).
_FORBIDDEN_CWD_PREFIXES = frozenset(
    ["/etc", "/private/etc", "/proc", "/sys", "/dev", "/var/run", "/boot", "/sbin"]
)

# Profile name must be a safe identifier: alphanumeric, hyphens, underscores only.
_PROFILE_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')


def _validate_cwd(value: str) -> Path:
    """
    Validate that --cwd is an existing directory, not a forbidden system path.

    Prevents:
    - Path traversal to /etc, /proc, /sys, etc.
    - Non-existent or file paths being used as working directories.
    """
    if "\x00" in value:
        print("[FAIL] invalid_cwd: --cwd contains NUL byte.", file=sys.stderr)
        raise SystemExit(2)
    try:
        cwd = Path(value).expanduser().resolve()
    except Exception as exc:
        print(f"[FAIL] invalid_cwd: cannot resolve --cwd '{value}': {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    # Forbidden system path check
    cwd_str = str(cwd)
    for prefix in _FORBIDDEN_CWD_PREFIXES:
        if cwd_str == prefix or cwd_str.startswith(prefix + "/"):
            print(
                f"[FAIL] cwd_forbidden_path: --cwd '{cwd}' targets a forbidden system "
                f"location. Forbidden prefixes: {sorted(_FORBIDDEN_CWD_PREFIXES)}",
                file=sys.stderr,
            )
            raise SystemExit(2)
    if not cwd.exists():
        print(f"[FAIL] cwd_not_found: --cwd directory does not exist: {cwd}", file=sys.stderr)
        raise SystemExit(2)
    if not cwd.is_dir():
        print(f"[FAIL] cwd_not_directory: --cwd path is not a directory: {cwd}", file=sys.stderr)
        raise SystemExit(2)
    return cwd


def _validate_profile_name(value: str) -> str:
    """
    Validate --profile-name is a safe identifier.

    Rejects values containing path separators (/ \\), null bytes, or characters
    that could be used for path traversal when the name is used as a filename.
    Allowed: alphanumeric, hyphens, underscores, 1-128 characters.
    """
    if not value or not value.strip():
        return ""
    cleaned = value.strip()
    if not _PROFILE_NAME_RE.match(cleaned):
        print(
            f"[FAIL] invalid_profile_name: --profile-name '{cleaned}' contains invalid "
            f"characters. Allowed: alphanumeric, hyphens, underscores (max 128 chars).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return cleaned


def _validate_passthrough(passthrough: List[str]) -> List[str]:
    """
    Validate pass-through arguments for basic safety.

    Checks:
    - Each token length ≤ _MAX_ARG_BYTES (prevents memory exhaustion)
    - No NUL bytes (prevent arg smuggling on some systems)

    Does NOT block specific flags — that's the subcommand's responsibility.
    """
    validated: List[str] = []
    for i, token in enumerate(passthrough):
        if len(token.encode("utf-8", errors="replace")) > _MAX_ARG_BYTES:
            print(
                f"[FAIL] passthrough_arg_too_long: argument at index {i} exceeds "
                f"{_MAX_ARG_BYTES} bytes. Possible memory exhaustion attempt.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if "\x00" in token:
            print(
                f"[FAIL] passthrough_arg_nul_byte: argument at index {i} contains a NUL "
                f"byte, which is not allowed.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        validated.append(token)
    return validated


def _run_subprocess(
    cmd: List[str],
    cwd: Path,
    timeout: Optional[int] = None,
) -> int:
    """
    Centralized subprocess launcher with timeout and error handling.

    All subprocess.run calls in this module should go through this function
    to ensure consistent timeout enforcement and return-code handling.
    """
    effective_timeout = timeout if timeout is not None else _DEFAULT_SUBPROCESS_TIMEOUT_SECONDS
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), text=True, timeout=effective_timeout)
        return int(proc.returncode)
    except subprocess.TimeoutExpired:
        print(
            f"[FAIL] subprocess_timeout: command exceeded {effective_timeout}s timeout. "
            f"Set MLGG_SUBPROCESS_TIMEOUT env var to increase limit.",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError as exc:
        print(f"[FAIL] subprocess_not_found: {exc}", file=sys.stderr)
        return 2
SCRIPTS_ROOT = REPO_ROOT / "scripts"
EXPERIMENTS_ROOT = REPO_ROOT / "experiments" / "authority-e2e"


COMMANDS: Dict[str, Tuple[Path, str]] = {
    "onboarding": (
        SCRIPTS_ROOT / "orchestration" / "mlgg_onboarding.py",
        "Run guided novice onboarding (demo data -> train -> attestation -> strict workflow).",
    ),
    "interactive": (
        SCRIPTS_ROOT / "orchestration" / "mlgg_interactive.py",
        "Launch interactive wizard for core commands (init/workflow/train/authority).",
    ),
    "init": (SCRIPTS_ROOT / "training" / "init_project.py", "Initialize project folders and config templates."),
    "split": (SCRIPTS_ROOT / "training" / "split_data.py", "Split a single CSV into train/valid/test with medical safety guarantees."),
    "doctor": (SCRIPTS_ROOT / "diagnostics" / "env_doctor.py", "Check runtime dependencies and optional backends."),
    "preflight": (SCRIPTS_ROOT / "training" / "schema_preflight.py", "Validate train/valid/test schema and semantic mapping."),
    "workflow": (SCRIPTS_ROOT / "orchestration" / "run_productized_workflow.py", "Run doctor -> preflight -> strict -> summary."),
    "strict": (SCRIPTS_ROOT / "orchestration" / "run_dag_pipeline.py", "Run strict fail-closed DAG gate pipeline."),
    "semantic-audit": (SCRIPTS_ROOT / "orchestration" / "semantic_audit.py", "LLM-powered semantic leakage detection on feature columns."),
    "summary": (SCRIPTS_ROOT / "reporting" / "render_user_summary.py", "Render user-facing markdown/json summary."),
    "train": (SCRIPTS_ROOT / "training" / "train_select_evaluate.py", "Train/select/evaluate and emit evidence artifacts."),
    "authority": (EXPERIMENTS_ROOT / "run_authority_e2e.py", "Run authority E2E benchmark suite."),
    "benchmark-suite": (
        EXPERIMENTS_ROOT / "run_release_benchmark_matrix.py",
        "Run structured multi-dataset stability benchmark matrix (authority + adversarial).",
    ),
    "authority-release": (
        EXPERIMENTS_ROOT / "run_authority_e2e.py",
        "Run authority E2E with recommended release-grade stress route (CKD).",
    ),
    "authority-research-heart": (
        EXPERIMENTS_ROOT / "run_authority_e2e.py",
        "Run authority E2E with heart research/high-pressure stress route.",
    ),
    "scan-diabetes": (
        EXPERIMENTS_ROOT / "scan_stress_diabetes_feasibility.py",
        "Scan stress-case diabetes feasibility across target modes and row caps.",
    ),
    "adversarial": (
        EXPERIMENTS_ROOT / "run_adversarial_gate_checks.py",
        "Run adversarial fail-closed gate scenarios.",
    ),
    "play": (
        SCRIPTS_ROOT / "orchestration" / "mlgg_pixel.py",
        "Launch pixel-art interactive CLI launcher (guided menu experience).",
    ),
    "audit": (
        SCRIPTS_ROOT / "reporting" / "audit_external_project.py",
        "Quantitative 10-dimension audit of a medical ML project (100-point scale).",
    ),
    "fairness": (
        SCRIPTS_ROOT / "gates" / "fairness_equity_gate.py",
        "Validate subgroup fairness and equity metrics (equalized odds, disparate impact).",
    ),
    "sample-size": (
        SCRIPTS_ROOT / "gates" / "sample_size_gate.py",
        "Validate sample size adequacy (EPV, shrinkage factor, Riley criteria).",
    ),
    "batch-review": (
        SCRIPTS_ROOT / "review" / "batch_journal_review.py",
        "Batch audit N projects against journal standards with comparison matrix.",
    ),
    "audit-report": (
        SCRIPTS_ROOT / "reporting" / "generate_audit_report.py",
        "Generate comprehensive audit report with TRIPOD+AI/PROBAST+AI coverage, error KB lookup, and literature citations.",
    ),
    "export-review-prompt": (
        SCRIPTS_ROOT / "reporting" / "export_review_prompt.py",
        "Export MLGG review criteria as a portable LLM prompt. Users paste the output into any LLM (Claude, GPT-4, Gemini) to review a paper without local deployment.",
    ),
    "lint": (
        REPO_ROOT / "plugin" / "mlgg_lint" / "__main__.py",
        "Static analysis for ML code — detect data leakage and best-practice violations.",
    ),
    "audit-metrics": (
        SCRIPTS_ROOT / "reporting" / "audit_metrics.py",
        "Quick publication-readiness check from metrics JSON — no data files needed.",
    ),
    "init-guide": (
        SCRIPTS_ROOT / "diagnostics" / "init_guide.py",
        "Generate MLGG methodology guide (.mlgg/ + CLAUDE.md) for any ML project.",
    ),
    "record-session": (
        SCRIPTS_ROOT / "reporting" / "record_session.py",
        "Append a session log entry from evidence directory.",
    ),
    "rag": (
        SCRIPTS_ROOT / "rag" / "query.py",
        "Query the MLGG peer-review knowledge base via hybrid RAG (dense + BM25 + MMR).",
    ),
    "llm-audit": (
        SCRIPTS_ROOT / "review" / "llm_paper_audit.py",
        "W29-MVP: LLM-first paper audit with optional RAG enrichment (Anthropic Claude).",
    ),
}
INTERACTIVE_CORE_COMMANDS = ("init", "workflow", "train", "authority")

# W28-S0: Two-product-line grouping (Mode A vs Mode B/C per SKILL.md Audit
# Routing). Purely organizational — every command still resolves through
# COMMANDS, so nothing about dispatch / imports / contracts changes. Used
# only to render a grouped --help and to drive SKILL.md / README sections.
#
# Rule of thumb for what belongs where:
#   - "governance": needs YOUR training pipeline (evidence/*.json, configs/)
#   - "review":     audits SOMEONE ELSE'S code/paper, no evidence required
#   - "benchmark":  internal release-gate suites (not user-facing)
#   - "ops":        meta / wizard / dispatch helpers
#
# When adding a new subcommand to COMMANDS, also add its name to ONE list
# below. The smoke test test_command_groups_cover_all_commands enforces
# parity (see tests/test_mlgg_command_groups.py).
COMMAND_GROUPS: Dict[str, Tuple[str, ...]] = {
    "governance": (
        "onboarding", "init", "split", "doctor", "preflight",
        "workflow", "strict", "semantic-audit", "summary", "train",
        "fairness", "sample-size", "init-guide", "record-session",
    ),
    "review": (
        "audit", "audit-report", "audit-metrics", "batch-review",
        "export-review-prompt", "lint", "rag", "llm-audit",
    ),
    "benchmark": (
        "authority", "benchmark-suite", "authority-release",
        "authority-research-heart", "scan-diabetes", "adversarial",
    ),
    "ops": (
        "interactive", "play",
    ),
}

COMMAND_GROUP_DESCRIPTIONS: Dict[str, str] = {
    "governance": "Mode A — runs against YOUR training pipeline (needs evidence/*.json, configs/)",
    "review":     "Mode B/C — audits SOMEONE ELSE'S code/paper, no instrumented evidence required",
    "benchmark":  "Internal release-gate suites (run before tagging a release)",
    "ops":        "Wizards / launchers / dispatch helpers",
}
COMMAND_PRESETS: Dict[str, Tuple[str, ...]] = {
    "strict": ("--strict",),
    "authority-release": (
        "--include-stress-cases",
        "--stress-case-id",
        "uci-chronic-kidney-disease",
    ),
    "authority-research-heart": (
        "--include-stress-cases",
        "--stress-case-id",
        "uci-heart-disease",
        "--stress-seed-search",
    ),
}
PRESET_BLOCKED_FLAGS: Dict[str, Tuple[str, ...]] = {
    # Keep wrapper semantics strict and auditable: these wrappers should not
    # allow callers to override the fixed stress route via passthrough flags.
    "authority-release": (
        "--include-stress-cases",
        "--stress-case-id",
        "--stress-seed-search",
        "--no-stress-seed-search",
    ),
    "authority-research-heart": (
        "--include-stress-cases",
        "--stress-case-id",
        "--stress-seed-search",
        "--no-stress-seed-search",
    ),
}
AUTHORITY_PRESET_ROUTE_OVERRIDE_FORBIDDEN = "authority_preset_route_override_forbidden"
MLGG_ERROR_CONTRACT_VERSION = "mlgg_error.v1"


def _extract_option_value(argv: list[str], option: str, default: str) -> str:
    for idx, token in enumerate(argv):
        if token == option and idx + 1 < len(argv):
            value = str(argv[idx + 1]).strip()
            if value:
                return value
        if token.startswith(option + "="):
            value = token.split("=", 1)[1].strip()
            if value:
                return value
    return default


def _find_subcommand(argv: list[str]) -> tuple[int, str] | None:
    for idx, token in enumerate(argv):
        if token in COMMANDS:
            return idx, str(token)
    return None


def maybe_forward_subcommand_help(raw_argv: list[str]) -> int | None:
    """
    Forward intuitive help forms like:
    - mlgg.py onboarding --help
    - mlgg.py train --interactive --help
    - mlgg.py interactive --help
    """
    if not raw_argv:
        return None
    hit = _find_subcommand(raw_argv)
    if not hit:
        return None
    subcommand_index, subcommand = hit
    suffix = raw_argv[subcommand_index + 1 :]
    if not any(token in {"-h", "--help"} for token in suffix):
        return None
    # Keep explicit passthrough handling in normal parse flow.
    if "--" in suffix:
        return None

    python_bin = _validate_python_bin(
        _extract_option_value(raw_argv, "--python", sys.executable)
    )
    cwd_raw = _extract_option_value(raw_argv, "--cwd", str(REPO_ROOT))
    cwd = _validate_cwd(cwd_raw)

    interactive_requested = subcommand == "interactive" or "--interactive" in raw_argv
    if interactive_requested:
        wizard_script = COMMANDS["interactive"][0]
        if not wizard_script.exists():
            print(f"[FAIL] Interactive script not found: {wizard_script}", file=sys.stderr)
            return 2
        target_command = subcommand if subcommand in INTERACTIVE_CORE_COMMANDS else ""
        if subcommand == "interactive":
            target_command = _extract_option_value(raw_argv, "--command", "")
        cmd = [python_bin, str(wizard_script)]
        if target_command in INTERACTIVE_CORE_COMMANDS:
            cmd.extend(["--command", target_command])
        cmd.append("--help")
        print(f"$ {shlex.join(cmd)}", file=sys.stderr)
        return _run_subprocess(cmd, cwd, timeout=60)

    script_path = COMMANDS[subcommand][0]
    if not script_path.exists():
        print(f"[FAIL] Script not found for command '{subcommand}': {script_path}", file=sys.stderr)
        return 2
    cmd = [python_bin, str(script_path), "--help"]
    print(f"$ {shlex.join(cmd)}", file=sys.stderr)
    return _run_subprocess(cmd, cwd, timeout=60)


def passthrough_contains_flag(passthrough: list[str], flag: str) -> bool:
    for token in passthrough:
        if token == flag:
            return True
        if token.startswith(flag + "="):
            return True
    return False


def emit_fail(
    *,
    code: str,
    message: str,
    error_json: bool,
    details: Dict[str, object] | None = None,
) -> int:
    print(f"[FAIL] {code}: {message}", file=sys.stderr)
    if error_json:
        payload = {
            "contract_version": MLGG_ERROR_CONTRACT_VERSION,
            "status": "fail",
            "code": code,
            "message": message,
            "details": details or {},
        }
        print(json.dumps(payload, ensure_ascii=True), file=sys.stderr)
    return 2


def _render_grouped_command_help() -> str:
    """W28-S0: format the available-commands block by COMMAND_GROUPS.

    Falls back gracefully: any command in COMMANDS not yet placed in a
    group is appended under an explicit "Other" header rather than
    silently dropped. This keeps --help correct even mid-refactor.
    """
    lines: list[str] = []
    placed: set[str] = set()
    for group_name, members in COMMAND_GROUPS.items():
        group_desc = COMMAND_GROUP_DESCRIPTIONS.get(group_name, "")
        lines.append(f"  [{group_name}] — {group_desc}")
        for name in members:
            spec = COMMANDS.get(name)
            if spec is None:
                continue
            lines.append(f"    - {name}: {spec[1]}")
            placed.add(name)
        lines.append("")
    ungrouped = sorted(set(COMMANDS) - placed)
    if ungrouped:
        lines.append("  [other] — not yet assigned to a group (please update COMMAND_GROUPS):")
        for name in ungrouped:
            lines.append(f"    - {name}: {COMMANDS[name][1]}")
    return "\n".join(lines).rstrip()


def build_parser() -> argparse.ArgumentParser:
    command_help = _render_grouped_command_help()
    parser = argparse.ArgumentParser(
        description=(
            "ml-governance-guard unified CLI.\n\n"
            "Available commands (grouped by Mode A vs B/C per SKILL.md Audit Routing):\n"
            f"{command_help}\n\n"
            "Examples:\n"
            "  python3 scripts/orchestration/mlgg.py onboarding --project-root /tmp/mlgg_demo --mode guided --yes\n"
            "  python3 scripts/orchestration/mlgg.py init --project-root /tmp/mlgg_demo\n"
            "  python3 scripts/orchestration/mlgg.py train --interactive\n"
            "  python3 scripts/orchestration/mlgg.py interactive --command workflow\n"
            "  python3 scripts/orchestration/mlgg.py interactive --command train --load-profile --profile-name demo --accept-defaults\n"
            "  python3 scripts/orchestration/mlgg.py interactive --command train -- --help\n"
            "  python3 scripts/orchestration/mlgg.py workflow --request /tmp/mlgg_demo/configs/request.json --strict --allow-missing-compare\n"
            "  python3 scripts/orchestration/mlgg.py workflow -- --help\n"
            "  python3 scripts/orchestration/mlgg.py authority --include-stress-cases\n"
            "  python3 scripts/orchestration/mlgg.py benchmark-suite --profile release\n"
            "  python3 scripts/orchestration/mlgg.py benchmark-suite --profile release --repeat 3 --emit-junit /tmp/mlgg_benchmark.junit.xml\n"
            "  python3 scripts/orchestration/mlgg.py authority-release\n"
            "  python3 scripts/orchestration/mlgg.py authority-research-heart --stress-seed-min 20250003 --stress-seed-max 20250060\n"
            "  python3 scripts/orchestration/mlgg.py play -- --strict-small-sample\n"
            "  python3 scripts/orchestration/mlgg.py play -- --strict-small-sample --fail-on-play-blockers\n"
            "\n"
            "Tip:\n"
            "  Use `<subcommand> --help` for direct script help (e.g., `mlgg.py onboarding --help`).\n"
            "  Use `-- --help` to view subcommand-native help.\n"
            "  For interactive mode, include `--command` before `-- --help`.\n"
            "  Example: `python3 scripts/orchestration/mlgg.py workflow -- --help`\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        allow_abbrev=False,
    )
    _all_commands = sorted(set(COMMANDS.keys()) | {"flow", "validate"})
    parser.add_argument("subcommand", choices=_all_commands, help="Subcommand to execute. Use 'flow' to see the recommended pipeline order.")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run underlying scripts (default: current interpreter).",
    )
    parser.add_argument(
        "--cwd",
        default=str(REPO_ROOT),
        help="Working directory for the subcommand (default: repository root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the forwarded command and exit without executing.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run selected core command via interactive wizard (init/workflow/train/authority).",
    )
    parser.add_argument(
        "--command",
        dest="interactive_command",
        choices=list(INTERACTIVE_CORE_COMMANDS),
        help="Wizard target command when using subcommand=interactive.",
    )
    parser.add_argument(
        "--profile-name",
        default="",
        help="Profile name for interactive mode.",
    )
    parser.add_argument(
        "--profile-dir",
        default="~/.mlgg/profiles",
        help="Profile directory for interactive mode.",
    )
    parser.add_argument(
        "--save-profile",
        action="store_true",
        help="Save interactive selections into profile.",
    )
    parser.add_argument(
        "--load-profile",
        action="store_true",
        help="Load interactive defaults from profile.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Interactive mode only: print generated command without execution.",
    )
    parser.add_argument(
        "--accept-defaults",
        action="store_true",
        help="Interactive mode only: auto-accept prompt defaults when available.",
    )
    parser.add_argument(
        "--error-json",
        action="store_true",
        help="Emit machine-readable JSON error payloads on failure.",
    )
    return parser


def main() -> int:
    # No arguments → show help instead of argparse error
    if len(sys.argv) < 2:
        build_parser().print_help()
        return 0

    forwarded_help = maybe_forward_subcommand_help(sys.argv[1:])
    if forwarded_help is not None:
        return int(forwarded_help)

    parser = build_parser()
    args, passthrough = parser.parse_known_args()
    passthrough = [token for token in passthrough if token != "--"]

    subcommand = str(args.subcommand)
    python_bin = _validate_python_bin(str(args.python).strip() or sys.executable)
    cwd = _validate_cwd(str(args.cwd))
    passthrough = _validate_passthrough(passthrough)
    interactive_requested = bool(args.interactive) or subcommand == "interactive"

    if interactive_requested:
        if subcommand == "interactive" and not args.interactive_command and passthrough and passthrough[0] in {"-h", "--help"}:
            wizard_script = COMMANDS["interactive"][0]
            if not wizard_script.exists():
                return emit_fail(
                    code="interactive_script_not_found",
                    message=f"Interactive script not found: {wizard_script}",
                    error_json=bool(args.error_json),
                )
            cmd = [python_bin, str(wizard_script), "--help"]
            # --dry-run: echo resolved command to stdout (the deliverable);
            # real runs keep it on stderr.
            echo_line = f"$ {shlex.join(cmd)}"
            if args.dry_run:
                print(echo_line)
                return 0
            print(echo_line, file=sys.stderr)
            return _run_subprocess(cmd, cwd, timeout=60)
        target_command = str(args.interactive_command).strip() if args.interactive_command else subcommand
        if target_command == "interactive":
            return emit_fail(
                code="interactive_command_missing",
                message=(
                    "interactive mode requires --command "
                    f"({'|'.join(INTERACTIVE_CORE_COMMANDS)})."
                ),
                error_json=bool(args.error_json),
            )
        if target_command not in INTERACTIVE_CORE_COMMANDS:
            return emit_fail(
                code="interactive_command_not_supported",
                message="--interactive is supported only for: " + ", ".join(INTERACTIVE_CORE_COMMANDS),
                error_json=bool(args.error_json),
            )
        wizard_script = COMMANDS["interactive"][0]
        if not wizard_script.exists():
            return emit_fail(
                code="interactive_script_not_found",
                message=f"Interactive script not found: {wizard_script}",
                error_json=bool(args.error_json),
            )
        cmd = [
            python_bin,
            str(wizard_script),
            "--command",
            target_command,
            "--python",
            python_bin,
            "--cwd",
            str(cwd),
            "--profile-dir",
            str(args.profile_dir),
        ]
        profile_name = _validate_profile_name(str(args.profile_name))
        if profile_name:
            cmd.extend(["--profile-name", profile_name])
        if args.save_profile:
            cmd.append("--save-profile")
        if args.load_profile:
            cmd.append("--load-profile")
        if args.print_only:
            cmd.append("--print-only")
        if args.accept_defaults:
            cmd.append("--accept-defaults")
        cmd.extend(passthrough)
        # --dry-run: echo resolved command to stdout (the deliverable);
        # real runs keep it on stderr.
        echo_line = f"$ {shlex.join(cmd)}"
        if args.dry_run:
            print(echo_line)
            return 0
        print(echo_line, file=sys.stderr)
        return _run_subprocess(cmd, cwd)

    # Built-in commands that don't dispatch to a script
    if subcommand == "validate":
        # Quick validation of all JSON configs in a project directory
        _proj = Path(cwd)
        _configs_dir = _proj / "configs"
        if not _configs_dir.is_dir():
            print(f"[ERROR] No configs/ directory found in {_proj}", file=sys.stderr)
            return 1
        _errors = 0
        _checked = 0
        for _cf in sorted(_configs_dir.glob("*.json")):
            _checked += 1
            try:
                with _cf.open("r", encoding="utf-8") as _fh:
                    _data = json.load(_fh)
                if not isinstance(_data, dict):
                    print(f"  [WARN] {_cf.name}: root is {type(_data).__name__}, expected dict", file=sys.stderr)
                    _errors += 1
                else:
                    print(f"  [OK]   {_cf.name} ({len(_data)} keys)", file=sys.stderr)
            except json.JSONDecodeError as _e:
                print(f"  [FAIL] {_cf.name}: {_e}", file=sys.stderr)
                _errors += 1
        print(f"\n  Checked: {_checked}, Errors: {_errors}", file=sys.stderr)
        return 1 if _errors > 0 else 0

    if subcommand == "flow":
        print("""
  MLGG Pipeline Flow — Recommended execution order

  ┌─────────────────────────────────────────────────────┐
  │ 1. mlgg doctor          Check Python + dependencies │
  │ 2. mlgg init            Create project scaffold     │
  │ 3. mlgg split           Split CSV → train/valid/test│
  │ 4. mlgg train           Train + evaluate models     │
  │ 5. mlgg strict          Run 33-gate DAG pipeline    │
  │ 6. mlgg summary         Human-readable results      │
  └─────────────────────────────────────────────────────┘

  Or use the all-in-one command:
    mlgg onboarding --input-csv data.csv --target-col y

  Show gate dependency DAG:
    mlgg strict --show-dag

  Diagnose a gate failure:
    python3 scripts/reporting/explain_gate.py --report evidence/<gate>_report.json
""")
        return 0

    script_path, _ = COMMANDS[subcommand]
    if not script_path.exists():
        return emit_fail(
            code="subcommand_script_not_found",
            message=f"Script not found for command '{subcommand}': {script_path}",
            error_json=bool(args.error_json),
            details={"subcommand": subcommand, "script_path": str(script_path)},
        )
    if subcommand in PRESET_BLOCKED_FLAGS:
        blocked = [
            flag
            for flag in PRESET_BLOCKED_FLAGS[subcommand]
            if passthrough_contains_flag(passthrough, flag)
        ]
        if blocked:
            return emit_fail(
                code=AUTHORITY_PRESET_ROUTE_OVERRIDE_FORBIDDEN,
                message=(
                    "preset command does not allow overriding fixed route flags: "
                    + ", ".join(blocked)
                ),
                error_json=bool(args.error_json),
                details={"subcommand": subcommand, "blocked_flags": blocked},
            )

    preset_args = list(COMMAND_PRESETS.get(subcommand, ()))

    # Special handling for "lint": invoke as `python -m mlgg_lint` with
    # PYTHONPATH pointing to the plugin directory so the module resolves.
    if subcommand == "lint":
        plugin_dir = str(REPO_ROOT / "plugin")
        cmd = [python_bin, "-m", "mlgg_lint", *preset_args, *passthrough]
        # In --dry-run the resolved command line IS the deliverable, so echo it
        # to stdout where callers/tests inspect it; real runs keep it on stderr.
        lint_echo_line = f"$ PYTHONPATH={plugin_dir} {shlex.join(cmd)}"
        if args.dry_run:
            print(lint_echo_line)
            return 0
        print(lint_echo_line, file=sys.stderr)
        import os as _os
        env = _os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{plugin_dir}:{existing}" if existing else plugin_dir
        try:
            proc = subprocess.run(cmd, cwd=str(cwd), text=True, env=env,
                                  timeout=_DEFAULT_SUBPROCESS_TIMEOUT_SECONDS)
            return int(proc.returncode)
        except subprocess.TimeoutExpired:
            print("[FAIL] subprocess_timeout: lint exceeded timeout.", file=sys.stderr)
            return 2

    cmd = [python_bin, str(script_path), *preset_args, *passthrough]
    # In --dry-run the resolved command line (including injected preset flags
    # such as --include-stress-cases) IS the deliverable, so echo it to stdout
    # where callers/tests inspect it. During a real run the echo stays on
    # stderr so it does not pollute the subprocess's stdout.
    echo_line = f"$ {shlex.join(cmd)}"
    if args.dry_run:
        print(echo_line)
        return 0
    print(echo_line, file=sys.stderr)
    return _run_subprocess(cmd, cwd)


def cli_main() -> None:
    """Entry point for ``console_scripts`` (pyproject.toml)."""
    raise SystemExit(main())


# ─────────────────────────────────────────────────────────────────────────
# W28-S1: ``mlgg-review`` thin shim
# ─────────────────────────────────────────────────────────────────────────
#
# Same dispatch as ``mlgg``, but only the commands in COMMAND_GROUPS["review"]
# are allowed. This gives users who only audit external code/paper a
# focused entry point that doesn't surface 21 governance commands they
# can't run without an instrumented training pipeline. ``mlgg`` keeps all
# 30 commands → full back-compat for existing scripts and CI.

_REVIEW_ALLOWED: frozenset[str] = frozenset(COMMAND_GROUPS["review"])


def review_cli_main() -> None:
    """Entry point for the ``mlgg-review`` console script.

    Behaviour:
    - ``mlgg-review <cmd> ...`` with cmd in COMMAND_GROUPS["review"] →
      identical to ``mlgg <cmd> ...``.
    - ``mlgg-review --help`` / no args → list ONLY the 8 review commands
      with their descriptions; point at ``mlgg`` for governance work.
    - ``mlgg-review <unknown-or-governance-cmd>`` → emit a clear error
      naming the allowed subset and exit 2 (argparse-style usage error).

    The shim never re-implements dispatch; it gates argv and delegates
    to :func:`main` so every flag, env-var, subcommand semantic, and
    error-mode stays identical between the two entry points.
    """
    argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        lines = [
            "mlgg-review — focused entry point for the MLGG review product line",
            "  (Mode B/C: audits SOMEONE ELSE's code/paper; no evidence/*.json required).",
            "",
            "Allowed subcommands (the same scripts as `mlgg <cmd>`):",
        ]
        for name in COMMAND_GROUPS["review"]:
            desc = COMMANDS.get(name, (None, ""))[1]
            lines.append(f"  - {name}: {desc}")
        lines.extend([
            "",
            "For governance / training-pipeline commands (workflow / strict / train / etc.),",
            "use the full `mlgg` entry point. See `mlgg --help` or docs/PRODUCTS.md.",
        ])
        print("\n".join(lines))
        raise SystemExit(0)

    cmd = argv[0]
    if cmd not in _REVIEW_ALLOWED:
        allowed = ", ".join(sorted(_REVIEW_ALLOWED))
        msg = (
            f"mlgg-review: subcommand {cmd!r} is not part of the review product line.\n"
            f"  Allowed: {allowed}\n"
            f"  For governance commands (e.g. workflow / strict / train), use `mlgg {cmd} ...` instead.\n"
            f"  See docs/PRODUCTS.md for the two-product-line split."
        )
        print(msg, file=sys.stderr)
        raise SystemExit(2)

    # Delegate: leave sys.argv untouched (main() reads it via build_parser()).
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
