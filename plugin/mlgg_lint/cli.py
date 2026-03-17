"""CLI entrypoint: ``mlgg-lint check [OPTIONS] PATH...``"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from mlgg_lint import __version__
from mlgg_lint.config import LintConfig, load_config
from mlgg_lint.engine import analyze_paths
from mlgg_lint.formatters import format_json, format_sarif, format_text
from mlgg_lint.models import Severity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlgg-lint",
        description=(
            "Static analysis for ML code — detects data leakage, "
            "improper preprocessing, and evaluation malpractice."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"mlgg-lint {__version__}")

    sub = parser.add_subparsers(dest="command")

    # ── check ─────────────────────────────────────────────────────────
    check_p = sub.add_parser(
        "check",
        help="Analyze Python files for ML best-practice violations.",
    )
    check_p.add_argument(
        "paths",
        nargs="+",
        help="Files or directories to analyze.",
    )
    check_p.add_argument(
        "--format", "-f",
        choices=["text", "json", "sarif"],
        default="text",
        dest="output_format",
        help="Output format (default: text).",
    )
    check_p.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with code 1 if any error-severity diagnostics found.",
    )
    check_p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to .mlgg-lint.toml config file.",
    )
    check_p.add_argument(
        "--disable",
        default="",
        help="Comma-separated rule IDs to disable (e.g., R004,R008).",
    )
    check_p.add_argument(
        "--severity",
        choices=["error", "warning", "info"],
        default="info",
        help="Minimum severity to report (default: info).",
    )
    check_p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output.",
    )

    # ── rules ─────────────────────────────────────────────────────────
    sub.add_parser(
        "rules",
        help="List all available rules.",
    )

    return parser


def cmd_check(args: argparse.Namespace) -> int:
    """Execute the check subcommand."""
    # Build config
    if args.config:
        config = load_config(path=args.config)
    elif args.paths:
        config = load_config(start=Path(args.paths[0]))
    else:
        config = LintConfig()

    # Apply CLI overrides
    if args.disable:
        for rid in args.disable.split(","):
            config.disabled_rules.add(rid.strip().upper())
    config.severity_threshold = args.severity

    # Run analysis
    diagnostics = analyze_paths(args.paths, config=config)

    # Format output
    if args.output_format == "json":
        print(format_json(diagnostics))
    elif args.output_format == "sarif":
        print(format_sarif(diagnostics))
    else:
        color = not args.no_color
        print(format_text(diagnostics, color=color))

    # Exit code
    if args.exit_code:
        has_errors = any(d.severity == Severity.ERROR for d in diagnostics)
        return 1 if has_errors else 0
    return 0


def cmd_rules() -> int:
    """List all available rules."""
    from mlgg_lint.rules import get_all_rules

    all_rules = get_all_rules()
    for rid, cls in sorted(all_rules.items()):
        sev = str(cls.severity).upper()
        tags = ", ".join(cls.tags) if cls.tags else ""
        print(f"  {rid:6s}  [{sev:7s}]  {cls.name:30s}  {tags}")
        if cls.description:
            # Wrap description
            desc = cls.description
            if len(desc) > 100:
                desc = desc[:97] + "..."
            print(f"          {desc}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return cmd_check(args)
    elif args.command == "rules":
        return cmd_rules()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
