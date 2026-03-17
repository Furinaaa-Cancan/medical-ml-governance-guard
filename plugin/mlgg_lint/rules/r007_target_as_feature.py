"""R007: Target column potentially used as a predictor feature."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_FIT_METHODS = {"fit", "fit_transform", "fit_predict"}
_TARGET_NAMES = {"target", "label", "y", "outcome", "diagnosis"}


@register
class TargetAsFeature(BaseRule):
    id = "R007"
    name = "target-as-feature"
    severity = Severity.ERROR
    description = (
        "Model is trained where X (features) and y (target) appear to come from "
        "the same DataFrame without dropping the target column from X. "
        "This is the most severe form of data leakage."
    )
    remediation = (
        "Always drop the target column from the feature matrix: "
        "`X = df.drop(columns=['target'])`."
    )
    tags = ("leakage", "target")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track: var -> (dataframe_source, is_target_dropped)
        self._drop_calls: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track X = df.drop(columns=[...]) patterns."""
        if isinstance(node.value, ast.Call):
            # df.drop(...)
            if isinstance(node.value.func, ast.Attribute):
                if node.value.func.attr == "drop":
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._drop_calls.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not isinstance(node.func, ast.Attribute):
            self.generic_visit(node)
            return
        if node.func.attr not in _FIT_METHODS:
            self.generic_visit(node)
            return

        # model.fit(X, y) — check if X and y come from same source
        if len(node.args) >= 2:
            x_arg = node.args[0]
            y_arg = node.args[1]
            x_name = self._get_name(x_arg)
            y_name = self._get_name(y_arg)

            if x_name and y_name:
                # Heuristic: if X is just the dataframe (same variable as y source)
                # without a .drop() call, flag it
                if x_name == y_name:
                    self.report(
                        node,
                        f"`{node.func.attr}({x_name}, {y_name})` — "
                        f"same variable used for both features and target. "
                        f"The target column is likely still in the feature matrix.",
                    )

                # Check: if X is a subscript like df[cols] where cols might include target
                if isinstance(x_arg, ast.Subscript):
                    self._check_subscript_for_target(node, x_arg, y_name)

        self.generic_visit(node)

    def _check_subscript_for_target(
        self, call_node: ast.Call, subscript: ast.Subscript, y_name: str
    ) -> None:
        """Check df[columns_list] for presence of target-like column names."""
        # df[[col1, col2, ...]] pattern
        if isinstance(subscript.slice, ast.List):
            for elt in subscript.slice.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if elt.value.lower() in _TARGET_NAMES:
                        self.report(
                            call_node,
                            f"Feature matrix appears to include target-like column "
                            f"'{elt.value}'. Drop it from X before training.",
                        )
                        return

    @staticmethod
    def _get_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        return None
