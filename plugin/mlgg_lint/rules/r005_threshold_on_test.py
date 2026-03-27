"""R005: Classification threshold/cutoff selected using test data.

Only flags when the thresholds return value of roc_curve/precision_recall_curve
is actually captured (not discarded with _). Computing ROC curves on test data
for evaluation/plotting is legitimate and should not be flagged.

Leakage pattern:
    fpr, tpr, thresholds = roc_curve(y_test, y_pred)  # thresholds captured → FLAG
    best = thresholds[np.argmax(tpr - fpr)]            # used for threshold selection

Legitimate use (not flagged):
    fpr, tpr, _ = roc_curve(y_test, y_pred)            # thresholds discarded → OK
    plt.plot(fpr, tpr)                                  # just plotting

    auc_score = roc_auc_score(y_test, y_pred)           # no thresholds involved → OK
"""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, classify_var_name, get_call_first_arg_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_THRESHOLD_CALLS = {
    "roc_curve",
    "precision_recall_curve",
    "sklearn.metrics.roc_curve",
    "sklearn.metrics.precision_recall_curve",
}

# Names that indicate threshold is deliberately discarded
_DISCARD_NAMES = {"_", "__", "___"}


@register
class ThresholdOnTest(BaseRule):
    id = "R005"
    name = "threshold-on-test"
    severity = Severity.ERROR
    description = (
        "Threshold/cutoff selection performed using test data (via roc_curve or "
        "precision_recall_curve). Thresholds should be selected on training or "
        "validation data, not on the test set."
    )
    remediation = (
        "Select the operating threshold on the validation set, not the test set. "
        "The test set should only be used for final, unbiased evaluation. "
        "If you only need AUC, use roc_auc_score() instead of roc_curve()."
    )
    tags = ("leakage", "evaluation")

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Check assignments like `fpr, tpr, thresholds = roc_curve(y_test, ...)`."""
        # Only care about calls on the RHS
        if not isinstance(node.value, ast.Call):
            self.generic_visit(node)
            return

        fqn = call_name(node.value, self.import_map)
        if not fqn or not matches_any(fqn, _THRESHOLD_CALLS):
            self.generic_visit(node)
            return

        # Check if first arg is test data
        arg_name = get_call_first_arg_name(node.value)
        if not arg_name:
            self.generic_visit(node)
            return

        taint = self.taint.get_taint(arg_name)
        if taint is None:
            taint = classify_var_name(arg_name)
        if taint != "test":
            self.generic_visit(node)
            return

        # Now check: is the thresholds return value captured or discarded?
        # roc_curve returns (fpr, tpr, thresholds) — 3 values
        # precision_recall_curve returns (precision, recall, thresholds) — 3 values
        thresholds_captured = self._is_thresholds_captured(node.targets)

        if thresholds_captured:
            self.report(
                node.value,
                f"`{fqn.rsplit('.', 1)[-1]}({arg_name})` — threshold values "
                f"captured from test data. If used to select an operating "
                f"threshold, this leaks test information into model decisions.",
            )
        # If thresholds discarded (e.g., fpr, tpr, _ = ...), no report.
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Handle bare calls (no assignment) — these are safe (result unused)."""
        # A bare roc_curve(y_test, ...) without capturing the result
        # cannot be used for threshold selection, so we don't flag it.
        self.generic_visit(node)

    @staticmethod
    def _is_thresholds_captured(targets: list[ast.expr]) -> bool:
        """Check if the 3rd return value (thresholds) is captured in a named variable.

        Patterns that mean "captured" (flag):
            fpr, tpr, thresholds = roc_curve(...)     # Tuple with named 3rd
            result = roc_curve(...)                    # Single name (all captured)

        Patterns that mean "discarded" (don't flag):
            fpr, tpr, _ = roc_curve(...)              # 3rd is _
            fpr, tpr = roc_curve(...)[:2]             # Only first 2 (rare)
        """
        if len(targets) != 1:
            return True  # Multiple assignment targets — conservative: flag

        target = targets[0]

        # Single name: `result = roc_curve(...)` — conservative: flag
        if isinstance(target, ast.Name):
            return True

        # Tuple unpacking: `a, b, c = roc_curve(...)`
        if isinstance(target, ast.Tuple) and len(target.elts) >= 3:
            third = target.elts[2]
            # Check if 3rd element is _ (discarded)
            if isinstance(third, ast.Name) and third.id in _DISCARD_NAMES:
                return False  # Explicitly discarded — safe
            return True  # Named variable — captured

        # 2-element unpack: `fpr, tpr = roc_curve(...)[:2]` — safe
        if isinstance(target, ast.Tuple) and len(target.elts) == 2:
            return False

        return True  # Conservative default: flag
