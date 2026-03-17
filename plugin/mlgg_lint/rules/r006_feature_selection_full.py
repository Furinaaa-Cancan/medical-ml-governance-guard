"""R006: Feature selection on full dataset before split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_FEATURE_SELECTORS = {
    "SelectKBest", "SelectPercentile", "RFE", "RFECV",
    "SelectFromModel", "SequentialFeatureSelector",
    "VarianceThreshold", "GenericUnivariateSelect",
    "mutual_info_classif", "mutual_info_regression",
    "f_classif", "f_regression", "chi2",
}


@register
class FeatureSelectionFull(BaseRule):
    id = "R006"
    name = "feature-selection-on-full"
    severity = Severity.ERROR
    description = (
        "Feature selection performed on the full dataset before train/test split. "
        "Feature selection must use only training data to avoid leaking test "
        "information into feature choices."
    )
    remediation = (
        "Perform feature selection after splitting, using only training data. "
        "Embed feature selection inside a Pipeline to ensure correct scope."
    )
    tags = ("leakage", "feature-selection")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn:
            self.generic_visit(node)
            return

        # Detect instantiation of feature selectors before split
        if matches_any(fqn, _FEATURE_SELECTORS):
            if self.taint.split_line is not None and node.lineno < self.taint.split_line:
                self.report(
                    node,
                    f"`{fqn.rsplit('.', 1)[-1]}()` instantiated at line {node.lineno} "
                    f"before split at line {self.taint.split_line}. "
                    f"Feature selection on full data leaks test information.",
                )

        # Detect .fit() on feature selectors before split
        if fqn.endswith(".fit") or fqn.endswith(".fit_transform"):
            if not self.taint.has_split_occurred(node.lineno):
                if self.taint.split_line is not None:
                    # We can't easily tell if it's a feature selector object,
                    # but R001 already catches generic fit-before-split.
                    pass

        self.generic_visit(node)
