"""R009: Metrics reported without confidence intervals."""

from __future__ import annotations

import ast
from typing import List

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Diagnostic, Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_METRIC_CALLS = {
    "accuracy_score", "roc_auc_score", "f1_score", "precision_score",
    "recall_score", "average_precision_score", "brier_score_loss",
    "log_loss", "matthews_corrcoef", "balanced_accuracy_score",
    "cohen_kappa_score",
}

_CI_NAMES = {
    "bootstrap", "confidence_interval", "bootstrap_ci", "resample",
    "percentile",
}


def _has_ci_indicators(tree: ast.Module) -> bool:
    """Check for CI computation via precise AST checks (not ast.dump)."""
    for node in ast.walk(tree):
        # Variable names / function names containing CI hints
        if isinstance(node, ast.Name):
            lower = node.id.lower()
            if any(h in lower for h in _CI_NAMES):
                return True
        # Attribute accesses: scipy.stats.bootstrap, etc.
        if isinstance(node, ast.Attribute):
            if node.attr.lower() in _CI_NAMES:
                return True
        # String literals: "ci_lower", "ci_upper", etc.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lower = node.value.lower()
            if "ci_" in lower or "_ci" in lower or "confidence" in lower:
                return True
    return False


@register
class NoConfidenceIntervals(BaseRule):
    id = "R009"
    name = "no-confidence-intervals"
    severity = Severity.INFO
    description = (
        "Evaluation metrics computed without apparent confidence interval estimation. "
        "Publication-grade results require uncertainty quantification."
    )
    remediation = (
        "Add bootstrap confidence intervals for all reported metrics. "
        "Use scipy.stats.bootstrap or sklearn.utils.resample for CI computation."
    )
    tags = ("reporting", "statistics")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_ci = False
        self._metric_calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if fqn and matches_any(fqn, _METRIC_CALLS):
            self._metric_calls.append(node)
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> List[Diagnostic]:
        self._has_ci = _has_ci_indicators(tree)
        self.visit(tree)
        if self._metric_calls and not self._has_ci:
            node = self._metric_calls[0]
            self.report(
                node,
                f"Found {len(self._metric_calls)} metric computation(s) without "
                f"confidence interval estimation. Publication-grade results need "
                f"uncertainty bounds (e.g., bootstrap CI).",
                metric_count=len(self._metric_calls),
            )
        return self._diagnostics
