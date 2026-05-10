"""R021: Test set used in hyperparameter tuning loop.

Detects patterns where a test-prediction call (predict_proba/predict/score/
holdout-metric) is performed inside a loop AND the loop body simultaneously
mutates model hyperparameters (set_params, attribute assignment with a known
sklearn HP name, or re-instantiation parametrized by a loop variable).

This is the canonical M01 violation: tuning hyperparameters by sweeping a
range and selecting based on test-set performance. Plain CV evaluation
(``for tr, te in cv.split(X, y): m.fit(...); m.predict_proba(X[te])``) does
NOT trigger this rule because no HP mutation occurs in the body — that is
the standard k-fold reporting pattern, not test-leak.

Revision history:
    2026-05-10 (B8): added _loop_body_mutates_hyperparameters gate to fix
    a 0/4 TP rate from A3 stratified review. The four FP cases were all
    plain k-fold CV evaluation loops on PR-086 (CV.split + per-fold
    X_test) misclassified as tuning loops.
"""

from __future__ import annotations

import ast
from typing import Optional, Set

from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


# Known sklearn / xgboost / lightgbm hyperparameter names. Used both for
# attribute-assignment detection (model.C = c) and for re-instantiation
# keyword detection (SVC(C=c)). Conservative list — bias toward recall
# of the tuning-loop pattern, not toward exhaustive coverage.
_HYPERPARAM_NAMES: frozenset[str] = frozenset({
    # Linear / regularized
    "C", "alpha", "l1_ratio", "penalty", "solver", "tol",
    "fit_intercept", "intercept_scaling",
    # Tree / ensemble
    "n_estimators", "max_depth", "max_features", "max_leaf_nodes",
    "min_samples_split", "min_samples_leaf", "min_weight_fraction_leaf",
    "min_impurity_decrease", "criterion", "splitter",
    "bootstrap", "max_samples", "ccp_alpha",
    # Boosting
    "learning_rate", "subsample", "colsample_bytree", "colsample_bylevel",
    "colsample_bynode", "reg_alpha", "reg_lambda", "gamma",
    "min_child_weight", "scale_pos_weight", "num_leaves",
    "boosting_type", "objective", "eval_metric",
    # SVM / kernel
    "kernel", "degree", "coef0", "shrinking", "probability",
    "cache_size", "class_weight",
    # Neighbors
    "n_neighbors", "weights", "algorithm", "leaf_size", "p", "metric",
    # Neural
    "hidden_layer_sizes", "activation", "batch_size",
    "learning_rate_init", "momentum", "early_stopping", "validation_fraction",
    "n_iter_no_change", "epochs", "dropout",
    # Misc
    "n_components", "n_clusters", "eps", "min_samples",
    "loss", "epsilon", "nu", "max_iter",
})


_TEST_PRED_METHODS: frozenset[str] = frozenset({
    "predict_proba", "predict", "decision_function", "score",
    "predict_log_proba",
})


_TEST_METRIC_FUNCS: frozenset[str] = frozenset({
    "roc_auc_score", "average_precision_score", "brier_score_loss",
    "log_loss", "accuracy_score", "f1_score", "precision_score",
    "recall_score", "matthews_corrcoef", "balanced_accuracy_score",
})


@register
class TestLoopTuning(BaseRule):
    id = "R021"
    name = "test-loop-tuning"
    severity = Severity.WARNING
    description = (
        "Test/holdout data evaluated inside a loop that also mutates model "
        "hyperparameters — strong indicator that hyperparameters are being "
        "tuned against the test set (MLGG-M01 violation)."
    )
    remediation = (
        "Use a separate validation set or inner cross-validation for HP "
        "selection (e.g., GridSearchCV with cv=). Reserve the test set for "
        "a single final-model evaluation after the best HPs are chosen."
    )
    tags = ("leakage", "model_selection")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reported_lines: Set[int] = set()

    # We override the default per-Call traversal: only inspect calls
    # whose enclosing for/while loop also mutates hyperparameters.
    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._check_loop(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self._check_loop(node)
        self.generic_visit(node)

    # ── Core logic ───────────────────────────────────────────────────────

    def _check_loop(self, loop_node: ast.AST) -> None:
        if not _loop_body_mutates_hyperparameters(loop_node):
            return  # plain CV evaluation — not our concern
        # Loop tunes HPs; now find test-prediction calls inside its body and
        # report at the call site so the diagnostic points to the leak.
        for call_node, method_name, arg_name in _iter_test_pred_calls(loop_node):
            line = getattr(call_node, "lineno", 0)
            if line in self._reported_lines:
                continue
            self._reported_lines.add(line)
            self.report(
                call_node,
                f"`{method_name}({arg_name})` called inside a loop that mutates "
                f"hyperparameters (e.g., set_params / attribute assignment / "
                f"parametrized re-instantiation). The test set is being used "
                f"for hyperparameter selection (MLGG-M01 violation).",
            )


# ── Helper: detect HP mutation inside a loop body ────────────────────────


def _loop_body_mutates_hyperparameters(loop_node: ast.AST) -> bool:
    """Return True if the body of *loop_node* contains a hyperparameter
    mutation pattern (set_params / HP-attribute assign / re-instantiation
    parametrized by a loop variable / nested HP-grid loop).

    Walks only the body of *loop_node* (not nested function definitions
    that happen to live inside the body — those should be analyzed on
    their own merits).
    """
    loop_var_names = _collect_loop_target_names(loop_node)

    body = getattr(loop_node, "body", []) or []
    orelse = getattr(loop_node, "orelse", []) or []
    for stmt in list(body) + list(orelse):
        for child in ast.walk(stmt):
            # Skip nested FunctionDef bodies — they're a different scope.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda)):
                continue
            # (a) m.set_params(C=c)
            if _is_set_params_call(child):
                return True
            # (b) model.<hp_name> = ...
            if _is_hp_attribute_assign(child):
                return True
            # (c) model = SomeEstimator(C=c)  where c is a loop var
            if _is_parametrized_reassignment(child, loop_var_names):
                return True
    # (d) nested for-loop sweeping HP values
    for stmt in body:
        if _contains_hp_sweep_subloop(stmt):
            return True
    return False


def _collect_loop_target_names(loop_node: ast.AST) -> set[str]:
    """Collect names bound by the loop's iteration target.

    ``for c in [0.1, 1, 10]`` → {"c"}
    ``for tr, te in cv.split(...)`` → {"tr", "te"}
    """
    names: set[str] = set()
    target = getattr(loop_node, "target", None)
    if target is None:
        return names
    for sub in ast.walk(target):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
    return names


def _is_set_params_call(node: ast.AST) -> bool:
    """``model.set_params(...)`` (any args)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "set_params"


def _is_hp_attribute_assign(node: ast.AST) -> bool:
    """``model.<hp_name> = expr`` where hp_name is a known sklearn HP.

    Also matches AugAssign (``model.alpha += 0.1``).
    """
    if isinstance(node, ast.Assign):
        for tgt in node.targets:
            if (isinstance(tgt, ast.Attribute)
                    and tgt.attr in _HYPERPARAM_NAMES):
                return True
        return False
    if isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        tgt = node.target
        if (isinstance(tgt, ast.Attribute)
                and tgt.attr in _HYPERPARAM_NAMES):
            return True
    return False


def _is_parametrized_reassignment(
    node: ast.AST,
    loop_var_names: set[str],
) -> bool:
    """``model = SomeEstimator(C=c, ...)`` where c is a loop variable.

    Also matches positional args that reference loop vars and the constructor
    name looks like an estimator (CamelCase ending in Classifier/Regressor/
    one of a small list of common sklearn estimators).
    """
    if not isinstance(node, ast.Assign):
        return False
    value = node.value
    if not isinstance(value, ast.Call):
        return False
    if not _looks_like_estimator_ctor(value.func):
        return False
    # Any keyword that is a known HP and references a loop var counts.
    for kw in value.keywords:
        if kw.arg in _HYPERPARAM_NAMES and _refs_loop_var(kw.value, loop_var_names):
            return True
    # Positional arg that is itself a loop var also counts (less common but
    # canonical for things like SVC(c) is rare; we still allow it for
    # parametrized estimators with a single primary HP).
    for arg in value.args:
        if _refs_loop_var(arg, loop_var_names):
            return True
    return False


def _looks_like_estimator_ctor(func: ast.expr) -> bool:
    """Heuristic: the call target is a class instantiation that's likely an
    sklearn-style estimator. Matches CamelCase names ending in common
    estimator suffixes, or a small allow-list of well-known classes.
    """
    name: Optional[str] = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    if not name:
        return False
    if not name[:1].isupper():
        return False
    suffixes = ("Classifier", "Regressor", "CV", "Boost", "Forest",
                "Tree", "Net", "Machine", "Model")
    if any(name.endswith(s) for s in suffixes):
        return True
    well_known = {
        "SVC", "SVR", "LinearSVC", "NuSVC", "NuSVR",
        "Lasso", "Ridge", "ElasticNet", "LogisticRegression",
        "KNeighborsClassifier", "KNeighborsRegressor",
        "DecisionTreeClassifier", "DecisionTreeRegressor",
        "MLPClassifier", "MLPRegressor",
        "XGBClassifier", "XGBRegressor",
        "LGBMClassifier", "LGBMRegressor",
        "CatBoostClassifier", "CatBoostRegressor",
        "Pipeline",
    }
    return name in well_known


def _refs_loop_var(node: ast.AST, loop_var_names: set[str]) -> bool:
    if not loop_var_names:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in loop_var_names:
            return True
    return False


def _contains_hp_sweep_subloop(stmt: ast.AST) -> bool:
    """Detect an inner for-loop that iterates over an HP-named iterable.

    Patterns:
        for n in n_estimators_list: ...
        for c in C_grid: ...
        for alpha in alphas: ...
    """
    for sub in ast.walk(stmt):
        if not isinstance(sub, ast.For):
            continue
        iter_name: Optional[str] = None
        if isinstance(sub.iter, ast.Name):
            iter_name = sub.iter.id
        elif isinstance(sub.iter, ast.Attribute):
            iter_name = sub.iter.attr
        if iter_name and _looks_like_hp_iterable_name(iter_name):
            return True
    return False


def _looks_like_hp_iterable_name(name: str) -> bool:
    """``alphas`` / ``C_grid`` / ``n_estimators_list`` etc."""
    low = name.lower()
    parts = set(low.replace("-", "_").split("_"))
    if parts & {hp.lower() for hp in _HYPERPARAM_NAMES}:
        return True
    suffixes = ("_grid", "_values", "_range", "_list", "_choices", "_space")
    if any(low.endswith(s) for s in suffixes):
        # Common HP-grid container names like "param_grid", "search_space"
        return True
    return False


# ── Helper: enumerate test-prediction calls inside a loop body ───────────


def _iter_test_pred_calls(loop_node: ast.AST):
    """Yield (call_node, method_name, arg_name) for every test-prediction
    call inside *loop_node*'s body. Test-likeness is heuristic on argument
    name parts (test/holdout/heldout/unseen/x_eval/...).
    """
    body = getattr(loop_node, "body", []) or []
    orelse = getattr(loop_node, "orelse", []) or []
    for stmt in list(body) + list(orelse):
        for sub in ast.walk(stmt):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.Lambda)):
                continue
            if not isinstance(sub, ast.Call):
                continue
            method_name = _call_method_name(sub)
            if method_name is None:
                continue
            if (method_name not in _TEST_PRED_METHODS
                    and method_name not in _TEST_METRIC_FUNCS):
                continue
            for arg in sub.args:
                arg_name = _arg_name(arg)
                if arg_name and _is_test_like(arg_name):
                    yield sub, method_name, arg_name
                    break


def _call_method_name(node: ast.Call) -> Optional[str]:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _arg_name(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def _is_test_like(name: str) -> bool:
    """Word-boundary matching to avoid false positives like 'contestant'."""
    parts = set(name.lower().replace("-", "_").split("_"))
    word_hints = {"test", "testing", "holdout", "heldout", "unseen"}
    if parts & word_hints:
        return True
    low = name.lower()
    compound_hints = (
        "held_out", "x_eval", "eval_data", "eval_x",
        "eval_label", "eval_y", "final_eval",
    )
    return any(
        low == h or low.startswith(h + "_") or low.endswith("_" + h)
        for h in compound_hints
    )
