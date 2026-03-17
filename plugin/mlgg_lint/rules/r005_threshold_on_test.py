"""R005: Classification threshold/cutoff selected using test data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, get_call_first_arg_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_THRESHOLD_CALLS = {
    "roc_curve",
    "precision_recall_curve",
    "sklearn.metrics.roc_curve",
    "sklearn.metrics.precision_recall_curve",
}


@register
class ThresholdOnTest(BaseRule):
    id = "R005"
    name = "threshold-on-test"
    severity = Severity.ERROR
    description = (
        "Threshold/cutoff selection performed using test data (via roc_curve or "
        "precision_recall_curve). Thresholds must be selected on training or "
        "validation data only."
    )
    remediation = (
        "Select the operating threshold on the validation set, not the test set. "
        "The test set should only be used for final, unbiased evaluation."
    )
    tags = ("leakage", "evaluation")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _THRESHOLD_CALLS):
            self.generic_visit(node)
            return

        arg_name = get_call_first_arg_name(node)
        if arg_name and self.taint.is_test_or_valid(arg_name):
            # Check if the result is used for threshold selection
            # (being assigned to something with "threshold" in name)
            parent = self._find_assign_parent(node)
            if parent:
                self.report(
                    node,
                    f"`{fqn.rsplit('.', 1)[-1]}()` called with test/validation data "
                    f"`{arg_name}`. If this is used to select an operating threshold, "
                    f"it leaks test information into model decisions.",
                )
        self.generic_visit(node)

    @staticmethod
    def _find_assign_parent(node: ast.Call) -> bool:
        """Heuristic: we always flag — if roc_curve is called on test data,
        the user is likely selecting thresholds from it."""
        return True
