"""R006: Feature selection fit on full dataset before split."""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import call_name, is_method_call, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_FEATURE_SELECTORS = {
    "SelectKBest", "SelectPercentile", "RFE", "RFECV",
    "SelectFromModel", "SequentialFeatureSelector",
    "VarianceThreshold", "GenericUnivariateSelect",
    "mutual_info_classif", "mutual_info_regression",
    "f_classif", "f_regression", "chi2",
}

_FIT_METHODS = {"fit", "fit_transform"}


@register
class FeatureSelectionFull(BaseRule):
    id = "R006"
    name = "feature-selection-on-full"
    severity = Severity.ERROR
    description = (
        "Feature selection performed on the full dataset before train/test split. "
        "Feature selection must use only training data to avoid leaking test "
        "information into feature choices."
    )
    remediation = (
        "Perform feature selection after splitting, using only training data. "
        "Embed feature selection inside a Pipeline to ensure correct scope."
    )
    tags = ("leakage", "feature-selection")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track variables that hold feature selector instances
        self._selector_vars: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Track: selector = SelectKBest(k=10)"""
        if isinstance(node.value, ast.Call):
            fqn = call_name(node.value, self.import_map)
            if fqn and matches_any(fqn, _FEATURE_SELECTORS):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._selector_vars.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)

        # Case 1: Direct call like SelectKBest(k=10).fit_transform(X, y)
        # before split — the selector is instantiated and fitted in one go
        if fqn and matches_any(fqn, _FEATURE_SELECTORS):
            if self.taint.split_line is not None and node.lineno < self.taint.split_line:
                # Only flag if this is also a chained fit call, e.g.
                # SelectKBest().fit_transform(X, y) — the parent is a method call
                # For bare instantiation (selector = SelectKBest()), we track it
                # in visit_Assign and check when .fit() is called later
                pass
            self.generic_visit(node)
            return

        # Case 2: selector.fit(X, y) or selector.fit_transform(X, y) before split
        for method in _FIT_METHODS:
            obj = is_method_call(node, method)
            if obj is not None and obj in self._selector_vars:
                if self.taint.split_line is not None and node.lineno < self.taint.split_line:
                    self.report(
                        node,
                        f"`{obj}.{method}()` called at line {node.lineno} "
                        f"before split at line {self.taint.split_line}. "
                        f"Feature selection on full data leaks test information.",
                    )
                break

        # Case 3: Chained call: SelectKBest(k=10).fit_transform(X, y) before split
        for method in _FIT_METHODS:
            obj = is_method_call(node, method)
            if obj == "<expr>":
                # Check if the chained object is a selector instantiation
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                    inner_fqn = call_name(node.func.value, self.import_map)
                    if inner_fqn and matches_any(inner_fqn, _FEATURE_SELECTORS):
                        if self.taint.split_line is not None and node.lineno < self.taint.split_line:
                            short = inner_fqn.rsplit(".", 1)[-1]
                            self.report(
                                node,
                                f"`{short}().{method}()` called at line {node.lineno} "
                                f"before split at line {self.taint.split_line}. "
                                f"Feature selection on full data leaks test information.",
                            )
                break

        self.generic_visit(node)
