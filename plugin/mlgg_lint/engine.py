"""Core analysis engine — parse files, run rules, collect diagnostics."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence

from mlgg_lint.ast_utils import ImportMap, TaintTracker, build_import_map
from mlgg_lint.config import LintConfig, load_config
from mlgg_lint.models import Diagnostic, Location, Severity
from mlgg_lint.notebook import CellMapping, extract_notebook_source, map_line_to_cell
from mlgg_lint.rules import get_enabled_rules

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
    # CV/KFold calls also imply a split boundary — any preprocessing before
    # these calls applies to the full dataset.
    cv_calls = {
        "cross_val_score", "cross_validate", "cross_val_predict",
        "sklearn.model_selection.cross_val_score",
        "sklearn.model_selection.cross_validate",
        "sklearn.model_selection.cross_val_predict",
    }


    def _unwrap_call(value: ast.AST) -> ast.Call | None:
        """Unwrap Call from Subscript (e.g. train_test_split(...)[0])."""
        if isinstance(value, ast.Call):
            return value
        if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Call):
            return value.value
        return None

    # Pass 1: explicit splits (train_test_split, for-loop kf.split)
    for node in ast.walk(tree):
        # Pattern 1: X_train, X_test, ... = train_test_split(...)
        #         or: indices = train_test_split(...)[0]
        if isinstance(node, ast.Assign):
            call_node = _unwrap_call(node.value)
            if call_node is not None:
                fqn = call_name(call_node, im)
                if fqn and matches_any(fqn, split_calls):
                    for target in node.targets:
                        names = extract_tuple_targets(target)
                        tracker.record_split(names, node.lineno)

        # Pattern 2: for train_idx, test_idx in kf.split(X):
        # Guard: require tuple unpacking (≥2 vars) to distinguish from
        # str.split() which iterates single values.
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
            if isinstance(node.iter.func, ast.Attribute):
                if node.iter.func.attr == "split":
                    if isinstance(node.target, ast.Tuple) and len(node.target.elts) >= 2:
                        names = extract_tuple_targets(node.target)
                        tracker.record_split(names, node.lineno)

    # Pass 2: cross_val_score/cross_validate as fallback split markers
    # Only if no explicit split was found — avoids false positives when
    # CV is used on an already-split training set.
    if tracker.split_line is None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.Expr)):
                call_node = node.value if isinstance(node, ast.Assign) else node.value
                if isinstance(call_node, ast.Call):
                    fqn = call_name(call_node, im)
                    if fqn and matches_any(fqn, cv_calls):
                        tracker.record_split([], node.lineno)
                        break  # only need the first one

    # Pass 3: propagate taint through simple assignments.
    # Handles ``data = X_test`` → data gets test taint.
    # Only propagates from already-tainted variables (single level).
    from mlgg_lint.ast_utils import classify_var_name
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            val = node.value
            # Resolve source taint from the RHS
            src_taint = None
            if isinstance(val, ast.Name):
                src_taint = tracker.get_taint(val.id)
                if src_taint is None:
                    src_taint = classify_var_name(val.id)
            elif isinstance(val, ast.Subscript) and isinstance(val.value, ast.Name):
                src_taint = tracker.get_taint(val.value.id)

            if src_taint:
                # Propagate to ALL targets (handles `a = b = X_test`)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        tracker.record_assignment(target.id, src_taint)

    return tracker


def _display_path(file_path: Path) -> str:
    """Return a relative path for display if possible, to avoid leaking
    absolute paths (e.g. /Users/...) in SARIF/JSON output."""
    try:
        return str(file_path.relative_to(Path.cwd()))
    except ValueError:
        return str(file_path)


def analyze_file(
    file_path: Path,
    config: Optional[LintConfig] = None,
) -> List[Diagnostic]:
    """Analyze a single Python or notebook file and return all diagnostics."""
    if config is None:
        config = load_config(start=file_path)

    is_notebook = file_path.suffix == ".ipynb"

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
                location=Location(file=_display_path(file_path), line=0, col=0),
            )
        ]
    if file_size > _MAX_FILE_BYTES:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="file-too-large",
                severity=Severity.ERROR,
                message=f"File exceeds {_MAX_FILE_BYTES // (1024 * 1024)} MB limit ({file_size} bytes).",
                location=Location(file=_display_path(file_path), line=0, col=0),
            )
        ]

    cell_mappings: List[CellMapping] = []

    if is_notebook:
        source, cell_mappings = extract_notebook_source(file_path)
        if not source:
            return [
                Diagnostic(
                    rule_id="E000",
                    rule_name="notebook-parse-error",
                    severity=Severity.ERROR,
                    message="Cannot parse notebook (malformed JSON or nbformat < 4).",
                    location=Location(file=_display_path(file_path), line=0, col=0),
                )
            ]
    else:
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [
                Diagnostic(
                    rule_id="E000",
                    rule_name="parse-error",
                    severity=Severity.ERROR,
                    message=f"Cannot read file: {exc}",
                    location=Location(file=_display_path(file_path), line=0, col=0),
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
                    file=_display_path(file_path),
                    line=exc.lineno or 0,
                    col=max((exc.offset or 1) - 1, 0),  # F2: offset is 1-based
                ),
            )
        ]

    try:
        im = build_import_map(tree)
        taint = _build_taint_tracker(tree, im)
    except RecursionError:
        return [
            Diagnostic(
                rule_id="E000",
                rule_name="recursion-limit",
                severity=Severity.ERROR,
                message="AST too deeply nested (possible adversarial input). Skipping analysis.",
                location=Location(file=_display_path(file_path), line=0, col=0),
            )
        ]
    noqa_map = _build_noqa_map(source)

    threshold = SEVERITY_ORDER.get(config.severity_threshold, 2)
    diagnostics: List[Diagnostic] = []
    display = _display_path(file_path)

    rule_classes = get_enabled_rules(disabled=config.disabled_rules)
    for rule_cls in rule_classes:
        rule = rule_cls(
            file_path=display,
            import_map=im,
            taint_tracker=taint,
        )
        try:
            found = rule.check(tree)
        except RecursionError:
            found = [
                Diagnostic(
                    rule_id=rule_cls.id,
                    rule_name=f"{rule_cls.name}-recursion",
                    severity=Severity.ERROR,
                    message=f"Rule {rule_cls.id} hit recursion limit on deeply nested AST.",
                    location=Location(file=display, line=0, col=0),
                )
            ]
        for diag in found:
            if SEVERITY_ORDER.get(str(diag.severity), 2) <= threshold:
                if not _is_suppressed(diag.location.line, diag.rule_id, noqa_map):
                    if is_notebook and cell_mappings:
                        diag = _remap_notebook_location(diag, display, cell_mappings)
                    diagnostics.append(diag)

    diagnostics.sort(key=lambda d: (d.location.line, d.location.col))
    return diagnostics


def _remap_notebook_location(
    diag: Diagnostic, display: str, mappings: List[CellMapping]
) -> Diagnostic:
    """Rewrite diagnostic location to include cell reference."""
    cell_info = map_line_to_cell(diag.location.line, mappings)
    if cell_info is not None:
        cell_idx, cell_line = cell_info
        new_file = f"{display}[cell {cell_idx}]"
        new_loc = Location(
            file=new_file,
            line=cell_line,
            col=diag.location.col,
            end_line=diag.location.end_line,
            end_col=diag.location.end_col,
        )
        return Diagnostic(
            rule_id=diag.rule_id,
            rule_name=diag.rule_name,
            severity=diag.severity,
            message=diag.message,
            location=new_loc,
            remediation=diag.remediation,
            details=diag.details,
        )
    return diag


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


_SUPPORTED_SUFFIXES = {".py", ".ipynb"}


def _collect_python_files(paths: Sequence[str | Path]) -> List[Path]:
    """Expand directories into .py/.ipynb files, skip hidden/venv."""
    result: List[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix in _SUPPORTED_SUFFIXES:
            result.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.suffix not in _SUPPORTED_SUFFIXES:
                    continue
                # Skip hidden dirs, venvs, __pycache__, symlinks
                if child.is_symlink():
                    continue
                parts = child.relative_to(p).parts
                if any(
                    part.startswith(".")
                    or part in (
                        "__pycache__", "node_modules",
                        "venv", ".venv", "env", ".env",
                        "site-packages", ".tox", ".nox",
                    )
                    for part in parts
                ):
                    continue
                result.append(child)
    return result
