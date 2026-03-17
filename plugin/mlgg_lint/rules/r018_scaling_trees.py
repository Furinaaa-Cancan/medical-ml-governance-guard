"""R018: Feature scaling applied before tree-based models."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SCALERS = {
    "StandardScaler", "MinMaxScaler", "RobustScaler",
    "MaxAbsScaler", "Normalizer",
}

_TREE_MODELS = {
    "DecisionTreeClassifier", "DecisionTreeRegressor",
    "RandomForestClassifier", "RandomForestRegressor",
    "GradientBoostingClassifier", "GradientBoostingRegressor",
    "ExtraTreesClassifier", "ExtraTreesRegressor",
    "XGBClassifier", "XGBRegressor",
    "LGBMClassifier", "LGBMRegressor",
    "CatBoostClassifier", "CatBoostRegressor",
}


@register
class ScalingTrees(BaseRule):
    id = "R018"
    name = "scaling-before-trees"
    severity = Severity.INFO
    description = (
        "Feature scaling (StandardScaler/MinMaxScaler) applied before a "
        "tree-based model. Tree-based models are invariant to monotonic "
        "feature transformations; scaling adds unnecessary complexity."
    )
    remediation = (
        "Remove feature scaling when using tree-based models (RF, GBDT, XGBoost). "
        "Scaling is needed for distance-based (KNN, SVM) and gradient-based "
        "(Logistic Regression, MLP) models."
    )
    tags = ("preprocessing", "efficiency")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_scaler = False
        self._has_tree = False
        self._scaler_node: ast.Call | None = None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if fqn:
            if matches_any(fqn, _SCALERS) and not self._has_scaler:
                self._has_scaler = True
                self._scaler_node = node
            if matches_any(fqn, _TREE_MODELS):
                self._has_tree = True
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self.visit(tree)
        if self._has_scaler and self._has_tree:
            node = self._scaler_node or tree
            self.report(
                node,
                "Feature scaling used with tree-based model. Trees are "
                "invariant to scaling — this adds unnecessary complexity.",
            )
        return self._diagnostics
