"""R001: fit/fit_transform called on data before train_test_split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, get_call_first_arg_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


def _get_fit_first_arg(node: ast.Call) -> str | None:
    """Return the first positional argument name of a fit/fit_transform call."""
    return get_call_first_arg_name(node)

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

# Encoders that operate on the target variable (not features) are safe.
# LabelEncoder on y is standard practice, not preprocessing leakage.
_TARGET_ENCODER_CLASSES = {
    "LabelEncoder", "OrdinalEncoder",
}

# Pipeline objects are also safe — Pipeline.fit() is intentional
_SAFE_NAMES = {"pipe", "pipeline", "clf", "model", "estimator", "le", "label_encoder"}


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
        # Track line ranges of function/class definitions to skip fit()
        # calls inside helper functions (they're called on specific data,
        # not necessarily on unsplit data).
        self._scope_ranges: list[tuple[int, int]] = []

    def check(self, tree: ast.Module) -> list:
        # Pre-scan: collect function/class body line ranges
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.body:
                    start = node.body[0].lineno
                    end = node.end_lineno or node.body[-1].lineno
                    self._scope_ranges.append((start, end))
        self.visit(tree)
        self.finalize()
        return self._diagnostics

    def _in_nested_scope(self, lineno: int) -> bool:
        """Check if a line is inside a function/class body."""
        return any(start <= lineno <= end for start, end in self._scope_ranges)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track model, pipeline, and target-encoder assignments to avoid false positives."""
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
                # LabelEncoder/OrdinalEncoder on target — not preprocessing leakage
                if matches_any(fqn, _TARGET_ENCODER_CLASSES):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self._model_vars.add(t.id)
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
            # Only flag if:
            # 1. A split exists in THIS file (split_line is not None)
            # 2. The fit call is BEFORE the split
            # 3. The fit call is at module level (not inside a function/class)
            # 4. The first argument is NOT train data (avoid FP on fit(X_train))
            if self.taint.split_line is None:
                # No split in this file — cannot determine if fit is on unsplit
                # data. Skip to avoid cross-file false positives.
                continue
            if self._in_nested_scope(node.lineno):
                # fit() inside a function/class body — the function may be
                # called on train data only. Skip to avoid false positives.
                continue
            if not self.taint.has_split_occurred(node.lineno):
                # Check if the fit argument is explicitly train data
                arg_name = _get_fit_first_arg(node)
                if arg_name and self.taint.get_taint(arg_name) == "train":
                    # fit(X_train) before split line but variable is already
                    # classified as train — likely a second split or reassignment.
                    continue
                self.report(
                    node,
                    f"`{obj_name}.{method}()` called at line {node.lineno} "
                    f"before train_test_split at line {self.taint.split_line}. "
                    f"Preprocessor fitted on unsplit data leaks test information.",
                )
        self.generic_visit(node)
