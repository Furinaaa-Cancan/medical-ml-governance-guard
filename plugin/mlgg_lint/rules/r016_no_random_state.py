"""R016: train_test_split or model without random_state."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_NEEDS_SEED = {
    "train_test_split",
    "RandomForestClassifier", "RandomForestRegressor",
    "GradientBoostingClassifier", "GradientBoostingRegressor",
    "ExtraTreesClassifier", "ExtraTreesRegressor",
    "BaggingClassifier", "BaggingRegressor",
    "KFold", "StratifiedKFold", "GroupKFold",
    "ShuffleSplit", "StratifiedShuffleSplit",
}


@register
class NoRandomState(BaseRule):
    id = "R016"
    name = "no-random-state"
    severity = Severity.INFO
    description = (
        "Call to a stochastic function/class without explicit random_state "
        "parameter. Results will not be reproducible across runs."
    )
    remediation = (
        "Always set random_state (e.g., random_state=42) for reproducibility. "
        "Log the seed value in experiment metadata."
    )
    tags = ("reproducibility",)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _NEEDS_SEED):
            self.generic_visit(node)
            return

        has_seed = any(
            kw.arg in ("random_state", "seed") for kw in node.keywords
        )
        if not has_seed:
            short = fqn.rsplit(".", 1)[-1]
            self.report(
                node,
                f"`{short}()` without `random_state=`. "
                f"Results will not be reproducible.",
            )
        self.generic_visit(node)
