"""Tests for R007 — target-as-feature, with CSV-loader-helper exclusion.

W26-L2 (from W25-P2-05 Harutyunyan 2019 case study): R007 was false-firing
on ``mimic3csv.py:20`` —

    def read_admissions_table(mimic3_path):
        admits = dataframe_from_csv(...)
        admits = admits[['SUBJECT_ID', 'HADM_ID', 'ADMITTIME', 'DISCHTIME',
                         'DEATHTIME', 'ETHNICITY', 'DIAGNOSIS']]
        ...

The column ``'DIAGNOSIS'`` lower-cases to ``'diagnosis'``, which is in
R007's ``_TARGET_NAMES`` set, so the assignment-time check fired even
though no model training happens in this helper.  Fix: skip the
assignment-time target-column check when the enclosing function looks
like a data loader (``read_*`` / ``load_*`` / ``get_*`` / ``fetch_*`` /
``parse_*``) and contains no ``.fit*(`` call.  Real leakage is still
caught by Cases 1/2/3 of ``visit_Call``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mlgg_lint.ast_utils import TaintTracker, build_import_map
from mlgg_lint.rules.r007_target_as_feature import TargetAsFeature


REPO = Path(__file__).resolve().parents[1]


def _run_rule_on_source(src: str, display_path: str = "loader.py") -> list:
    """Parse ``src`` and run R007 against it as if it lived at
    ``display_path``.  Bypasses the engine so we can isolate the rule."""
    tree = ast.parse(src)
    im = build_import_map(tree)
    rule = TargetAsFeature(
        file_path=display_path,
        import_map=im,
        taint_tracker=TaintTracker(),
    )
    return rule.check(tree)


# ── TRUE NEGATIVE: CSV-loader helpers must not fire ──────────────────────


def test_r007_excludes_simple_csv_loader():
    """W26-L2: ``read_*`` helper that projects a CSV with a ``'diagnosis'``
    column must NOT fire R007 — no model training happens, no leakage."""
    src = (
        "import pandas as pd\n"
        "def read_admissions_table(path):\n"
        "    admits = pd.read_csv(path)\n"
        "    admits = admits[['SUBJECT_ID', 'HADM_ID', 'ADMITTIME',\n"
        "                     'DISCHTIME', 'DEATHTIME', 'ETHNICITY',\n"
        "                     'DIAGNOSIS']]\n"
        "    return admits\n"
    )
    diags = _run_rule_on_source(src, "mimic3csv.py")
    assert diags == [], (
        f"R007 must not fire on plain CSV-loader helpers; got: "
        f"{[(d.rule_id, d.location.line, d.message) for d in diags]}"
    )


def test_r007_excludes_load_prefix_helper():
    """``load_*`` is also a loader prefix."""
    src = (
        "import pandas as pd\n"
        "def load_outcomes(path):\n"
        "    df = pd.read_csv(path)\n"
        "    df = df[['id', 'outcome']]\n"
        "    return df\n"
    )
    diags = _run_rule_on_source(src, "loader.py")
    assert diags == []


def test_r007_excludes_get_prefix_helper():
    src = (
        "def get_labels(df):\n"
        "    df = df[['patient_id', 'label']]\n"
        "    return df\n"
    )
    diags = _run_rule_on_source(src, "loader.py")
    assert diags == []


# ── TRUE POSITIVE: real leakage must still fire ──────────────────────────


def test_r007_still_catches_real_leakage_same_var():
    """Regression: the original Case 1 pattern (model.fit(df, df)) still fires."""
    src = (
        "model = X()\n"
        "model.fit(df, df)\n"
    )
    diags = _run_rule_on_source(src, "train.py")
    assert len(diags) == 1
    assert diags[0].rule_id == "R007"
    assert "same variable" in diags[0].message.lower()


def test_r007_still_catches_target_in_feature_list_at_module_scope():
    """Module-level ``X = df[['feat', 'target']]; model.fit(X, y)`` still fires.

    Outside any function, the loader-exclusion does not apply.
    """
    src = (
        "X = df[['age', 'sex', 'target']]\n"
        "y = df['target']\n"
        "model.fit(X, y)\n"
    )
    diags = _run_rule_on_source(src, "train.py")
    rule_hits = [d for d in diags if d.rule_id == "R007"]
    assert len(rule_hits) >= 1, (
        f"R007 must still fire on module-level target-in-feature-list; "
        f"got: {[(d.rule_id, d.message) for d in diags]}"
    )


def test_r007_still_catches_fit_inside_loader_named_function():
    """Defensive: if a function is named ``load_pipeline`` but actually
    calls ``.fit()``, it isn't a pure loader — R007 must still fire on
    Case 2 (X and y from same df without ``.drop()``)."""
    src = (
        "def load_pipeline(df):\n"
        "    X = df\n"
        "    y = df\n"
        "    model.fit(X, y)\n"
    )
    diags = _run_rule_on_source(src, "trainer.py")
    rule_hits = [d for d in diags if d.rule_id == "R007"]
    assert len(rule_hits) >= 1, (
        f"R007 must still fire inside loader-named functions that call .fit(); "
        f"got: {[(d.rule_id, d.message) for d in diags]}"
    )


def test_r007_still_catches_assign_target_inside_training_function():
    """``def train_model(): X = df[['feat', 'target']]`` is NOT loader-prefixed
    and must still fire at assignment time."""
    src = (
        "def train_model(df):\n"
        "    X = df[['age', 'sex', 'target']]\n"
        "    return X\n"
    )
    diags = _run_rule_on_source(src, "train.py")
    rule_hits = [d for d in diags if d.rule_id == "R007"]
    assert len(rule_hits) == 1


# ── INTEGRATION: the actual Harutyunyan 2019 false-fire site ─────────────


def test_r007_no_longer_fires_on_harutyunyan_mimic3csv_line_20():
    """W26-L2 regression: the exact W25-P2-05 false-fire site must be clean.

    Reconstructs the relevant snippet from ``mimic3csv.py`` (line 20 is
    the ``admits = admits[[..., 'DIAGNOSIS']]`` re-projection) without
    depending on the cloned repo being present.
    """
    src = (
        "import os\n"
        "import pandas as pd\n"
        "from mimic3benchmark.util import dataframe_from_csv\n"
        "\n"
        "def read_admissions_table(mimic3_path):\n"
        "    admits = dataframe_from_csv(os.path.join(mimic3_path, 'ADMISSIONS.csv'))\n"
        "    admits = admits[['SUBJECT_ID', 'HADM_ID', 'ADMITTIME',\n"
        "                     'DISCHTIME', 'DEATHTIME', 'ETHNICITY',\n"
        "                     'DIAGNOSIS']]\n"
        "    admits.ADMITTIME = pd.to_datetime(admits.ADMITTIME)\n"
        "    return admits\n"
    )
    diags = _run_rule_on_source(src, "mimic3benchmark/mimic3csv.py")
    r007 = [d for d in diags if d.rule_id == "R007"]
    assert r007 == [], (
        f"R007 must not false-fire on Harutyunyan mimic3csv.py:20; "
        f"got: {[(d.location.line, d.message) for d in r007]}"
    )
