"""R001: fit/fit_transform called on data before train_test_split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_FIT_METHODS = {"fit", "fit_transform"}
_FITTABLE_CLASSES = {
    "StandardScaler", "MinMaxScaler", "RobustScaler", "MaxAbsScaler",
    "Normalizer", "SimpleImputer", "IterativeImputer", "KNNImputer",
    "LabelEncoder", "OrdinalEncoder", "OneHotEncoder",
    "PolynomialFeatures", "PowerTransformer", "QuantileTransformer",
    "PCA", "TruncatedSVD", "SelectKBest", "RFE",
}


@register
class FitBeforeSplit(BaseRule):
    id = "R001"
    name = "fit-before-split"
    severity = Severity.ERROR
    description = (
        "Preprocessor fit/fit_transform called on full dataset before "
        "train_test_split. This leaks test distribution into the training pipeline."
    )
    remediation = (
        "Move fit/fit_transform to after the split and only fit on training data. "
        "Use sklearn.pipeline.Pipeline to ensure correct ordering."
    )
    tags = ("leakage", "preprocessing")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Check if this is obj.fit() or obj.fit_transform()
        for method in _FIT_METHODS:
            obj_name = is_method_call(node, method)
            if obj_name is None:
                continue
            # Only flag if no split has occurred yet
            if not self.taint.has_split_occurred(node.lineno):
                if self.taint.split_line is not None:
                    # Split exists but this call is before it
                    self.report(
                        node,
                        f"`{obj_name}.{method}()` called at line {node.lineno} "
                        f"before train_test_split at line {self.taint.split_line}. "
                        f"Preprocessor fitted on unsplit data leaks test information.",
                    )
        self.generic_visit(node)
