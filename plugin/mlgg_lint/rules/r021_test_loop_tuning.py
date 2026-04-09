"""R021: Test set used in hyperparameter tuning loop.

Detects patterns where model.predict_proba(X_test) or similar is called
inside a for loop, suggesting the test set is being used for model selection
or hyperparameter tuning.
"""

from __future__ import annotations

import ast
from typing import Set

from mlgg_lint.ast_utils import classify_var_name
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


@register
class TestLoopTuning(BaseRule):
    id = "R021"
    name = "test-loop-tuning"
    severity = Severity.ERROR
    description = (
        "Test/holdout data used inside a loop for model evaluation, suggesting "
        "hyperparameter tuning on test data. This inflates reported performance "
        "and violates MLGG-M01."
    )
    remediation = (
        "Use a separate validation set or inner cross-validation for "
        "hyperparameter tuning. Reserve the test set for a single final evaluation."
    )
    tags = ("leakage", "model_selection")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop_depth = 0
        self._reported_lines: Set[int] = set()

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._loop_depth <= 0:
            self.generic_visit(node)
            return

        # Check for predict_proba / predict / score calls with test-tainted args
        func = node.func
        method_name = None
        if isinstance(func, ast.Attribute):
            method_name = func.attr
        elif isinstance(func, ast.Name):
            method_name = func.id

        if method_name not in ("predict_proba", "predict", "score",
                               "roc_auc_score", "average_precision_score",
                               "brier_score_loss", "log_loss"):
            self.generic_visit(node)
            return

        # Check if any argument looks like test data
        for arg in node.args:
            name = self._arg_name(arg)
            if name and self._is_test_like(name):
                line = getattr(node, "lineno", 0)
                if line not in self._reported_lines:
                    self._reported_lines.add(line)
                    self.report(
                        node,
                        f"`{method_name}({name})` called inside a loop. "
                        f"If this loop tunes hyperparameters, test data is being "
                        f"used for model selection (MLGG-M01 violation).",
                    )
        self.generic_visit(node)

    @staticmethod
    def _arg_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            return node.value.id
        return None

    @staticmethod
    def _is_test_like(name: str) -> bool:
        low = name.lower()
        test_hints = ("test", "holdout", "held_out", "heldout", "x_eval")
        return any(h in low for h in test_hints)
