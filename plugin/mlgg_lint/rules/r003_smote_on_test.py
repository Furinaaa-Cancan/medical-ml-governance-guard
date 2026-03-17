"""R003: SMOTE/oversampling applied to test or validation data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, get_call_first_arg_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_RESAMPLERS = {
    "SMOTE", "ADASYN", "BorderlineSMOTE", "SVMSMOTE",
    "RandomOverSampler", "RandomUnderSampler", "SMOTEENN",
    "SMOTETomek", "NearMiss", "EditedNearestNeighbours",
}


@register
class SmoteOnTest(BaseRule):
    id = "R003"
    name = "resample-on-test"
    severity = Severity.ERROR
    description = (
        "Resampling (SMOTE/oversampling/undersampling) applied to "
        "validation or test data. Resampling must only be applied to training data."
    )
    remediation = (
        "Only apply SMOTE/resampling to the training split. "
        "Never resample validation or test sets — they must reflect real distribution."
    )
    tags = ("leakage", "imbalance")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Check fit_resample calls
        obj = is_method_call(node, "fit_resample")
        if obj is not None:
            arg_name = get_call_first_arg_name(node)
            if arg_name and self.taint.is_test_or_valid(arg_name):
                self.report(
                    node,
                    f"`{obj}.fit_resample({arg_name}, ...)` — resampling applied "
                    f"to holdout data. This inflates holdout metrics artificially.",
                )
        self.generic_visit(node)
