"""R023: Target encoding leakage via groupby().transform() on label column.

Detects patterns like:
    df["feature"] = df.groupby("col")["label"].transform("mean")
which computes target statistics on the full dataset before split.
"""

from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_TARGET_HINTS = ("label", "target", "outcome", "y", "died", "death",
                 "mortality", "readmit", "readmission", "sepsis",
                 "diagnosis", "positive", "event")

_STAT_METHODS = ("mean", "std", "median", "sum", "count", "var")


@register
class TargetEncodingLeak(BaseRule):
    id = "R023"
    name = "target-encoding-leak"
    severity = Severity.ERROR
    description = (
        "Target encoding detected: groupby().transform() applied to a column "
        "that appears to be the label/outcome. Computing target statistics on "
        "the full dataset before split leaks label information into features."
    )
    remediation = (
        "If target encoding is needed, compute statistics on training set only "
        "(e.g., using category_encoders.TargetEncoder inside a Pipeline), or "
        "use leave-one-out target encoding with proper CV."
    )
    tags = ("leakage", "feature_engineering")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Pattern: df.groupby(X)[Y].transform(Z)
        # AST: Call(func=Attr(value=Subscript(value=Call(func=Attr(attr="groupby")), attr="transform")))
        # Or: Call(func=Attr(value=Call(func=Attr(value=Subscript(...), attr="transform"))))

        # Detect .transform("mean") etc
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "transform"):
            self.generic_visit(node)
            return

        # Check if transform arg is a stat method
        stat_method = None
        if node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str) and node.args[0].value in _STAT_METHODS:
                stat_method = node.args[0].value

        if stat_method is None:
            self.generic_visit(node)
            return

        # Walk up to find if there's a subscript with a target-like column
        # Pattern: .groupby(...)["label"].transform("mean")
        chain = node.func.value  # what .transform is called on
        target_col = self._find_target_subscript(chain)

        if target_col:
            self.report(
                node,
                f'`groupby(...)["{target_col}"].transform("{stat_method}")` — '
                f'target encoding on label column "{target_col}" leaks outcome '
                f'information into features. Compute on training set only.',
            )
        self.generic_visit(node)

    @staticmethod
    def _find_target_subscript(node: ast.expr) -> str | None:
        """Check if node is a subscript like df.groupby(...)["label"]."""
        if isinstance(node, ast.Subscript):
            # Get the subscript key
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                col = sl.value.lower()
                if any(h in col for h in _TARGET_HINTS):
                    return sl.value
        return None
