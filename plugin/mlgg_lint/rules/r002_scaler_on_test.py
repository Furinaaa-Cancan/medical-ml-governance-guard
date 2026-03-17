"""R002: Preprocessor fit/fit_transform called on test/validation data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import get_call_first_arg_name, is_method_call
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


@register
class ScalerOnTest(BaseRule):
    id = "R002"
    name = "scaler-fit-on-test"
    severity = Severity.ERROR
    description = (
        "Preprocessor .fit() or .fit_transform() called with test/validation data. "
        "This contaminates the preprocessing with holdout information."
    )
    remediation = (
        "Only call .fit() on training data. Use .transform() for test/validation sets. "
        "Wrap the full pipeline in sklearn.pipeline.Pipeline for safety."
    )
    tags = ("leakage", "preprocessing")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        for method in ("fit", "fit_transform"):
            obj = is_method_call(node, method)
            if obj is None:
                continue
            arg_name = get_call_first_arg_name(node)
            if arg_name and self.taint.is_test_or_valid(arg_name):
                self.report(
                    node,
                    f"`{obj}.{method}({arg_name})` — fitting on "
                    f"{'test' if 'test' in arg_name.lower() else 'validation'} data "
                    f"leaks holdout statistics into the preprocessor.",
                )
        self.generic_visit(node)
