"""R014: LabelEncoder used on feature columns."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_LABEL_ENCODER = {"LabelEncoder", "sklearn.preprocessing.LabelEncoder"}


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

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if fqn and matches_any(fqn, _LABEL_ENCODER):
            self.report(
                node,
                "LabelEncoder is designed for target labels, not features. "
                "Use OrdinalEncoder or OneHotEncoder for feature columns.",
            )
        self.generic_visit(node)
