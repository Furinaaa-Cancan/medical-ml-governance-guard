"""R010: Training-set metrics presented as final evaluation results."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, get_call_first_arg_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_METRIC_CALLS = {
    "accuracy_score", "roc_auc_score", "f1_score", "precision_score",
    "recall_score", "average_precision_score", "brier_score_loss",
    "log_loss", "classification_report", "confusion_matrix",
}


@register
class TrainMetricAsFinal(BaseRule):
    id = "R010"
    name = "train-metric-as-final"
    severity = Severity.WARNING
    description = (
        "Evaluation metric computed on training data. Training metrics are "
        "optimistically biased and must not be reported as final results."
    )
    remediation = (
        "Always compute and report metrics on the held-out test set. "
        "Training metrics may be logged for overfitting detection but must "
        "be clearly labelled as such."
    )
    tags = ("evaluation", "reporting")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _METRIC_CALLS):
            self.generic_visit(node)
            return

        # Check first argument — is it train data?
        arg_name = get_call_first_arg_name(node)
        if arg_name and self.taint.get_taint(arg_name) == "train":
            self.report(
                node,
                f"`{fqn.rsplit('.', 1)[-1]}({arg_name}, ...)` — metric computed "
                f"on training data. This produces optimistically biased estimates "
                f"and must not be used as final evaluation.",
            )
        self.generic_visit(node)
