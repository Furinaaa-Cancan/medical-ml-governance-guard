"""Tests for R021 revision (B8): the rule must only fire when the loop body
mutates hyperparameters AND uses test data. Plain CV evaluation must NOT
fire.

Background: Agent A3 stratified review found R021 had 0/4 TP rate (100% FP)
because it fired on every per-fold ``predict_proba(X_test)`` inside a CV
loop. The four FP cases were all canonical k-fold evaluation patterns from
PR-086. The revised rule gates on ``_loop_body_mutates_hyperparameters``.
"""

from __future__ import annotations

from pathlib import Path

from mlgg_lint.engine import analyze_file


# ── Negative cases: must NOT fire ──────────────────────────────────────────


def test_r021_plain_cv_loop_not_flagged(tmp_path):
    """Canonical CV evaluation: cv.split() iterates folds, model.fit on
    train, predict_proba on test. No HP tuning happens — must not fire."""
    code = tmp_path / "cv_eval.py"
    code.write_text(
        "from sklearn.ensemble import GradientBoostingClassifier\n"
        "from sklearn.model_selection import StratifiedKFold\n"
        "from sklearn.metrics import roc_auc_score\n"
        "model = GradientBoostingClassifier(n_estimators=50, max_depth=7)\n"
        "skf = StratifiedKFold(n_splits=5)\n"
        "for tr, te in skf.split(X, y):\n"
        "    X_train, X_test = X.iloc[tr], X.iloc[te]\n"
        "    y_train, y_test = y.iloc[tr], y.iloc[te]\n"
        "    model.fit(X_train, y_train)\n"
        "    y_pred_prob = model.predict_proba(X_test)[:, 1]\n"
        "    auc = roc_auc_score(y_test, y_pred_prob)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) == 0, f"Plain CV must not trigger R021, got: {[d.message for d in r021]}"


def test_r021_fold_by_fold_auc_not_flagged(tmp_path):
    """Fold-by-fold AUC reporting (no HP mutation) must not fire."""
    code = tmp_path / "fold_auc.py"
    code.write_text(
        "from sklearn.ensemble import RandomForestClassifier\n"
        "from sklearn.metrics import roc_auc_score\n"
        "m = RandomForestClassifier(n_estimators=100)\n"
        "for fold in folds:\n"
        "    X_train, X_test = fold.train, fold.test\n"
        "    y_train, y_test = fold.train_y, fold.test_y\n"
        "    m.fit(X_train, y_train)\n"
        "    auc = roc_auc_score(y_test, m.predict_proba(X_test)[:, 1])\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) == 0


def test_r021_pr086_fp_files_suppressed():
    """Regression: the four PR-086 audit files that A3 marked FP must now
    produce zero R021 findings."""
    repo_root = Path(__file__).resolve().parents[2]
    fp_files = [
        repo_root / ".cache/audit-repos/PR-086/Gradient Boosting-5倍交叉验证.py",
        repo_root / ".cache/audit-repos/PR-086/RF-5倍交叉验证.py",
        repo_root / ".cache/audit-repos/PR-086/adaboost-5倍交叉验证.py",
        repo_root / ".cache/audit-repos/PR-086/xgb-5倍交叉验证.py",
    ]
    missing = [str(p) for p in fp_files if not p.exists()]
    if missing:
        # Cache may be absent in fresh clones — skip rather than fail hard.
        import pytest
        pytest.skip(f"Audit cache missing: {missing}")
    for fp in fp_files:
        diags = analyze_file(fp)
        r021 = [d for d in diags if d.rule_id == "R021"]
        assert len(r021) == 0, (
            f"{fp.name} still produces R021: "
            f"{[(d.location.line, d.message[:80]) for d in r021]}"
        )


# ── Positive cases: must fire ──────────────────────────────────────────────


def test_r021_hp_grid_reinstantiation_flagged(tmp_path):
    """``for c in grid: m = SVC(C=c); m.fit(X_tr); m.predict(X_te)`` —
    re-instantiation parametrized by the loop variable, test reused per
    iteration. Classic test-set tuning."""
    code = tmp_path / "grid_svc.py"
    code.write_text(
        "from sklearn.svm import SVC\n"
        "for c in [0.1, 1, 10]:\n"
        "    m = SVC(C=c)\n"
        "    m.fit(X_tr, y_tr)\n"
        "    pred = m.predict(X_test)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) >= 1, "HP grid + test reuse must fire R021"


def test_r021_set_params_flagged(tmp_path):
    """``m.set_params(n_estimators=n)`` inside a loop with predict_proba on
    test must fire."""
    code = tmp_path / "set_params.py"
    code.write_text(
        "from sklearn.ensemble import RandomForestClassifier\n"
        "m = RandomForestClassifier()\n"
        "for n in n_estimators_list:\n"
        "    m.set_params(n_estimators=n)\n"
        "    m.fit(X_tr, y_tr)\n"
        "    proba = m.predict_proba(X_test)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) >= 1, "set_params + test reuse must fire R021"


def test_r021_hp_attribute_assign_flagged(tmp_path):
    """``m.alpha = alpha`` inside loop + score on test must fire."""
    code = tmp_path / "attr_assign.py"
    code.write_text(
        "from sklearn.linear_model import Lasso\n"
        "m = Lasso()\n"
        "for alpha in alphas:\n"
        "    m.alpha = alpha\n"
        "    m.fit(X_tr, y_tr)\n"
        "    s = m.score(X_test, y_test)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) >= 1, "HP attribute assign + test score must fire R021"


# ── Edge cases ────────────────────────────────────────────────────────────


def test_r021_nested_hp_sweep_flagged(tmp_path):
    """Nested for-loop iterating over an HP-named iterable inside the
    outer loop body counts as a tuning loop."""
    code = tmp_path / "nested.py"
    code.write_text(
        "from sklearn.ensemble import RandomForestClassifier\n"
        "for fold in folds:\n"
        "    for n in n_estimators_grid:\n"
        "        m = RandomForestClassifier(n_estimators=n)\n"
        "        m.fit(X_tr, y_tr)\n"
        "        m.predict_proba(X_test)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) >= 1


def test_r021_loop_with_no_estimator_call_not_flagged(tmp_path):
    """A loop with set_params but no test-prediction must not fire."""
    code = tmp_path / "no_pred.py"
    code.write_text(
        "from sklearn.ensemble import RandomForestClassifier\n"
        "m = RandomForestClassifier()\n"
        "for n in [10, 20, 30]:\n"
        "    m.set_params(n_estimators=n)\n"
        "    m.fit(X_tr, y_tr)\n"
    )
    diags = analyze_file(code)
    r021 = [d for d in diags if d.rule_id == "R021"]
    assert len(r021) == 0
