"""Tests for NCPR v1 severity-weighted F1 scoring (W22-X2).

Spec: ``references/benchmark/ncpr_v1_severity_rationale.md``.
Companion implementation: ``scripts/rag/evals/ncpr_severity_score.py``.

All tests are offline and deterministic — they exercise the lexical
matcher stub so they pass before W22-X1 lands.
"""
from __future__ import annotations

import math
import warnings

import pytest

from scripts.rag.evals.ncpr_severity_score import (
    SEVERITY_WEIGHTS,
    macro_average,
    per_paper_score,
    severity_weight,
    weighted_tp_fn_fp,
)


# ---------------------------------------------------------------------------
# severity_weight — happy path + ValueError surface
# ---------------------------------------------------------------------------
class TestSeverityWeight:
    def test_happy_path_exact_keys(self):
        assert severity_weight("CRITICAL") == 4.0
        assert severity_weight("HIGH") == 2.0
        assert severity_weight("MEDIUM") == 1.0
        assert severity_weight("LOW") == 0.5

    def test_case_and_whitespace_insensitive(self):
        assert severity_weight("critical") == 4.0
        assert severity_weight("  High  ") == 2.0
        assert severity_weight("Medium") == 1.0

    def test_geometric_progression(self):
        # Spec section 2: ratios form a geometric progression, ratio 2.
        assert SEVERITY_WEIGHTS["CRITICAL"] / SEVERITY_WEIGHTS["HIGH"] == 2.0
        assert SEVERITY_WEIGHTS["HIGH"] / SEVERITY_WEIGHTS["MEDIUM"] == 2.0
        assert SEVERITY_WEIGHTS["MEDIUM"] / SEVERITY_WEIGHTS["LOW"] == 2.0

    def test_unknown_severity_raises(self):
        with pytest.raises(ValueError, match="unknown severity"):
            severity_weight("URGENT")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="None"):
            severity_weight(None)  # type: ignore[arg-type]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            severity_weight("")
        with pytest.raises(ValueError, match="empty"):
            severity_weight("   ")

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="must be str"):
            severity_weight(2.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# weighted_tp_fn_fp — with hand-crafted match_result
# ---------------------------------------------------------------------------
class TestWeightedCounts:
    def test_basic_mixed_match(self):
        flags = [
            {"flag_id": "f1", "severity": "HIGH", "code": "leak_gate"},
            {"flag_id": "f2", "severity": "MEDIUM", "code": "extra_gate"},
        ]
        concerns = [
            {"concern_id": "c1", "severity": "CRITICAL"},
            {"concern_id": "c2", "severity": "LOW"},
        ]
        # f1 matches c1; c2 missed; f2 is an extra flag.
        match_result = {"matches": [{"flag_id": "f1", "concern_id": "c1"}]}
        out = weighted_tp_fn_fp(match_result, flags, concerns)
        assert out["wTP"] == 4.0           # c1 CRITICAL
        assert out["wFN"] == 0.5           # c2 LOW
        assert out["wFP"] == 1.0 * 0.5     # f2 MEDIUM * discount
        # P = 4 / (4 + 0.5) = 8/9
        assert math.isclose(out["wPrecision"], 4.0 / 4.5)
        # R = 4 / (4 + 0.5) = 8/9
        assert math.isclose(out["wRecall"], 4.0 / 4.5)
        assert math.isclose(out["weighted_f1"], 4.0 / 4.5)

    def test_tuple_match_shape_compat(self):
        # Matcher spec section 3 returns tuples; we accept tuples too.
        flags = [{"flag_id": "f1", "severity": "HIGH"}]
        concerns = [{"concern_id": "c1", "severity": "HIGH"}]
        match_result = {"matches": [("f1", "c1", "exact_code")]}
        out = weighted_tp_fn_fp(match_result, flags, concerns)
        assert out["wTP"] == 2.0
        assert out["wFN"] == 0.0
        assert out["wFP"] == 0.0
        assert out["weighted_f1"] == 1.0

    def test_zero_tp_returns_zero_f1_not_nan(self):
        flags = [{"flag_id": "f1", "severity": "HIGH"}]
        concerns = [{"concern_id": "c1", "severity": "HIGH"}]
        out = weighted_tp_fn_fp({"matches": []}, flags, concerns)
        assert out["wTP"] == 0.0
        assert out["wFN"] == 2.0
        assert out["wFP"] == 1.0
        assert out["wPrecision"] == 0.0
        assert out["wRecall"] == 0.0
        assert out["weighted_f1"] == 0.0
        assert not math.isnan(out["weighted_f1"])

    def test_empty_inputs_no_crash(self):
        out = weighted_tp_fn_fp({"matches": []}, [], [])
        assert out == {
            "wTP": 0.0,
            "wFN": 0.0,
            "wFP": 0.0,
            "wPrecision": 0.0,
            "wRecall": 0.0,
            "weighted_f1": 0.0,
        }

    def test_reviewer_severity_drives_tp_weight(self):
        # Spec section 3: weight = REVIEWER severity, never MLGG's.
        flags = [{"flag_id": "f1", "severity": "LOW"}]  # MLGG under-rated
        concerns = [{"concern_id": "c1", "severity": "CRITICAL"}]
        match_result = {"matches": [{"flag_id": "f1", "concern_id": "c1"}]}
        out = weighted_tp_fn_fp(match_result, flags, concerns)
        # wTP must be 4.0 (reviewer's CRITICAL), not 0.5 (MLGG's LOW).
        assert out["wTP"] == 4.0
        assert out["weighted_f1"] == 1.0

    def test_unknown_concern_severity_raises_with_id(self):
        flags = []
        concerns = [
            {"concern_id": "c1", "severity": "HIGH"},
            {"concern_id": "c_bad", "severity": "URGENT"},
        ]
        with pytest.raises(ValueError, match="c_bad"):
            weighted_tp_fn_fp({"matches": []}, flags, concerns)

    def test_unknown_flag_severity_raises_only_when_unmatched(self):
        # Matched flag with bad sev => no error (we only weight unmatched).
        flags = [{"flag_id": "f1", "severity": "BOGUS"}]
        concerns = [{"concern_id": "c1", "severity": "HIGH"}]
        match_result = {"matches": [{"flag_id": "f1", "concern_id": "c1"}]}
        out = weighted_tp_fn_fp(match_result, flags, concerns)
        assert out["wTP"] == 2.0
        # Unmatched flag with bad sev => raises with flag id.
        flags2 = [{"flag_id": "f_bad", "severity": "BOGUS"}]
        with pytest.raises(ValueError, match="f_bad"):
            weighted_tp_fn_fp({"matches": []}, flags2, concerns)


# ---------------------------------------------------------------------------
# per_paper_score — end-to-end via the lexical stub matcher
# ---------------------------------------------------------------------------
class TestPerPaperScore:
    def test_zero_flags_zero_concerns(self):
        out = per_paper_score("p_empty", flags=[], concerns=[])
        assert out["paper_id"] == "p_empty"
        assert out["n_flags"] == 0
        assert out["n_concerns"] == 0
        assert out["paper_excluded"] is True
        assert out["totals"]["weighted_f1"] == 0.0
        assert not math.isnan(out["totals"]["weighted_f1"])

    def test_zero_flags_some_concerns(self):
        # No flags => zero TP, all concerns are FN, F1 = 0.
        concerns = [
            {"concern_id": "c1", "severity": "CRITICAL",
             "concern_text": "leakage", "mlgg_gates": ["leak"]},
        ]
        out = per_paper_score("p_no_flags", flags=[], concerns=concerns)
        assert out["totals"]["wTP"] == 0.0
        assert out["totals"]["wFN"] == 4.0
        assert out["totals"]["wFP"] == 0.0
        assert out["totals"]["weighted_f1"] == 0.0
        assert out["per_severity"]["CRITICAL"]["missed"] == 1
        assert out["paper_excluded"] is False

    def test_three_flags_three_concerns_mixed(self):
        # f1 exact-code matches c1; f2 prefix matches c2; f3 has no
        # corresponding concern; c3 is missed entirely.
        flags = [
            {"flag_id": "f1", "severity": "HIGH",
             "code": "leak", "evidence_text": "label in features"},
            {"flag_id": "f2", "severity": "MEDIUM",
             "code": "calibration_ece_too_high",
             "evidence_text": "ECE 0.18 reported"},
            {"flag_id": "f3", "severity": "LOW",
             "code": "totally_unrelated_gate", "evidence_text": ""},
        ]
        concerns = [
            {"concern_id": "c1", "severity": "CRITICAL",
             "concern_text": "target leakage",
             "mlgg_gates": ["leak"]},
            {"concern_id": "c2", "severity": "HIGH",
             "concern_text": "miscalibration",
             "mlgg_gates": ["calibration_gate"]},
            {"concern_id": "c3", "severity": "MEDIUM",
             "concern_text": "missing CONSORT",
             "mlgg_gates": ["reporting_gate"]},
        ]
        out = per_paper_score("p1", flags, concerns)
        totals = out["totals"]
        # Matched concerns: c1 (CRITICAL=4) + c2 (HIGH=2) = 6.0
        assert totals["wTP"] == 6.0
        # Missed: c3 (MEDIUM=1)
        assert totals["wFN"] == 1.0
        # Extra flag: f3 (LOW=0.5) * 0.5 = 0.25
        assert totals["wFP"] == 0.25
        assert totals["wPrecision"] == pytest.approx(6.0 / 6.25)
        assert totals["wRecall"] == pytest.approx(6.0 / 7.0)
        expected_f1 = 2 * (6.0 / 6.25) * (6.0 / 7.0) / ((6.0 / 6.25) + (6.0 / 7.0))
        assert totals["weighted_f1"] == pytest.approx(expected_f1)
        # Per-severity breakdown sanity
        assert out["per_severity"]["CRITICAL"]["matched"] == 1
        assert out["per_severity"]["HIGH"]["matched"] == 1
        assert out["per_severity"]["MEDIUM"]["missed"] == 1
        assert out["per_severity"]["LOW"]["extra_flags"] == 1
        assert out["paper_excluded"] is False

    def test_runs_with_real_matcher_or_stub(self):
        # per_paper_score MUST run end-to-end either with the W22-X1
        # matcher (if present) or the offline stub. The matcher name
        # is informational only — we only assert the totals are sane.
        out = per_paper_score(
            "p_stub", flags=[], concerns=[
                {"concern_id": "c1", "severity": "LOW"},
            ],
        )
        assert "matcher" in out
        assert isinstance(out["matcher"], str)
        # One concern, no flags => wTP=0, wFN=0.5, F1=0.
        assert out["totals"]["wTP"] == 0.0
        assert out["totals"]["wFN"] == 0.5
        assert out["totals"]["weighted_f1"] == 0.0


# ---------------------------------------------------------------------------
# macro_average
# ---------------------------------------------------------------------------
class TestMacroAverage:
    def _mk(self, paper_id: str, p: float, r: float, f1: float,
            n_concerns: int = 1, excluded: bool = False) -> dict:
        return {
            "paper_id": paper_id,
            "n_flags": 0,
            "n_concerns": n_concerns,
            "matcher": "test",
            "totals": {
                "wTP": 0.0, "wFN": 0.0, "wFP": 0.0,
                "wPrecision": p, "wRecall": r, "weighted_f1": f1,
            },
            "per_severity": {sev: {"matched": 0, "missed": 0, "extra_flags": 0}
                             for sev in SEVERITY_WEIGHTS},
            "paper_excluded": excluded,
        }

    def test_five_papers_equal_weight(self):
        results = [
            self._mk("p1", 1.0, 1.0, 1.0),
            self._mk("p2", 0.5, 0.5, 0.5),
            self._mk("p3", 0.0, 0.0, 0.0),
            self._mk("p4", 0.8, 0.6, 0.685714),
            self._mk("p5", 0.2, 1.0, 0.333333),
        ]
        agg = macro_average(results)
        assert agg["n_papers"] == 5
        assert agg["n_papers_excluded"] == 0
        expected_f1 = (1.0 + 0.5 + 0.0 + 0.685714 + 0.333333) / 5
        assert agg["macro_weighted_f1"] == pytest.approx(expected_f1, abs=1e-5)

    def test_excluded_paper_dropped(self):
        results = [
            self._mk("p1", 1.0, 1.0, 1.0),
            self._mk("p_empty", 0.0, 0.0, 0.0, n_concerns=0, excluded=True),
        ]
        agg = macro_average(results)
        assert agg["n_papers"] == 1
        assert agg["n_papers_excluded"] == 1
        assert agg["macro_weighted_f1"] == 1.0  # p_empty did not drag it down

    def test_empty_list_warns_and_returns_zeros(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agg = macro_average([])
            assert any("empty" in str(x.message).lower() for x in w)
        assert agg["n_papers"] == 0
        assert agg["macro_weighted_f1"] == 0.0
        assert agg["macro_wPrecision"] == 0.0
        assert agg["macro_wRecall"] == 0.0
        # Per-severity scaffolding still present
        assert set(agg["per_severity_totals"]) == set(SEVERITY_WEIGHTS)

    def test_all_papers_excluded_warns_and_returns_zeros(self):
        results = [
            self._mk("p1", 0.0, 0.0, 0.0, n_concerns=0, excluded=True),
            self._mk("p2", 0.0, 0.0, 0.0, n_concerns=0, excluded=True),
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agg = macro_average(results)
            assert any("excluded" in str(x.message).lower() for x in w)
        assert agg["n_papers"] == 0
        assert agg["n_papers_excluded"] == 2
        assert agg["macro_weighted_f1"] == 0.0
