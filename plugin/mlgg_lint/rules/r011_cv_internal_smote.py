"""R011: SMOTE/resampling inside cross-validation without imblearn.Pipeline."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_CV_CALLS = {
    "cross_val_score", "cross_validate", "cross_val_predict",
    "GridSearchCV", "RandomizedSearchCV",
    "StratifiedKFold", "KFold", "RepeatedStratifiedKFold", "RepeatedKFold",
    "GroupKFold", "LeaveOneOut", "LeaveOneGroupOut",
    "sklearn.model_selection.cross_val_score",
    "sklearn.model_selection.cross_validate",
    "sklearn.model_selection.GridSearchCV",
    "sklearn.model_selection.RandomizedSearchCV",
    "sklearn.model_selection.StratifiedKFold",
    "sklearn.model_selection.KFold",
}

_RESAMPLE_CLASSES = {
    "SMOTE", "ADASYN", "BorderlineSMOTE", "SVMSMOTE",
    "RandomOverSampler", "RandomUnderSampler",
}

_IMBLEARN_PIPELINE = {"Pipeline", "make_pipeline", "imblearn.pipeline.Pipeline"}


@register
class CvInternalSmote(BaseRule):
    id = "R011"
    name = "cv-internal-smote"
    severity = Severity.ERROR
    description = (
        "SMOTE/resampling used alongside cross-validation but not wrapped in "
        "an imblearn.Pipeline. Resampling outside the CV loop applies to "
        "validation folds, inflating CV scores."
    )
    remediation = (
        "Wrap resampling + model in imblearn.pipeline.Pipeline so resampling "
        "is applied inside each CV fold on training data only."
    )
    tags = ("leakage", "cross-validation", "imbalance")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_resampler = False
        self._has_cv = False
        self._has_imblearn_pipeline = False
        self._cv_node: ast.Call | None = None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if fqn:
            if matches_any(fqn, _CV_CALLS):
                self._has_cv = True
                self._cv_node = node
            if matches_any(fqn, _RESAMPLE_CLASSES):
                self._has_resampler = True
            if matches_any(fqn, _IMBLEARN_PIPELINE):
                self._has_imblearn_pipeline = True
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self.visit(tree)
        if self._has_resampler and self._has_cv and not self._has_imblearn_pipeline:
            node = self._cv_node or tree
            self.report(
                node,
                "SMOTE/resampling used with cross-validation but not inside an "
                "imblearn.Pipeline. Resampling leaks into validation folds.",
            )
        return self._diagnostics
