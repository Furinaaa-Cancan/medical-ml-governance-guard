"""R022: Only AUROC reported without AUPRC or calibration metrics.

Medical prediction models require a comprehensive metric panel including
discrimination (AUROC + AUPRC), calibration, and clinical utility metrics.
Reporting only AUROC is insufficient for publication.
"""

from __future__ import annotations

import ast

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


_AUROC_FUNCS = {"roc_auc_score"}
_COMPLEMENTARY_FUNCS = {
    "average_precision_score",  # AUPRC
    "brier_score_loss",         # calibration
    "calibration_curve",        # calibration
    "log_loss",                 # calibration
    "matthews_corrcoef",        # MCC
}


@register
class SingleMetricReport(BaseRule):
    id = "R022"
    name = "single-metric-report"
    severity = Severity.WARNING
    description = (
        "Only AUROC (roc_auc_score) is computed without complementary metrics "
        "(AUPRC, calibration, MCC). TRIPOD+AI 2024 and top-journal reviewers "
        "require a comprehensive metric panel."
    )
    remediation = (
        "Add at least: average_precision_score (AUPRC), brier_score_loss, "
        "and calibration_curve. For clinical models, also add DCA (decision "
        "curve analysis) and MCC (matthews_corrcoef)."
    )
    tags = ("evaluation", "reporting")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_auroc = False
        self._auroc_node = None
        self._has_complementary = False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func_name = self._get_func_name(node)
        if func_name in _AUROC_FUNCS:
            if not self._has_auroc:
                self._has_auroc = True
                self._auroc_node = node
        if func_name in _COMPLEMENTARY_FUNCS:
            self._has_complementary = True
        self.generic_visit(node)

    def finalize(self) -> None:
        if self._has_auroc and not self._has_complementary:
            self.report(
                self._auroc_node,
                "Only roc_auc_score found — no AUPRC, calibration, or MCC metrics. "
                "Publication-grade evaluation requires a comprehensive metric panel "
                "(TRIPOD+AI 2024 Item 17).",
            )

    @staticmethod
    def _get_func_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None
