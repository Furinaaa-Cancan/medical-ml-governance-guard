"""R019: Multiple model comparison without correction."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_MODEL_CLASSES = {
    "LogisticRegression", "RandomForestClassifier", "GradientBoostingClassifier",
    "SVC", "KNeighborsClassifier", "DecisionTreeClassifier",
    "ExtraTreesClassifier", "BaggingClassifier", "AdaBoostClassifier",
    "XGBClassifier", "LGBMClassifier", "CatBoostClassifier",
    "MLPClassifier", "GaussianNB", "LinearSVC",
    "RandomForestRegressor", "GradientBoostingRegressor",
    "XGBRegressor", "LGBMRegressor", "CatBoostRegressor",
}

_CORRECTION_HINTS = {
    "bonferroni", "holm", "multipletests", "fdr", "sidak",
    "statsmodels.stats.multitest",
}


@register
class MultipleComparison(BaseRule):
    id = "R019"
    name = "multiple-comparison-no-correction"
    severity = Severity.INFO
    description = (
        "Multiple models compared without apparent multiple-comparison "
        "correction. When comparing N models, the probability of finding "
        "a spuriously 'best' model increases with N."
    )
    remediation = (
        "Apply Bonferroni or Holm correction when comparing multiple models. "
        "Alternatively, use a one-standard-error rule to select the simplest "
        "model within one SE of the best."
    )
    tags = ("statistical", "model-selection")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._model_count = 0
        self._has_correction = False
        self._first_model_node: ast.Call | None = None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if fqn and matches_any(fqn, _MODEL_CLASSES):
            self._model_count += 1
            if self._first_model_node is None:
                self._first_model_node = node
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        # Check for correction indicators
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if any(h in node.id.lower() for h in _CORRECTION_HINTS):
                    self._has_correction = True
            if isinstance(node, ast.Attribute):
                if any(h in node.attr.lower() for h in _CORRECTION_HINTS):
                    self._has_correction = True

        self.visit(tree)
        if self._model_count >= 3 and not self._has_correction:
            node = self._first_model_node or tree
            self.report(
                node,
                f"{self._model_count} model classes instantiated without "
                f"multiple-comparison correction. Risk of selecting a "
                f"spuriously best model.",
                model_count=self._model_count,
            )
        return self._diagnostics
