"""R012: GridSearchCV/cross_val_score using accuracy on imbalanced data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_CV_CALLS = {
    "GridSearchCV", "RandomizedSearchCV",
    "cross_val_score", "cross_validate",
}

_IMBALANCE_HINTS = {
    "smote", "oversamp", "undersamp", "imbalance", "imbalanced",
    "class_weight", "sample_weight", "resamp",
}


@register
class CvAccuracyImbalanced(BaseRule):
    id = "R012"
    name = "cv-accuracy-imbalanced"
    severity = Severity.WARNING
    description = (
        "GridSearchCV or cross_val_score uses 'accuracy' as scoring metric "
        "in a context that appears to involve class imbalance. Accuracy is "
        "misleading on imbalanced data."
    )
    remediation = (
        "Use 'average_precision', 'roc_auc', or 'f1' as the scoring metric "
        "for imbalanced classification. Accuracy inflates performance when "
        "the majority class dominates."
    )
    tags = ("evaluation", "imbalance")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_imbalance_context = False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _CV_CALLS):
            self.generic_visit(node)
            return

        # Check scoring= keyword
        for kw in node.keywords:
            if kw.arg == "scoring" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str) and kw.value.value == "accuracy":
                    if self._has_imbalance_context:
                        self.report(
                            node,
                            f"`{fqn.rsplit('.', 1)[-1]}(scoring='accuracy')` in "
                            f"imbalanced-data context. Use 'average_precision' or "
                            f"'roc_auc' instead.",
                        )
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        # Pre-scan for imbalance indicators
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if any(h in node.id.lower() for h in _IMBALANCE_HINTS):
                    self._has_imbalance_context = True
                    break
            if isinstance(node, ast.Attribute):
                if any(h in node.attr.lower() for h in _IMBALANCE_HINTS):
                    self._has_imbalance_context = True
                    break
        self.visit(tree)
        return self._diagnostics
