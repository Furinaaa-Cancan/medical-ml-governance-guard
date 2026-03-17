"""R013: Hardcoded classification threshold 0.5."""

from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


@register
class HardcodedThreshold(BaseRule):
    id = "R013"
    name = "hardcoded-threshold"
    severity = Severity.WARNING
    description = (
        "Classification threshold hardcoded to 0.5. For medical prediction, "
        "the optimal threshold depends on the cost of false positives vs "
        "false negatives and should be tuned on the validation set."
    )
    remediation = (
        "Tune the classification threshold on the validation set using "
        "roc_curve or precision_recall_curve. Never hardcode 0.5 for "
        "clinical decision-making."
    )
    tags = ("evaluation", "clinical")

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        """Detect patterns like: y_pred = (y_prob > 0.5).astype(int)"""
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and comparator.value == 0.5:
                # Check if left side looks like probability
                left_name = self._get_name(node.left)
                if left_name and any(h in left_name.lower() for h in
                                     ("prob", "proba", "score", "pred")):
                    self.report(
                        node,
                        f"Threshold hardcoded to 0.5 on `{left_name}`. "
                        f"Tune the threshold on validation data for optimal "
                        f"sensitivity/specificity tradeoff.",
                    )
        self.generic_visit(node)

    @staticmethod
    def _get_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            return node.value.id
        return None
