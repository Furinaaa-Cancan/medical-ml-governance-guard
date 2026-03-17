"""Core analysis engine — parse files, run rules, collect diagnostics."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set

from mlgg_lint.ast_utils import ImportMap, TaintTracker, build_import_map
from mlgg_lint.config import LintConfig, load_config
from mlgg_lint.models import Diagnostic, Location, Severity
from mlgg_lint.rules import get_enabled_rules
from mlgg_lint.rules.base import BaseRule

# Maximum file size to analyze (16 MB).  Prevents memory exhaustion from
# adversarial or accidentally huge .py files.
_MAX_FILE_BYTES = 16 * 1024 * 1024

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# Regex for ``# noqa: R001,R002`` or bare ``# noqa`` (suppress all)
_NOQA_RE = re.compile(r"#\s*noqa\b(?:\s*:\s*([A-Za-z0-9,\s]+))?", re.IGNORECASE)


def _build_noqa_map(source: str) -> Dict[int, FrozenSet[str] | None]:
    """Parse ``# noqa`` comments from source lines.

    Returns a dict of ``{line_number: frozenset_of_rule_ids}`` or
    ``{line_number: None}`` when all rules are suppressed (bare ``# noqa``).
    """
    noqa: Dict[int, FrozenSet[str] | None] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _NOQA_RE.search(line)
        if m:
            codes_str = m.group(1)
            if codes_str:
                codes = frozenset(c.strip().upper() for c in codes_str.split(",") if c.strip())
                noqa[lineno] = codes
            else:
                noqa[lineno] = None  # suppress all
    return noqa


def _is_suppressed(
    diag_line: int, rule_id: str, noqa_map: Dict[int, FrozenSet[str] | None]
) -> bool:
    """Check if a diagnostic is suppressed by a noqa comment on its line."""
    if diag_line not in noqa_map:
        return False
    suppressed = noqa_map[diag_line]
    if suppressed is None:
        return True  # bare # noqa
    return rule_id.upper() in suppressed


def _build_taint_tracker(tree: ast.Module, im: ImportMap) -> TaintTracker:
    """Pre-scan the AST to populate the taint tracker with split info."""
    from mlgg_lint.ast_utils import (
        call_name,
        extract_tuple_targets,
        matches_any,
    )

    tracker = TaintTracker()
    split_calls = {"train_test_split", "sklearn.model_selection.train_test_split"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        fqn = call_name(node.value, im)
        if fqn and matches_any(fqn, split_calls):
            for target in node.targets:
                names = extract_tuple_targets(target)
                tracker.record_split(names, node.lineno)

    return tracker


def analyze_file(
    file_path: Path,
    config: Optional[LintConfig] = None,
) -> List[Diagnostic]:
    """Analyze a single Python file and return all diagnostics."""
    if config is None:
        config = load_config(start=file_path)

    # Guard against oversized files; treat stat errors as unreadable
    try:
        stat = file_path.stat()
        file_size = stat.st_size
    except OSError as exc:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="file-unreadable",
                severity=Severity.ERROR,
                message=f"Cannot stat file: {exc}",
                location=Location(file=str(file_path), line=0, col=0),
            )
        ]
    if file_size > _MAX_FILE_BYTES:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="file-too-large",
                severity=Severity.ERROR,
                message=f"File exceeds {_MAX_FILE_BYTES // (1024 * 1024)} MB limit ({file_size} bytes).",
                location=Location(file=str(file_path), line=0, col=0),
            )
        ]

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="parse-error",
                severity=Severity.ERROR,
                message=f"Cannot read file: {exc}",
                location=Location(file=str(file_path), line=0, col=0),
            )
        ]

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="parse-error",
                severity=Severity.ERROR,
                message=f"Syntax error: {exc.msg}",
                location=Location(
                    file=str(file_path),
                    line=exc.lineno or 0,
                    col=max((exc.offset or 1) - 1, 0),  # F2: offset is 1-based
                ),
            )
        ]

    im = build_import_map(tree)
    taint = _build_taint_tracker(tree, im)
    noqa_map = _build_noqa_map(source)

    threshold = SEVERITY_ORDER.get(config.severity_threshold, 2)
    diagnostics: List[Diagnostic] = []

    rule_classes = get_enabled_rules(disabled=config.disabled_rules)
    for rule_cls in rule_classes:
        rule = rule_cls(
            file_path=str(file_path),
            import_map=im,
            taint_tracker=taint,
        )
        found = rule.check(tree)
        for diag in found:
            if SEVERITY_ORDER.get(str(diag.severity), 2) <= threshold:
                if not _is_suppressed(diag.location.line, diag.rule_id, noqa_map):
                    diagnostics.append(diag)

    diagnostics.sort(key=lambda d: (d.location.line, d.location.col))
    return diagnostics


def analyze_paths(
    paths: Sequence[str | Path],
    config: Optional[LintConfig] = None,
) -> List[Diagnostic]:
    """Analyze multiple files/directories."""
    all_diags: List[Diagnostic] = []
    files = _collect_python_files(paths)
    for fpath in files:
        all_diags.extend(analyze_file(fpath, config=config))
    return all_diags


def _collect_python_files(paths: Sequence[str | Path]) -> List[Path]:
    """Expand directories into .py files, skip hidden/venv."""
    result: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix == ".py":
            result.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*.py")):
                # Skip hidden dirs, venvs, __pycache__, symlinks
                if child.is_symlink():
                    continue
                parts = child.relative_to(p).parts
                if any(
                    part.startswith(".") or part in ("__pycache__", "node_modules")
                    for part in parts
                ):
                    continue
                result.append(child)
    return result
