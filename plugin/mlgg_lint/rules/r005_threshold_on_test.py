"""R005: Classification threshold/cutoff selected using test data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, classify_var_name, get_call_first_arg_name, matches_any
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
        "precision_recall_curve). Thresholds should be selected on training or "
        "validation data, not on the test set."
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
        if not arg_name:
            self.generic_visit(node)
            return

        # F5: Only flag test data, NOT validation (threshold selection on
        # validation is the recommended practice).
        taint = self.taint.get_taint(arg_name)
        if taint is None:
            taint = classify_var_name(arg_name)
        if taint == "test":
            self.report(
                node,
                f"`{fqn.rsplit('.', 1)[-1]}({arg_name})` — threshold/cutoff "
                f"curve computed on test data. If used to select an operating "
                f"threshold, this leaks test information into model decisions.",
            )
        self.generic_visit(node)
