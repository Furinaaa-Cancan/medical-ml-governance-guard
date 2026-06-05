"""R028 hardening (Phase 2, F2.2): catch omics columns built via f-strings,
comprehensions, tuples, and sets — not only literal gene_-prefixed lists —
while staying conservative on legitimate EHR code.

(`df.columns` loaded from a CSV at runtime is intentionally out of scope: a
static linter cannot see runtime column names; that belongs to a gate.)
"""
from __future__ import annotations

import textwrap

from mlgg_lint.config import LintConfig
from mlgg_lint.engine import analyze_file


def _check(tmp_path, src: str, name: str = "case.py"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    return [d for d in analyze_file(p, config=LintConfig()) if d.rule_id == "R028"]


# ── new detected forms (must fire) ───────────────────────────────────────────

def test_r028_fires_on_fstring_list_comprehension(tmp_path):
    assert len(_check(tmp_path, 'cols = [f"gene_{i}" for i in range(1000)]\n')) >= 1


def test_r028_fires_on_generator_comprehension(tmp_path):
    assert len(_check(tmp_path, 'cols = list(f"snp_{i}" for i in range(500))\n')) >= 1


def test_r028_fires_on_tuple_of_omics(tmp_path):
    assert len(_check(tmp_path, "cols = ('gene_a', 'snp_b', 'cpg_c')\n")) >= 1


def test_r028_fires_on_set_of_omics(tmp_path):
    assert len(_check(tmp_path, "cols = {'gene_a', 'probe_b', 'ENSG000001'}\n")) >= 1


def test_r028_fires_on_mixed_const_and_fstring_list(tmp_path):
    assert len(_check(tmp_path, 'cols = ["gene_1", f"gene_{x}", "snp_3"]\n')) >= 1


# ── conservative: legitimate non-omics code must NOT fire ────────────────────

def test_r028_quiet_on_ehr_list(tmp_path):
    assert _check(tmp_path, "cols = ['age', 'sex', 'bmi', 'systolic_bp', 'a1c']\n") == []


def test_r028_quiet_on_non_omics_comprehension(tmp_path):
    assert _check(tmp_path, 'cols = [f"lab_{i}" for i in range(50)]\n') == []


def test_r028_quiet_on_general_prefix(tmp_path):
    # 'general_' must NOT match '^gene_'
    assert _check(tmp_path, 'cols = [f"general_{i}" for i in range(50)]\n') == []


def test_r028_quiet_below_threshold_in_tuple(tmp_path):
    assert _check(tmp_path, "cols = ('age', 'gene_count', 'sex')\n") == []


# ── dict-comprehension bypass (review finding) ───────────────────────────────

def test_r028_fires_on_dict_comprehension_keys(tmp_path):
    # {f"gene_{i}": 0 for i in range(1000)} builds thousands of omics columns
    # via dict KEYS — DictComp has no .elt, so it slipped past the rule.
    assert len(_check(tmp_path, 'cols = {f"gene_{i}": 0 for i in range(1000)}\n')) >= 1


def test_r028_quiet_on_non_omics_dict_comprehension(tmp_path):
    assert _check(tmp_path, 'cols = {f"lab_{i}": 0 for i in range(50)}\n') == []
