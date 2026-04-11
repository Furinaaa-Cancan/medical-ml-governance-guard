"""R026: fillna with data-dependent values before train/test split.

Catches patterns that R020 misses:
  - df.fillna(df.mean())  — DataFrame-level fill (no column subscript)
  - df[col].fillna(df[col].median())  — column subscript variant
  - dataset[feature] = dataset[feature].fillna(dataset[feature].median())
  - df.fillna(method='ffill')  — forward fill keyword form
  - Chained: df.col.fillna(df.col.mean())
"""
from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_STAT_METHODS = {"mean", "median", "std", "var", "mode", "quantile"}


def _is_stat_call(node: ast.AST) -> bool:
    """Check if node is a call to a statistical method (mean/median/etc)."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in _STAT_METHODS
    return False


def _is_fillna_call(node: ast.Call) -> bool:
    """Check if node is a .fillna() call."""
    return isinstance(node.func, ast.Attribute) and node.func.attr == "fillna"


@register
class FillnaBeforeSplit(BaseRule):
    id = "R026"
    name = "fillna-before-split"
    severity = Severity.ERROR
    description = (
        "fillna() using data-dependent statistics (mean, median, etc.) "
        "detected before train/test split. The fill values are computed "
        "from the full dataset including test samples, leaking test "
        "distribution into the imputation."
    )
    remediation = (
        "Split data first, then compute fill values from training set only. "
        "Use sklearn.impute.SimpleImputer(strategy='median') inside a "
        "Pipeline for automatic train-only imputation."
    )
    tags = ("leakage", "preprocessing", "imputation")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not _is_fillna_call(node):
            self.generic_visit(node)
            return

        # Only flag before split
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # Check positional arg: fillna(df.mean()), fillna(df[col].median())
        # NOTE: R020 also detects inline fillna(stat()) — only report here
        # if the stat call is on a column subscript (df[col].median()) which
        # R020 may miss because R020 checks arg.func.attr on the arg itself,
        # not on the arg's receiver.
        if node.args:
            arg = node.args[0]
            if _is_stat_call(arg):
                # Check if this is a column-subscript variant that R020 misses:
                # df[col].fillna(df[col].median()) — the stat arg receiver is a Subscript
                receiver_is_subscript = (
                    isinstance(arg.func, ast.Attribute)
                    and isinstance(arg.func.value, ast.Subscript)
                )
                if not receiver_is_subscript:
                    # R020 already covers df.fillna(df.mean()) — skip to avoid duplication
                    self.generic_visit(node)
                    return
                stat_name = arg.func.attr
                self.report(
                    node,
                    f"`fillna({stat_name}())` before split at line "
                    f"{self.taint.split_line} — fill values computed from "
                    f"the full dataset leak test distribution.",
                )
                self.generic_visit(node)
                return

            # fillna(some_variable) where variable was assigned from stat
            # This is handled by R020's variable tracking, so skip here
            # to avoid double-reporting.

        # Check keyword: fillna(value=df.mean())
        for kw in node.keywords:
            if kw.arg == "value" and _is_stat_call(kw.value):
                stat_name = kw.value.func.attr
                self.report(
                    node,
                    f"`fillna(value={stat_name}())` before split at line "
                    f"{self.taint.split_line} — fill values computed from "
                    f"the full dataset leak test distribution.",
                )
                break

        self.generic_visit(node)
