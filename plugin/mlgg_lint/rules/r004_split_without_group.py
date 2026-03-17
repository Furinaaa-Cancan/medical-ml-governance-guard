"""R004: train_test_split without groups= for patient/subject data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SPLIT_CALLS = {"train_test_split", "sklearn.model_selection.train_test_split"}

_PATIENT_HINTS = {
    "patient", "subject", "person", "individual", "participant",
    "pid", "patient_id", "subject_id", "person_id",
}


def _has_patient_identifiers(tree: ast.Module) -> bool:
    """Check if the AST contains patient/subject-like variable names or
    string literals — using precise Name/Constant node checks rather than
    ast.dump() which would match inside comments and unrelated strings."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id.lower() in _PATIENT_HINTS:
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lower = node.value.lower()
            if any(h in lower for h in _PATIENT_HINTS):
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr.lower() in _PATIENT_HINTS:
                return True
    return False


@register
class SplitWithoutGroup(BaseRule):
    id = "R004"
    name = "split-without-group"
    severity = Severity.WARNING
    description = (
        "train_test_split called without groups= parameter in a context that "
        "appears to involve patient/subject data. Without grouping, the same "
        "patient may appear in both train and test, causing data leakage."
    )
    remediation = (
        "Use GroupShuffleSplit or pass groups= to train_test_split to ensure "
        "patient-level disjoint splits."
    )
    tags = ("leakage", "split")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_patient_context = False
        self._checked_module = False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        # Lazy check: only scan for patient context once
        if not self._checked_module:
            self._checked_module = True
            # Walk up to find the Module node — but since we don't have parent
            # references, we stored the tree in check(). Use a workaround:
            # the taint tracker proves the tree was already walked, so we
            # check patient context via the import_map / taint tracker.
            # Actually, we need the tree — defer to check() override.

        if not self._has_patient_context:
            self.generic_visit(node)
            return

        has_groups = any(kw.arg == "groups" for kw in node.keywords)
        if not has_groups:
            self.report(
                node,
                "train_test_split without `groups=` parameter in patient/subject "
                "context. Patients may appear in both train and test splits.",
            )
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self._has_patient_context = _has_patient_identifiers(tree)
        self.visit(tree)
        return self._diagnostics
