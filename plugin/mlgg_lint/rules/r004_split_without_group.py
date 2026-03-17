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

    def visit_Module(self, node: ast.Module) -> None:  # noqa: N802
        # Pre-scan: does this file reference patient-like variables?
        source = ast.dump(node)
        lower = source.lower()
        self._has_patient_context = any(h in lower for h in _PATIENT_HINTS)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not self._has_patient_context:
            self.generic_visit(node)
            return

        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        # Check for groups= keyword argument
        has_groups = any(
            kw.arg == "groups" for kw in node.keywords
        )
        if not has_groups:
            self.report(
                node,
                "train_test_split without `groups=` parameter in patient/subject "
                "context. Patients may appear in both train and test splits.",
            )
        self.generic_visit(node)
