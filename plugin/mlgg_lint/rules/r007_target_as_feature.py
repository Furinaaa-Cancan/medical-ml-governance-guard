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
        # var_name -> source dataframe variable (if known)
        self._var_source: dict[str, str] = {}
        # variables that were produced by df.drop()
        self._drop_derived: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track variable origins: X = df.drop(...), y = df['target'], X = df[cols]."""
        if not isinstance(node.value, (ast.Call, ast.Subscript)):
            self.generic_visit(node)
            return

        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            var_name = target.id

            # On any re-assignment, clear stale drop-derived status
            self._drop_derived.discard(var_name)

            # Pattern: X = df.drop(columns=[...])
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                if node.value.func.attr == "drop":
                    src = self._get_name(node.value.func.value)
                    if src:
                        self._var_source[var_name] = src
                        self._drop_derived.add(var_name)

            # Pattern: y = df['target'] or y = df[col]
            if isinstance(node.value, ast.Subscript):
                src = self._get_name(node.value.value)
                if src:
                    self._var_source[var_name] = src

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not isinstance(node.func, ast.Attribute):
            self.generic_visit(node)
            return
        if node.func.attr not in _FIT_METHODS:
            self.generic_visit(node)
            return

        if len(node.args) < 2:
            self.generic_visit(node)
            return

        x_arg = node.args[0]
        y_arg = node.args[1]
        x_name = self._get_name(x_arg)
        y_name = self._get_name(y_arg)

        if not x_name or not y_name:
            self.generic_visit(node)
            return

        # Case 1: model.fit(df, df) — exact same variable
        if x_name == y_name:
            self.report(
                node,
                f"`{node.func.attr}({x_name}, {y_name})` — "
                f"same variable used for both features and target. "
                f"The target column is likely still in the feature matrix.",
            )

        # Case 2: X and y both come from the same dataframe, but X was NOT
        # produced by df.drop() — the target column may still be in X.
        elif (
            x_name in self._var_source
            and y_name in self._var_source
            and self._var_source[x_name] == self._var_source[y_name]
            and x_name not in self._drop_derived
        ):
            src = self._var_source[x_name]
            self.report(
                node,
                f"`{node.func.attr}({x_name}, {y_name})` — both derived from "
                f"`{src}` but `{x_name}` was not produced by `.drop()`. "
                f"The target column may still be in the feature matrix.",
            )

        # Case 3: X is df[columns_list] with target-like names in the list
        if isinstance(x_arg, ast.Subscript):
            self._check_subscript_for_target(node, x_arg)

        self.generic_visit(node)

    def _check_subscript_for_target(
        self, call_node: ast.Call, subscript: ast.Subscript
    ) -> None:
        """Check df[[col1, col2, ...]] for presence of target-like column names."""
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
