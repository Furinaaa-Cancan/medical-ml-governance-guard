"""R020: Data cleaning using global statistics before split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_GLOBAL_STAT_METHODS = {"mean", "median", "std", "var", "mode", "quantile", "describe"}
_FILL_METHODS = {"fillna", "replace", "interpolate"}
_TEMPORAL_FILL_METHODS = {"ffill", "bfill", "pad", "backfill"}
_STAT_CLEAN_METHODS = {"clip", "dropna"}


@register
class GlobalCleanBeforeSplit(BaseRule):
    id = "R020"
    name = "global-clean-before-split"
    severity = Severity.WARNING
    description = (
        "Data cleaning (fillna, replace, ffill, bfill) using global statistics "
        "(mean, median) or temporal propagation applied before train/test split. "
        "Global statistics and forward/backward fills computed on the full "
        "dataset leak test distribution into the cleaning process."
    )
    remediation = (
        "Compute fill values on training data only after splitting. "
        "Use sklearn.impute.SimpleImputer inside a Pipeline for automatic "
        "train-only imputation. For temporal fills, apply ffill/bfill within "
        "each split independently."
    )
    tags = ("leakage", "preprocessing")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track variables that hold global statistics
        self._global_stat_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track: mean_val = df['col'].mean()"""
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute):
                if node.value.func.attr in _GLOBAL_STAT_METHODS:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._global_stat_vars.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect: df.fillna(df.mean()), df.dropna(), df.clip(quantile()) before split."""
        if not isinstance(node.func, ast.Attribute):
            self.generic_visit(node)
            return

        method = node.func.attr

        # Only flag if before split
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # --- fillna / replace / interpolate with global stats ---
        if method in _FILL_METHODS:
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                    if arg.func.attr in _GLOBAL_STAT_METHODS:
                        self.report(
                            node,
                            f"`{method}({arg.func.attr}())` before split — "
                            f"global statistics leak test distribution into cleaning.",
                        )
                elif isinstance(arg, ast.Name) and arg.id in self._global_stat_vars:
                    self.report(
                        node,
                        f"`{method}({arg.id})` before split — "
                        f"`{arg.id}` was computed from the full dataset.",
                    )

        # --- dropna before split (removes rows using global missingness pattern) ---
        # Exceptions:
        # - dropna(subset=[...]) = legitimate exclusion criteria
        # - dropna(axis=1) or dropna(axis='columns') = column schema cleanup, not leakage
        elif method == "dropna":
            has_subset = any(kw.arg == "subset" for kw in node.keywords)
            has_axis_col = any(
                kw.arg == "axis" and isinstance(kw.value, ast.Constant)
                and kw.value.value in (1, "columns")
                for kw in node.keywords
            )
            if not has_subset and not has_axis_col:
                self.report(
                    node,
                    f"`dropna()` before split at line {self.taint.split_line} — "
                    f"row removal based on full-data missingness pattern leaks "
                    f"information about test distribution.",
                )

        # --- ffill / bfill before split (propagates values across train/test boundary) ---
        elif method in _TEMPORAL_FILL_METHODS:
            self.report(
                node,
                f"`{method}()` before split — forward/backward fill propagates "
                f"values across the train/test boundary, leaking future or test "
                f"distribution information into training rows.",
            )

        # --- clip with quantile-based bounds before split ---
        elif method == "clip":
            # Check if any keyword arg uses .quantile()
            for kw in node.keywords:
                if kw.arg in ("lower", "upper") and isinstance(kw.value, ast.Call):
                    if isinstance(kw.value.func, ast.Attribute):
                        if kw.value.func.attr in _GLOBAL_STAT_METHODS | {"quantile"}:
                            self.report(
                                node,
                                f"`clip({kw.arg}={kw.value.func.attr}())` before split — "
                                f"clip bounds computed from full data leak test distribution.",
                            )
                            break

        self.generic_visit(node)
