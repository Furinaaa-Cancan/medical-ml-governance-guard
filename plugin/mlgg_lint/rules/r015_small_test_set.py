"""R015: train_test_split with very small test_size."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SPLIT_CALLS = {"train_test_split", "sklearn.model_selection.train_test_split"}


@register
class SmallTestSet(BaseRule):
    id = "R015"
    name = "small-test-set"
    severity = Severity.WARNING
    description = (
        "train_test_split with test_size < 0.1 (less than 10%). Very small "
        "test sets produce unstable performance estimates with wide confidence "
        "intervals."
    )
    remediation = (
        "Use test_size >= 0.15 for reliable evaluation. For small datasets, "
        "consider nested cross-validation instead of a single train/test split."
    )
    tags = ("evaluation", "split")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        for kw in node.keywords:
            if kw.arg == "test_size" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, (int, float)) and 0 < val < 0.1:
                    self.report(
                        node,
                        f"test_size={val} is very small (<10%). Performance "
                        f"estimates will be unstable. Use >= 0.15 or nested CV.",
                    )
        self.generic_visit(node)
