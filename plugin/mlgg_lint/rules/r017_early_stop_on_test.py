"""R017: Early stopping / eval_set using test data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import classify_var_name, is_method_call
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

        Walks the eval_set expression recursively (ast.walk) so ANY nesting and
        the bare-variable form are covered — the old one-level List/Tuple scan
        missed e.g. ``eval_set=[[(X_test, y_test)]]`` and ``eval_set=my_test_set``:
        - XGBoost/LightGBM: eval_set=[(X_test, y_test)]  (List[Tuple])
        - CatBoost:         eval_set=(X_test, y_test)     (bare Tuple)
        - nested:           eval_set=[[(X_test, y_test)]]
        - variable:         eval_set=my_eval_set           (Name)

        Only TEST data is flagged (early stopping on validation is the
        recommended practice), so each referenced name is checked for `test`
        taint specifically — validation names never fire.
        """
        for node in ast.walk(value):
            if not isinstance(node, ast.Name):
                continue
            taint = self.taint.get_taint(node.id)
            if taint is None:
                taint = classify_var_name(node.id)
            if taint == "test":
                self.report(
                    call_node,
                    f"eval_set contains `{node.id}` (test data). "
                    f"Early stopping on test data leaks information "
                    f"into the training process. Use validation data instead.",
                )
                return
