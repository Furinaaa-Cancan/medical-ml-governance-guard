"""R027: Manual scaling/normalization on full data before split.

Catches patterns that R001/R002 miss because they only look for sklearn API:
  - X = (X - X.mean()) / X.std()          # z-score
  - X = (X - np.min(X)) / (np.max(X) - np.min(X))  # min-max
  - X = StandardScaler().fit_transform(X)  # sklearn but on full data
  - preprocessing.scale(X)                 # sklearn.preprocessing.scale
  - preprocessing.normalize(X)
"""
from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

# Functions that scale/normalize full data in-place or return scaled data
_SCALE_FUNCTIONS = {
    "scale", "normalize", "minmax_scale", "maxabs_scale",
    "robust_scale", "power_transform", "quantile_transform",
}


@register
class ManualScalingBeforeSplit(BaseRule):
    id = "R027"
    name = "manual-scaling-before-split"
    severity = Severity.ERROR
    description = (
        "Manual scaling or normalization applied to full data before "
        "train/test split. The scaling parameters (mean, std, min, max) "
        "are computed from the entire dataset, leaking test distribution."
    )
    remediation = (
        "Split data first, then fit scaler on training set only. "
        "Use StandardScaler/MinMaxScaler inside a Pipeline."
    )
    tags = ("leakage", "preprocessing", "scaling")

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Detect: X = (X - X.mean()) / X.std()"""
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # Pattern: X = (X - X.mean()) / X.std()
        # This is BinOp(Div) with left=BinOp(Sub) containing .mean(), right containing .std()
        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div):
            if self._contains_stat_call(node.value):
                self.report(
                    node,
                    f"Manual normalization before split at line "
                    f"{self.taint.split_line} — scaling parameters computed "
                    f"from full data leak test distribution.",
                )

        # Pattern: X = (X - np.min(X)) / (np.max(X) - np.min(X))
        # Also caught by the above check since np.min/np.max are stat calls

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect: preprocessing.scale(X), preprocessing.normalize(X)"""
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # Get function name from AST
        func = node.func
        if isinstance(func, ast.Attribute):
            func_name = func.attr
        elif isinstance(func, ast.Name):
            func_name = func.id
        else:
            self.generic_visit(node)
            return

        if func_name in _SCALE_FUNCTIONS:
            self.report(
                node,
                f"`{func_name}()` before split at line {self.taint.split_line} — "
                f"scaling on full data leaks test distribution.",
            )

        self.generic_visit(node)

    def _contains_stat_call(self, node: ast.AST) -> bool:
        """Recursively check if an expression contains .mean()/.std()/.min()/.max()."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("mean", "std", "var", "min", "max",
                                   "median", "quantile"):
                return True
        for child in ast.iter_child_nodes(node):
            if self._contains_stat_call(child):
                return True
        return False
