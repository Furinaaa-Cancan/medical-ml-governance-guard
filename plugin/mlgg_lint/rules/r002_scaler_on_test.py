"""R002: Preprocessor fit/fit_transform called on test/validation data."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import classify_var_name, get_call_first_arg_name, is_method_call
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

# Object names that are known safe to call .fit(X_test) on.
# Pipeline .fit() on test is intentional, not a preprocessing leak.
# NOTE: "model" removed — users may name a StandardScaler "model" and
# that would silently bypass this check. Only Pipeline-specific names.
_SAFE_FIT_NAMES = {
    "pipe", "pipeline",
}


@register
class ScalerOnTest(BaseRule):
    id = "R002"
    name = "scaler-fit-on-test"
    severity = Severity.ERROR
    description = (
        "Preprocessor .fit() or .fit_transform() called with test/validation data. "
        "This contaminates the preprocessing with holdout information."
    )
    remediation = (
        "Only call .fit() on training data. Use .transform() for test/validation sets. "
        "Wrap the full pipeline in sklearn.pipeline.Pipeline for safety."
    )
    tags = ("leakage", "preprocessing")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pipeline_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track Pipeline(...) assignments to avoid false positives."""
        if isinstance(node.value, ast.Call):
            from mlgg_lint.ast_utils import call_name, matches_any
            fqn = call_name(node.value, self.import_map)
            if fqn and matches_any(fqn, {"Pipeline", "make_pipeline"}):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self._pipeline_vars.add(t.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        for method in ("fit", "fit_transform"):
            obj = is_method_call(node, method)
            if obj is None:
                continue
            # Skip Pipeline and model objects — their .fit() is intentional
            if obj.lower() in _SAFE_FIT_NAMES or obj in self._pipeline_vars:
                continue
            arg_name = get_call_first_arg_name(node)
            if arg_name and self.taint.is_test_or_valid(arg_name):
                # Use tracked taint first (handles aliases like data = X_test),
                # fall back to name heuristic
                taint = self.taint.get_taint(arg_name) or classify_var_name(arg_name)
                label = "test" if taint == "test" else "validation"
                self.report(
                    node,
                    f"`{obj}.{method}({arg_name})` — fitting on "
                    f"{label} data leaks holdout statistics into the preprocessor.",
                )
        self.generic_visit(node)
