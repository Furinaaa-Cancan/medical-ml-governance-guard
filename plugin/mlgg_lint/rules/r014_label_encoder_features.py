"""R014: LabelEncoder used on feature columns."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, classify_var_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_LABEL_ENCODER = {"LabelEncoder", "sklearn.preprocessing.LabelEncoder"}

# Variable names / column names that indicate target usage
_TARGET_NAMES = {"target", "label", "y", "outcome", "diagnosis", "class"}


@register
class LabelEncoderFeatures(BaseRule):
    id = "R014"
    name = "label-encoder-on-features"
    severity = Severity.WARNING
    description = (
        "LabelEncoder used on feature columns. LabelEncoder is designed for "
        "target labels only; it imposes an arbitrary ordinal relationship on "
        "categorical features."
    )
    remediation = (
        "Use OrdinalEncoder for ordinal features or OneHotEncoder for nominal "
        "features. LabelEncoder should only be used for the target variable."
    )
    tags = ("preprocessing", "encoding")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track variables that hold LabelEncoder instances
        self._le_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track: le = LabelEncoder()"""
        if isinstance(node.value, ast.Call):
            fqn = call_name(node.value, self.import_map)
            if fqn and matches_any(fqn, _LABEL_ENCODER):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._le_vars.add(target.id)

        # Track: df["gender"] = le.fit_transform(df["gender"])
        # If assigning to a subscript like df["col"], check if col is target-like
        for target in node.targets:
            if isinstance(node.value, ast.Call):
                obj = is_method_call(node.value, "fit_transform")
                if obj is None:
                    obj = is_method_call(node.value, "transform")
                if obj is not None and obj in self._le_vars:
                    if not self._is_target_context(target, node.value):
                        self.report(
                            node,
                            f"LabelEncoder `{obj}` used on feature column. "
                            f"Use OrdinalEncoder or OneHotEncoder for feature columns.",
                        )

        self.generic_visit(node)

    def _is_target_context(self, target: ast.AST, call: ast.Call) -> bool:
        """Check if the assignment target or call argument indicates target usage."""
        # Check assignment target: y = le.fit_transform(...)
        if isinstance(target, ast.Name):
            name = target.id.lower()
            if name in _TARGET_NAMES or classify_var_name(target.id) is not None:
                return True

        # Check assignment target: df['target'] = le.fit_transform(...)
        if isinstance(target, ast.Subscript):
            col = self._get_subscript_str(target)
            if col and col.lower() in _TARGET_NAMES:
                return True

        # Check call argument: le.fit_transform(df['target'])
        if call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Subscript):
                col = self._get_subscript_str(arg)
                if col and col.lower() in _TARGET_NAMES:
                    return True
            if isinstance(arg, ast.Name):
                if arg.id.lower() in _TARGET_NAMES:
                    return True

        return False

    @staticmethod
    def _get_subscript_str(node: ast.Subscript) -> str | None:
        """Extract string key from df['col']."""
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return node.slice.value
        return None
