"""Tests for R004 B9 revision — suppress when data is already deduplicated
to one row per patient upstream of train_test_split.

A3 finding: 2 TP / 3 FP. The three FP cases all involved an upstream
``link_patient_id_to_outcome`` (or ``drop_duplicates(['patient_id'])``)
call before the split, so ``groups=`` is unnecessary.
"""

from __future__ import annotations

import textwrap

from mlgg_lint.config import LintConfig
from mlgg_lint.engine import analyze_file


def _check(tmp_path, src: str, name: str = "case.py"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    diags = analyze_file(p, config=LintConfig())
    return [d for d in diags if d.rule_id == "R004"]


# ── Suppressed cases (must NOT fire) ─────────────────────────────────────────

def test_r004_suppressed_when_drop_duplicates_upstream(tmp_path):
    """drop_duplicates(['patient_id']) before split → suppress R004."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df = pd.read_csv('cohort.csv')
        df = df.drop_duplicates(subset=['patient_id'])
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert _check(tmp_path, src) == []


def test_r004_suppressed_with_positional_drop_duplicates(tmp_path):
    """drop_duplicates('patient_id') (positional) → suppress R004."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df = pd.read_csv('cohort.csv')
        df = df.drop_duplicates('patient_id')
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert _check(tmp_path, src) == []


def test_r004_suppressed_when_groupby_first(tmp_path):
    """df.groupby('patient_id').first() before split → suppress R004."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df = pd.read_csv('cohort.csv')
        pat = df.groupby('patient_id').first().reset_index()
        X = pat.drop(columns=['target'])
        y = pat['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    assert _check(tmp_path, src) == []


def test_r004_suppressed_when_groupby_agg(tmp_path):
    """df.groupby('subject_id').agg(...) before split → suppress R004."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df = pd.read_csv('cohort.csv')
        pat = df.groupby('subject_id').agg({'val': 'mean', 'target': 'max'})
        X_tr, X_te, y_tr, y_te = train_test_split(pat, pat['target'])
    """
    assert _check(tmp_path, src) == []


def test_r004_suppressed_with_per_patient_docstring(tmp_path):
    """A docstring stating 'one row per patient' → suppress R004."""
    src = '''
        from sklearn.model_selection import train_test_split

        def split_cohort(df, y):
            """Split a cohort DataFrame.

            Note: ``df`` is one row per patient; per-patient deduplication
            has been performed upstream.
            """
            return train_test_split(df, y, test_size=0.2)

        # invocation site so patient_context fires:
        patient_id = 1
        result = split_cohort(some_df, some_y)
    '''
    assert _check(tmp_path, src) == []


def test_r004_suppressed_with_link_patient_id_helper(tmp_path):
    """``link_patient_id_to_outcome`` (PR-029 pattern) → suppress R004."""
    src = """
        from sklearn.model_selection import train_test_split

        all_pids_with_outcome = link_patient_id_to_outcome(y, outcome)
        pid_train, pid_test, y_pid_train, y_pid_test = train_test_split(
            all_pids_with_outcome.patient_id.tolist(),
            all_pids_with_outcome.outcome.tolist(),
            test_size=0.2,
        )
    """
    assert _check(tmp_path, src) == []


def test_r004_suppressed_with_avoid_duplicates_text(tmp_path):
    """A comment-style string constant near the split → suppress R004."""
    src = '''
        from sklearn.model_selection import train_test_split

        explanation = "Reduce every patient to a single outcome to avoid duplicates"
        patient_id = df['patient_id']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    '''
    assert _check(tmp_path, src) == []


# ── Cases that MUST still fire ────────────────────────────────────────────────

def test_r004_fires_on_visit_level_data(tmp_path):
    """Multiple visits per patient with no dedup → R004 must fire."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df_visits = pd.read_csv('visits.csv')
        patient_id = df_visits['patient_id']
        X = df_visits.drop(columns=['target'])
        y = df_visits['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    diags = _check(tmp_path, src)
    assert len(diags) >= 1


def test_r004_fires_when_no_dedup_visible(tmp_path):
    """Plain patient-level cohort but no dedup operation → R004 must fire."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df = pd.read_csv('admissions.csv')
        admission_id = df['admission_id']
        X = df.drop(columns=['target'])
        y = df['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    diags = _check(tmp_path, src)
    assert len(diags) >= 1


def test_r004_groupby_without_patient_key_does_not_suppress(tmp_path):
    """``groupby('site').first()`` (non-patient key) must NOT suppress R004."""
    src = """
        import pandas as pd
        from sklearn.model_selection import train_test_split

        df_visits = pd.read_csv('visits.csv')
        patient_id = df_visits['patient_id']
        agg = df_visits.groupby('site').first()
        X = df_visits.drop(columns=['target'])
        y = df_visits['target']
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)
    """
    diags = _check(tmp_path, src)
    assert len(diags) >= 1
