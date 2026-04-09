"""R024: Frequency encoding on full data before split.

Detects patterns like:
    freq = df[col].value_counts(normalize=True)
    df[col + "_freq"] = df[col].map(freq)
which computes category frequencies on the full dataset before split.
"""

from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


@register
class FrequencyEncodingLeak(BaseRule):
    id = "R024"
    name = "frequency-encoding-leak"
    severity = Severity.WARNING
    description = (
        "Frequency or count encoding computed on the full dataset before split. "
        "Category frequencies differ between train and test; using full-data "
        "frequencies leaks test distribution into training features."
    )
    remediation = (
        "Compute value_counts() on training data only after splitting, "
        "then map to both train and test. Unknown categories in test "
        "should be assigned a default frequency (e.g., 0 or global mean)."
    )
    tags = ("leakage", "feature_engineering")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._freq_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track: freq = df[col].value_counts(...)"""
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute):
                if node.value.func.attr in ("value_counts", "nunique"):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._freq_vars.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect: df[col].map(freq) before split where freq is full-data counts."""
        if not isinstance(node.func, ast.Attribute):
            self.generic_visit(node)
            return

        method = node.func.attr
        if method != "map":
            self.generic_visit(node)
            return

        # Only flag before split
        if self.taint.has_split_occurred(node.lineno):
            self.generic_visit(node)
            return
        if self.taint.split_line is None:
            self.generic_visit(node)
            return

        # Check if map argument is a freq variable or inline value_counts
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id in self._freq_vars:
                self.report(
                    node,
                    f"`.map({arg.id})` before split — `{arg.id}` contains "
                    f"category frequencies computed on the full dataset. "
                    f"Compute frequencies on training set only.",
                )
                break
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                if arg.func.attr in ("value_counts",):
                    self.report(
                        node,
                        f"`.map(value_counts())` before split — "
                        f"frequency encoding using full-data category counts.",
                    )
                    break
        self.generic_visit(node)
