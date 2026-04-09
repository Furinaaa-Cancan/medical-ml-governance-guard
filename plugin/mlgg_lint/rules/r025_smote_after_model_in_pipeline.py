"""R025: SMOTE/resampling placed after estimator in Pipeline.

In an imblearn Pipeline, resampling must come BEFORE the classifier.
Placing SMOTE after the classifier is nonsensical and indicates a bug.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_RESAMPLE_NAMES = {
    "smote", "adasyn", "borderlinesmote", "svmsmote",
    "randomoversampler", "randomundersampler",
}

_ESTIMATOR_NAMES = {
    "logisticregression", "randomforestclassifier", "gradientboostingclassifier",
    "xgbclassifier", "lgbmclassifier", "catboostclassifier",
    "svc", "mlpclassifier", "decisiontreeclassifier",
    "kneighborsclassifier", "gaussiannb",
}


@register
class SmoteAfterModelInPipeline(BaseRule):
    id = "R025"
    name = "smote-after-model-in-pipeline"
    severity = Severity.ERROR
    description = (
        "SMOTE/resampling step placed after the estimator in a Pipeline. "
        "Resampling must come before the classifier to be applied on "
        "training data during fit()."
    )
    remediation = (
        "Reorder Pipeline steps: imputer → scaler → SMOTE → classifier. "
        "Example: Pipeline([('smote', SMOTE()), ('model', LogisticRegression())])"
    )
    tags = ("leakage", "pipeline", "imbalance")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Look for Pipeline([...]) or make_pipeline(...)
        func_name = self._get_func_name(node)
        if func_name not in ("Pipeline", "make_pipeline"):
            self.generic_visit(node)
            return

        # Extract the steps list
        steps = self._extract_pipeline_steps(node)
        if not steps:
            self.generic_visit(node)
            return

        # Find positions of resampler and estimator
        estimator_pos: Optional[int] = None
        resampler_pos: Optional[int] = None
        resampler_name: Optional[str] = None

        for i, (step_name, class_name) in enumerate(steps):
            if class_name and class_name.lower() in _ESTIMATOR_NAMES:
                estimator_pos = i
            if class_name and class_name.lower() in _RESAMPLE_NAMES:
                resampler_pos = i
                resampler_name = class_name

        if (estimator_pos is not None and resampler_pos is not None
                and resampler_pos > estimator_pos):
            self.report(
                node,
                f"'{resampler_name}' (step {resampler_pos}) placed after estimator "
                f"(step {estimator_pos}) in Pipeline. Resampling must come BEFORE "
                f"the classifier.",
            )

        self.generic_visit(node)

    def _extract_pipeline_steps(self, node: ast.Call) -> List[tuple]:
        """Extract (step_name, class_name) from Pipeline([...]) steps arg."""
        steps = []
        # Pipeline(steps=[...]) or Pipeline([...])
        steps_arg = None
        if node.args:
            steps_arg = node.args[0]
        for kw in node.keywords:
            if kw.arg == "steps":
                steps_arg = kw.value

        if not isinstance(steps_arg, ast.List):
            return steps

        for elt in steps_arg.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                # ("name", ClassInstance(...))
                step_name = None
                if isinstance(elt.elts[0], ast.Constant):
                    step_name = str(elt.elts[0].value)
                class_name = self._get_class_name(elt.elts[1])
                steps.append((step_name, class_name))
        return steps

    @staticmethod
    def _get_class_name(node: ast.expr) -> Optional[str]:
        """Get class name from a Call node like SMOTE(...) or LogisticRegression(...)."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return node.func.id
            if isinstance(node.func, ast.Attribute):
                return node.func.attr
        if isinstance(node, ast.Name):
            return node.id
        return None

    @staticmethod
    def _get_func_name(node: ast.Call) -> Optional[str]:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None
