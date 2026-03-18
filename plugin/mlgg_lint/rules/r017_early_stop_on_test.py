"""R017: Early stopping / eval_set using test data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, classify_var_name, get_call_first_arg_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_BOOSTING_MODELS = {
    "XGBClassifier", "XGBRegressor",
    "LGBMClassifier", "LGBMRegressor",
    "CatBoostClassifier", "CatBoostRegressor",
}


@register
class EarlyStopOnTest(BaseRule):
    id = "R017"
    name = "early-stop-on-test"
    severity = Severity.ERROR
    description = (
        "Gradient boosting model uses test data for early stopping (eval_set). "
        "Early stopping on test data leaks test information into the model's "
        "training process (number of iterations is tuned on test)."
    )
    remediation = (
        "Use validation data (not test) for early stopping. "
        "eval_set=[(X_valid, y_valid)] or use nested cross-validation."
    )
    tags = ("leakage", "tuning")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Check model.fit(..., eval_set=[(X_test, y_test)])
        obj = is_method_call(node, "fit")
        if obj is None:
            self.generic_visit(node)
            return

        for kw in node.keywords:
            if kw.arg == "eval_set":
                self._check_eval_set(node, kw.value)
        self.generic_visit(node)

    def _check_eval_set(self, call_node: ast.Call, value: ast.expr) -> None:
        """Check if eval_set contains test data references.

        Early stopping on validation data is the recommended practice;
        only flag test data (not validation).
        """
        # eval_set=[(X_test, y_test)] — List of tuples
        if isinstance(value, ast.List):
            for elt in value.elts:
                if isinstance(elt, ast.Tuple):
                    for item in elt.elts:
                        if isinstance(item, ast.Name):
                            taint = self.taint.get_taint(item.id)
                            if taint is None:
                                taint = classify_var_name(item.id)
                            if taint == "test":
                                self.report(
                                    call_node,
                                    f"eval_set contains `{item.id}` (test data). "
                                    f"Early stopping on test data leaks information "
                                    f"into the training process. Use validation data instead.",
                                )
                                return
