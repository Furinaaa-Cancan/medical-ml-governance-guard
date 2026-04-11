"""R008: train_test_split with shuffle on time-series/temporal data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SPLIT_CALLS = {"train_test_split", "sklearn.model_selection.train_test_split"}
# Single-word hints matched via word-boundary split on _ (Name/Attribute/Constant).
# Multi-word entries like "admission_date" are redundant because "date" already
# matches. Entries like "created_at" are included for Name/Attribute exact match
# but won't match string literals split on _ (where they become {"created","at"}).
# We keep only single-word roots that reliably trigger via word splitting.
_TIME_HINTS = {
    "date", "time", "timestamp", "datetime",
    "admission", "discharge", "temporal", "chronological",
}


def _has_temporal_identifiers(tree: ast.Module) -> bool:
    """Check if the AST contains temporal variable names or column accesses
    using precise Name/Attribute/Constant checks (not ast.dump)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id.lower() in _TIME_HINTS:
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr.lower() in _TIME_HINTS:
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Use word-boundary matching: split on _ and whitespace
            words = set(node.value.lower().replace("-", "_").split("_"))
            for w in node.value.lower().split():
                words.add(w.strip(".,;:!?'\"()"))
            if words & _TIME_HINTS:
                return True
    return False


@register
class TemporalSplit(BaseRule):
    id = "R008"
    name = "temporal-split-shuffle"
    severity = Severity.WARNING
    description = (
        "train_test_split used with shuffle=True (default) on data that appears "
        "to contain temporal columns. Shuffled splits on time-series data cause "
        "future information to leak into training."
    )
    remediation = (
        "For temporal medical data, use time-based splits: sort by date and split "
        "chronologically, or use TimeSeriesSplit/GroupShuffleSplit with temporal ordering."
    )
    tags = ("leakage", "temporal")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_time_context = False

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not self._has_time_context:
            self.generic_visit(node)
            return

        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        shuffle_false = False
        for kw in node.keywords:
            if kw.arg == "shuffle":
                if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    shuffle_false = True
        if not shuffle_false:
            self.report(
                node,
                "train_test_split with shuffle enabled (default) on temporal data. "
                "This allows future observations to leak into training. "
                "Use chronological splitting instead.",
            )
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self._has_time_context = _has_temporal_identifiers(tree)
        self.visit(tree)
        return self._diagnostics
