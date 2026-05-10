"""Tests for R008 B9 revision — require strong evidence of a forecasting
or sequence task before firing on shuffled train_test_split.

A3 finding: 0 TP / 2 FP. The two FP cases were in PR-029 (mRS outcome at
fixed timepoint), where ``case_admission_id`` / ``relative_sample_date_*``
column names triggered the temporal-keyword heuristic but the actual task
is static patient-level binary classification.
"""

from __future__ import annotations

import textwrap

from mlgg_lint.config import LintConfig
from mlgg_lint.engine import analyze_file


def _check(tmp_path, src: str, name: str = "case.py"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    diags = analyze_file(p, config=LintConfig())
    return [d for d in diags if d.rule_id == "R008"]


# ── Suppressed cases (must NOT fire) ─────────────────────────────────────────

def test_r008_suppressed_on_static_patient_outcome(tmp_path):
    """mRS outcome at fixed timepoint with patient-level rows → no R008."""
    src = """
        from sklearn.model_selection import train_test_split

        # static patient-level binary outcome (mRS 0-2 at 3 months)
        case_admission_id = df['case_admission_id']
        admission_date = df['admission_date']
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    """
    assert _check(tmp_path, src) == []


def test_r008_suppressed_on_temporal_keyword_only(tmp_path):
    """Plain temporal keywords without sequence/forecasting evidence → no R008."""
    src = """
        from sklearn.model_selection import train_test_split

        event_time = df['event_time']
        X = df.drop(columns=['event_time', 'target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert _check(tmp_path, src) == []


# ── Cases that MUST fire ─────────────────────────────────────────────────────

def test_r008_fires_with_datetime_index_assignment(tmp_path):
    """``df.index = pd.to_datetime(...)`` → fire."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df.index = pd.to_datetime(df['event_time'])
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, shuffle=True, test_size=0.2)
    """
    assert len(_check(tmp_path, src)) >= 1


def test_r008_fires_with_to_datetime_call(tmp_path):
    """``pd.to_datetime(...)`` standalone → strong signal, fires."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df['event_time'] = pd.to_datetime(df['event_time'])
        X = df[['event_time', 'feature_a']]
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert len(_check(tmp_path, src)) >= 1


def test_r008_fires_on_3d_lstm_input(tmp_path):
    """LSTM 3D ``(n, T, F)`` input via slicing → fire."""
    src = """
        import numpy as np
        from sklearn.model_selection import train_test_split

        # raw is shape (n, T, F, C) — LSTM input pipeline
        raw = np.zeros((100, 24, 30, 4))
        X_3d = raw[:, :, :, -1]
        y = np.zeros(100)
        X_tr, X_te, y_tr, y_te = train_test_split(X_3d, y, test_size=0.2)
    """
    assert len(_check(tmp_path, src)) >= 1


def test_r008_fires_with_seq_len_kwarg(tmp_path):
    """Explicit ``seq_len`` argument → forecasting evidence, fires."""
    src = """
        from sklearn.model_selection import train_test_split

        seq_len = 24
        horizon = 6
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert len(_check(tmp_path, src)) >= 1


def test_r008_fires_with_lstm_layer(tmp_path):
    """Instantiating an LSTM layer → sequence task, fires."""
    src = """
        from keras.layers import LSTM
        from sklearn.model_selection import train_test_split

        layer = LSTM(units=16)
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert len(_check(tmp_path, src)) >= 1


def test_r008_no_fire_when_shuffle_false(tmp_path):
    """``shuffle=False`` is the recommended pattern; do not fire."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df.index = pd.to_datetime(df['event_time'])
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, shuffle=False, test_size=0.2)
    """
    assert _check(tmp_path, src) == []
