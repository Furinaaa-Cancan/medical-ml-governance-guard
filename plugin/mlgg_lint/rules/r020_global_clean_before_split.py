"""R020: Data cleaning using global statistics before split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_GLOBAL_STAT_METHODS = {"mean", "median", "std", "var", "mode", "quantile", "describe"}
_FILL_METHODS = {"fillna", "replace", "interpolate"}


@register
class GlobalCleanBeforeSplit(BaseRule):
    id = "R020"
    name = "global-clean-before-split"
    severity = Severity.WARNING
    description = (
        "Data cleaning (fillna, replace) using global statistics (mean, median) "
        "applied before train/test split. Global statistics computed on the full "
        "dataset leak test distribution into the cleaning process."
    )
    remediation = (
        "Compute fill values on training data only after splitting. "
        "Use sklearn.impute.SimpleImputer inside a Pipeline for automatic "
        "train-only imputation."
    )
    tags = ("leakage", "preprocessing")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track variables that hold global statistics
        self._global_stat_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track: mean_val = df['col'].mean()"""
        if isinstance(node.value, ast.Call):
            method = is_method_call(node.value, None)  # won't match, check manually
            if isinstance(node.value.func, ast.Attribute):
                if node.value.func.attr in _GLOBAL_STAT_METHODS:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._global_stat_vars.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect: df.fillna(df.mean()) or df.fillna(mean_val) before split."""
        if not isinstance(node.func, ast.Attribute):
            self.generic_visit(node)
            return
        if node.func.attr not in _FILL_METHODS:
            self.generic_visit(node)
            return

        # Only flag if before split
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # Check: fillna(df.mean()) — arg is a method call with global stat
        if node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                if arg.func.attr in _GLOBAL_STAT_METHODS:
                    self.report(
                        node,
                        f"`{node.func.attr}({arg.func.attr}())` before split — "
                        f"global statistics leak test distribution into cleaning.",
                    )
            elif isinstance(arg, ast.Name) and arg.id in self._global_stat_vars:
                self.report(
                    node,
                    f"`{node.func.attr}({arg.id})` before split — "
                    f"`{arg.id}` was computed from the full dataset.",
                )
        self.generic_visit(node)
