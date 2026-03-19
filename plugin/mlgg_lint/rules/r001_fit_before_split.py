"""R001: fit/fit_transform called on data before train_test_split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_FIT_METHODS = {"fit", "fit_transform"}

# Model classes whose .fit() is training, not preprocessing.
# We don't flag these under R001 (preprocessor leak) — models fitting on
# unsplit data is a different concern.
_MODEL_CLASSES = {
    "LogisticRegression", "RandomForestClassifier", "RandomForestRegressor",
    "GradientBoostingClassifier", "GradientBoostingRegressor",
    "SVC", "SVR", "LinearSVC", "LinearSVR",
    "KNeighborsClassifier", "KNeighborsRegressor",
    "DecisionTreeClassifier", "DecisionTreeRegressor",
    "ExtraTreesClassifier", "ExtraTreesRegressor",
    "BaggingClassifier", "BaggingRegressor",
    "AdaBoostClassifier", "AdaBoostRegressor",
    "XGBClassifier", "XGBRegressor",
    "LGBMClassifier", "LGBMRegressor",
    "CatBoostClassifier", "CatBoostRegressor",
    "MLPClassifier", "MLPRegressor",
    "GaussianNB", "MultinomialNB", "BernoulliNB",
    "SGDClassifier", "SGDRegressor",
    "Ridge", "Lasso", "ElasticNet",
}

# Pipeline objects are also safe — Pipeline.fit() is intentional
_SAFE_NAMES = {"pipe", "pipeline", "clf", "model", "estimator"}


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track variables that hold model instances (not preprocessors)
        self._model_vars: set[str] = set()
        self._pipeline_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track model and pipeline assignments to avoid false positives."""
        if isinstance(node.value, ast.Call):
            fqn = call_name(node.value, self.import_map)
            if fqn:
                if matches_any(fqn, _MODEL_CLASSES):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self._model_vars.add(t.id)
                if matches_any(fqn, {"Pipeline", "make_pipeline"}):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self._pipeline_vars.add(t.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        for method in _FIT_METHODS:
            obj_name = is_method_call(node, method)
            if obj_name is None:
                continue
            # Skip model objects — their .fit() is training, not preprocessing
            if obj_name in self._model_vars or obj_name in self._pipeline_vars:
                continue
            if obj_name.lower() in _SAFE_NAMES:
                continue
            # Only flag if no split has occurred yet
            if not self.taint.has_split_occurred(node.lineno):
                if self.taint.split_line is not None:
                    self.report(
                        node,
                        f"`{obj_name}.{method}()` called at line {node.lineno} "
                        f"before train_test_split at line {self.taint.split_line}. "
                        f"Preprocessor fitted on unsplit data leaks test information.",
                    )
        self.generic_visit(node)
