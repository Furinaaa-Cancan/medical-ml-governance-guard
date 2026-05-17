"""Tests for R002 — Keras ``validation_data=`` kwarg false-fire (W26-L1).

W25-P2-05 (Harutyunyan 2019) surfaced R002 firing falsely on
``in_hospital_mortality/main.py:143`` where the code reads::

    model.fit(X_train, y_train, validation_data=(X_val, y_val))

The first positional arg is training data; ``validation_data`` is
held-out monitoring data passed to Keras for per-epoch evaluation
(not training input). R002 must skip ``.fit()`` calls whose kwargs
include ``validation_data=``. Real fit-on-test calls without that
kwarg must still fire (regression).
"""

from __future__ import annotations

import ast

from mlgg_lint.ast_utils import TaintTracker, build_import_map
from mlgg_lint.rules.r002_scaler_on_test import ScalerOnTest


def _run_rule_on_source(src: str, display_path: str = "user_model.py") -> list:
    """Parse *src*, pre-populate taint from train_test_split unpackings,
    then run R002 in isolation (bypasses the engine for unit-level focus)."""
    tree = ast.parse(src)
    im = build_import_map(tree)
    tracker = TaintTracker()

    # Mirror engine pass 1 just enough for these fixtures: record taint
    # from train_test_split unpacking. Anything not coming from a split
    # falls back to name-heuristic via TaintTracker.is_test_or_valid.
    from mlgg_lint.ast_utils import call_name, extract_tuple_targets, matches_any
    split_calls = {"train_test_split", "sklearn.model_selection.train_test_split"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fqn = call_name(node.value, im)
            if fqn and matches_any(fqn, split_calls):
                for target in node.targets:
                    tracker.record_split(extract_tuple_targets(target), node.lineno)

    rule = ScalerOnTest(
        file_path=display_path,
        import_map=im,
        taint_tracker=tracker,
    )
    return rule.check(tree)


# ── TRUE NEGATIVE: Keras validation_data= kwarg ──────────────────────────

def test_r002_excludes_keras_validation_data():
    """The W25-P2-05 Harutyunyan pattern. ``validation_data=`` means the
    first positional arg is by Keras convention training input, not test."""
    src = (
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_val, y_train, y_val = train_test_split(X, y)\n"
        "model.fit(X_train, y_train, validation_data=(X_val, y_val))\n"
    )
    diags = _run_rule_on_source(src)
    assert diags == [], (
        f"R002 must not fire on Keras-style fit(...) with validation_data= "
        f"kwarg; got {[d.message for d in diags]}"
    )


def test_r002_excludes_validation_data_even_when_first_arg_looks_testy():
    """Defensive: even if the first positional arg's NAME tripped the
    taint heuristic, presence of validation_data= still suppresses R002
    because Keras semantics fix the role of arg 0 as training input."""
    src = (
        "model.fit(X_valid, y_valid, validation_data=(X_holdout, y_holdout))\n"
    )
    diags = _run_rule_on_source(src)
    assert diags == []


# ── TRUE POSITIVE (regression): real fit-on-test still fires ─────────────

def test_r002_still_catches_real_fit_on_test():
    """Regression guard: a bare fit on test data with no validation_data=
    kwarg is still flagged after the W26-L1 exclusion lands."""
    src = (
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n"
        "scaler.fit(X_test)\n"
    )
    diags = _run_rule_on_source(src)
    assert len(diags) == 1, (
        f"expected R002 to still fire on scaler.fit(X_test); "
        f"got {len(diags)} diagnostics: {[d.message for d in diags]}"
    )
    assert diags[0].rule_id == "R002"


def test_r002_fires_on_model_fit_on_test_without_validation_data():
    """Another regression slice: ``model.fit(X_test, y_test)`` with no
    validation_data= kwarg is unambiguous fit-on-test, must still fire."""
    src = (
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n"
        "model.fit(X_test, y_test)\n"
    )
    diags = _run_rule_on_source(src)
    assert len(diags) == 1
    assert diags[0].rule_id == "R002"
