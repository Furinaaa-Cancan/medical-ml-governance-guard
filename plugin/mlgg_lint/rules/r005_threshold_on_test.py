"""R005: Classification threshold/cutoff selected using test data.

Two-pass detection:
  Pass 1 (visit_Assign): Collect candidate roc_curve/precision_recall_curve calls
         where thresholds are captured from test data.
  Pass 2 (finalize): Check if captured threshold variables are actually USED
         later in the code (subscript, argument, assignment source). If the
         variable is never referenced after capture, it's just evaluation —
         not threshold selection.

Leakage (flagged):
    fpr, tpr, thresholds = roc_curve(y_test, y_pred)
    best = thresholds[np.argmax(tpr - fpr)]    # thresholds USED → flag

Not leakage (not flagged):
    fpr, tpr, _ = roc_curve(y_test, y_pred)    # discarded
    fpr, tpr, thresholds = roc_curve(y_test, y_pred)  # captured but never used
    plt.plot(fpr, tpr)                          # only fpr/tpr used
"""

from __future__ import annotations

import ast
from typing import List, Optional, Set, Tuple

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

_DISCARD_NAMES = {"_", "__", "___"}


def _find_index_2_access(tree: ast.AST, var_name: str, after_line: int) -> bool:
    """Check if `var_name[2]` or `var_name[-1]` is accessed after `after_line`.

    roc_curve returns (fpr, tpr, thresholds) — index 2 or -1 is the thresholds.
    """
    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno <= after_line:
            continue
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == var_name:
                # Check for [2] or [-1]
                sl = node.slice
                if isinstance(sl, ast.Constant):
                    if sl.value == 2 or sl.value == -1:
                        return True
                # Check for ast.UnaryOp (Python 3.7 compat for negative index)
                if isinstance(sl, ast.UnaryOp) and isinstance(sl.op, ast.USub):
                    if isinstance(sl.operand, ast.Constant) and sl.operand.value == 1:
                        return True
    return False


def _find_name_uses_after(tree: ast.AST, var_name: str, after_line: int) -> bool:
    """Check if `var_name` is referenced (loaded) after `after_line` in the AST."""
    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno <= after_line:
            continue
        # Direct name reference: `thresholds[idx]`, `print(thresholds)`, etc.
        if isinstance(node, ast.Name) and node.id == var_name:
            if isinstance(node.ctx, ast.Load):
                return True
    return False


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Candidates: (node, fqn, arg_name, threshold_var_name, assign_line)
        self._candidates: List[Tuple[ast.AST, str, str, Optional[str], int]] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Pass 1: Collect candidate threshold captures."""
        if not isinstance(node.value, ast.Call):
            self.generic_visit(node)
            return

        fqn = call_name(node.value, self.import_map)
        if not fqn or not matches_any(fqn, _THRESHOLD_CALLS):
            self.generic_visit(node)
            return

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

        # Extract the threshold variable name (3rd element in tuple unpack)
        thresh_var = self._get_threshold_var(node.targets)
        if thresh_var is None:
            # Discarded or 2-element unpack — safe
            self.generic_visit(node)
            return

        self._candidates.append((node.value, fqn, arg_name, thresh_var, node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Bare calls without assignment are always safe."""
        self.generic_visit(node)

    def finalize(self) -> None:
        """Pass 2: Check if captured threshold variables are actually used."""
        if not self._candidates:
            return

        for call_node, fqn, arg_name, thresh_var, assign_line in self._candidates:
            if thresh_var == "__single_var__":
                # `result = roc_curve(...)` — check if result[2] or similar
                # index access is used (threshold is the 3rd element).
                # Also check if the variable is used in a context that
                # suggests threshold extraction (e.g., result[2], result[-1]).
                target_names = self._get_assign_target_names(assign_line)
                if target_names and any(
                    _find_index_2_access(self._tree, name, assign_line)
                    for name in target_names
                ):
                    self.report(
                        call_node,
                        f"`{fqn.rsplit('.', 1)[-1]}({arg_name})` — return value "
                        f"accessed by index, potentially extracting thresholds. "
                        f"This may leak test information.",
                    )
                # If no index-2 access found, skip — likely just using fpr/tpr
                continue

            # Check if thresh_var is referenced after the assignment line
            used = _find_name_uses_after(self._tree, thresh_var, assign_line)
            if used:
                self.report(
                    call_node,
                    f"`{fqn.rsplit('.', 1)[-1]}({arg_name})` — threshold variable "
                    f"`{thresh_var}` captured and used after line {assign_line}. "
                    f"This leaks test information into threshold selection.",
                )
            # If not used: thresholds captured but never referenced → just evaluation, no report

    def _get_assign_target_names(self, line: int) -> List[str]:
        """Get target variable names for an assignment at a given line."""
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign) and node.lineno == line:
                names = []
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.append(t.id)
                return names
        return []

    @staticmethod
    def _get_threshold_var(targets: list[ast.expr]) -> Optional[str]:
        """Extract the threshold variable name, or None if discarded/safe.

        Returns:
            Variable name string if thresholds are captured in a named var.
            "__single_var__" if all return values go to one variable.
            None if thresholds are discarded (_) or only 2 values unpacked.
        """
        if len(targets) != 1:
            return "__single_var__"

        target = targets[0]

        # Single name: `result = roc_curve(...)`
        if isinstance(target, ast.Name):
            return "__single_var__"

        # Tuple unpacking: `a, b, c = roc_curve(...)`
        if isinstance(target, ast.Tuple) and len(target.elts) >= 3:
            third = target.elts[2]
            if isinstance(third, ast.Name):
                if third.id in _DISCARD_NAMES:
                    return None  # Discarded
                return third.id  # Named variable — needs usage check
            return "__single_var__"

        # 2-element unpack — safe
        if isinstance(target, ast.Tuple) and len(target.elts) == 2:
            return None

        return "__single_var__"
