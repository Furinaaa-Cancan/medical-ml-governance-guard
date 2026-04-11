"""R022: Only AUROC reported without AUPRC or calibration metrics.

Medical prediction models require a comprehensive metric panel including
discrimination (AUROC + AUPRC), calibration, and clinical utility metrics.
Reporting only AUROC is insufficient for publication.
"""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


_AUROC_FUNCS = {"roc_auc_score", "sklearn.metrics.roc_auc_score"}
_COMPLEMENTARY_FUNCS = {
    "average_precision_score", "sklearn.metrics.average_precision_score",
    "brier_score_loss", "sklearn.metrics.brier_score_loss",
    "calibration_curve", "sklearn.calibration.calibration_curve",
    "log_loss", "sklearn.metrics.log_loss",
    "matthews_corrcoef", "sklearn.metrics.matthews_corrcoef",
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
        fqn = call_name(node, self.import_map)
        if fqn and matches_any(fqn, _AUROC_FUNCS):
            if not self._has_auroc:
                self._has_auroc = True
                self._auroc_node = node
        if fqn and matches_any(fqn, _COMPLEMENTARY_FUNCS):
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

