"""Property-based tests for three critical math functions.

Round-2 code review surfaced that MLGG's gate math (calibration, DCA,
sample-size) had no fuzz / property coverage. Structured test cases
pin specific scenarios; hypothesis-based tests assert INVARIANTS —
"for any valid input, this property must hold" — which catch edge
cases authors didn't think to write pinned tests for.

Covers three functions whose outputs are consumed by
publication-grade reports:

1. cohort_definition_gate.riley_sample_size — Riley et al. 2019
   minimum sample size. Invariant: well-formed inputs produce a dict
   with a finite positive n_minimum; boundary prevalences are handled
   without crashing.

2. calibration_dca_gate.expected_calibration_error — equal-frequency
   ECE (Van Calster 2019). Invariant: output is always in [0, 1];
   never NaN or infinity.

3. calibration_dca_gate.net_benefit — DCA net benefit (Vickers 2006).
   Invariant: output is finite, and bounded above by prevalence
   (TP/n ≤ prevalence).

If any property fails, hypothesis shrinks the failing input to a
minimal reproducer, which is then logged for the author to fix.

Scope: these tests are DEFENSIVE — they document the contracts the
functions are expected to satisfy under ANY input that could plausibly
be passed by upstream gate code. They are not a substitute for the
scenario-based tests in test_cohort_definition_gate.py,
test_calibration_dca_gate.py, and test_sample_size_gate.py.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import assume, given, settings, strategies as st

from calibration_dca_gate import expected_calibration_error, net_benefit
from cohort_definition_gate import riley_sample_size


# ── Riley 2019 sample-size formula ──────────────────────────────────

class TestRileySampleSizeProperties:
    """Riley RD et al. Stat Med 2019;38:1276 minimum sample size."""

    @given(
        prevalence=st.floats(min_value=0.001, max_value=0.999,
                             allow_nan=False, allow_infinity=False),
        n_parameters=st.integers(min_value=1, max_value=200),
    )
    @settings(deadline=None, max_examples=50)
    def test_valid_inputs_produce_positive_n_minimum(
        self, prevalence: float, n_parameters: int
    ):
        """For any valid (prevalence, n_parameters) in the interior,
        Riley formula must return a dict with a positive integer
        n_minimum — never zero, never negative, never NaN, never None."""
        result = riley_sample_size(prevalence, n_parameters)
        # Should not be an error dict for interior prevalences.
        assert "error" not in result, (
            f"Riley unexpectedly errored for prevalence={prevalence}, "
            f"n_parameters={n_parameters}: {result}"
        )
        n_min = result["n_minimum"]
        assert isinstance(n_min, int)
        assert n_min > 0
        assert n_min >= n_parameters, (
            f"n_min={n_min} < n_parameters={n_parameters} — can't have "
            f"fewer observations than predictors"
        )

    @given(
        prevalence=st.floats(min_value=0.001, max_value=0.999,
                             allow_nan=False, allow_infinity=False),
        n_parameters=st.integers(min_value=1, max_value=200),
    )
    @settings(deadline=None, max_examples=50)
    def test_e_minimum_scales_with_prevalence(
        self, prevalence: float, n_parameters: int
    ):
        """e_minimum (required events) must equal ceil(n_minimum * phi)
        to within rounding. Catches drift if the scaling factor is
        ever changed."""
        result = riley_sample_size(prevalence, n_parameters)
        n_min = result["n_minimum"]
        e_min = result["e_minimum"]
        expected_e = math.ceil(n_min * prevalence)
        assert e_min == expected_e, (
            f"e_min={e_min} != ceil(n_min * phi)={expected_e} "
            f"(n_min={n_min}, phi={prevalence})"
        )

    @pytest.mark.parametrize("phi", [0.0, 1.0, -0.1, 1.5])
    def test_boundary_prevalences_return_error_dict(self, phi: float):
        """phi outside (0, 1) must return an error dict, not crash
        or produce a nonsensical n."""
        result = riley_sample_size(phi, n_parameters=10)
        assert "error" in result
        assert "n_minimum" not in result


# ── Equal-frequency ECE ─────────────────────────────────────────────

class TestExpectedCalibrationErrorProperties:
    """calibration_dca_gate.expected_calibration_error — Van Calster 2019."""

    @given(
        n=st.integers(min_value=10, max_value=500),
        seed=st.integers(min_value=0, max_value=10_000),
        n_bins=st.integers(min_value=2, max_value=20),
    )
    @settings(deadline=None, max_examples=50)
    def test_ece_always_in_unit_interval(
        self, n: int, seed: int, n_bins: int
    ):
        """ECE is an expected absolute-deviation between predicted and
        observed frequencies, both in [0, 1]. So ECE itself must be
        in [0, 1] for any valid input."""
        rng = np.random.default_rng(seed)
        y_true = rng.integers(0, 2, size=n).astype(int)
        y_score = rng.uniform(0.0, 1.0, size=n).astype(float)
        ece = expected_calibration_error(y_true, y_score, n_bins, min_bin_size=1)
        assert math.isfinite(ece), f"ECE produced non-finite: {ece}"
        assert 0.0 <= ece <= 1.0, f"ECE={ece} out of [0,1]"

    def test_empty_input_returns_ece_of_one(self):
        """Documented edge: empty arrays return ECE=1.0 (maximum
        possible error, interpreted as 'unknown calibration')."""
        y_true = np.asarray([], dtype=int)
        y_score = np.asarray([], dtype=float)
        ece = expected_calibration_error(y_true, y_score, n_bins=10, min_bin_size=1)
        assert ece == 1.0

    @given(
        n=st.integers(min_value=50, max_value=200),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    @settings(deadline=None, max_examples=25)
    def test_perfect_calibration_yields_small_ece(self, n: int, seed: int):
        """When y_true is drawn exactly from Bernoulli(y_score), ECE
        should be small (concentrated around 0 ± sampling noise).
        Upper bound is generous to accommodate small-cohort variance."""
        rng = np.random.default_rng(seed)
        y_score = rng.uniform(0.0, 1.0, size=n).astype(float)
        y_true = (rng.uniform(0.0, 1.0, size=n) < y_score).astype(int)
        ece = expected_calibration_error(y_true, y_score, n_bins=10, min_bin_size=1)
        # Sampling noise bound: for n=50, sqrt(1/4n) ≈ 0.07 per bin.
        # Generous cap at 0.25 accounts for small-n variance.
        assert ece < 0.25, (
            f"Well-calibrated predictor produced unexpectedly large "
            f"ECE={ece} at n={n}, seed={seed}"
        )


# ── DCA net benefit ─────────────────────────────────────────────────

class TestNetBenefitProperties:
    """calibration_dca_gate.net_benefit — Vickers 2006 Decision Curve Analysis."""

    @given(
        n=st.integers(min_value=10, max_value=500),
        seed=st.integers(min_value=0, max_value=10_000),
        threshold=st.floats(min_value=0.01, max_value=0.99,
                            allow_nan=False, allow_infinity=False),
    )
    @settings(deadline=None, max_examples=50)
    def test_net_benefit_is_finite(
        self, n: int, seed: int, threshold: float
    ):
        """NB must be a finite float for any well-formed input. No
        NaN from 0/0, no inf from threshold=1 edge."""
        rng = np.random.default_rng(seed)
        y_true = rng.integers(0, 2, size=n).astype(int)
        y_score = rng.uniform(0.0, 1.0, size=n).astype(float)
        nb = net_benefit(y_true, y_score, threshold)
        assert math.isfinite(nb), f"NB non-finite: {nb}"

    @given(
        n=st.integers(min_value=10, max_value=500),
        seed=st.integers(min_value=0, max_value=10_000),
        threshold=st.floats(min_value=0.01, max_value=0.99,
                            allow_nan=False, allow_infinity=False),
    )
    @settings(deadline=None, max_examples=50)
    def test_net_benefit_upper_bound_is_prevalence(
        self, n: int, seed: int, threshold: float
    ):
        """NB = TP/n - FP/n * w. Since TP/n ≤ prevalence (can't have
        more true positives than total positives), and the subtracted
        term is non-negative, NB ≤ prevalence."""
        rng = np.random.default_rng(seed)
        y_true = rng.integers(0, 2, size=n).astype(int)
        y_score = rng.uniform(0.0, 1.0, size=n).astype(float)
        prevalence = float(np.mean(y_true))
        nb = net_benefit(y_true, y_score, threshold)
        # Small float tolerance for the boundary equality.
        assert nb <= prevalence + 1e-9, (
            f"NB={nb} > prevalence={prevalence} — violates "
            f"TP/n ≤ prevalence bound (threshold={threshold}, n={n})"
        )

    @pytest.mark.parametrize("threshold", [0.0, 1.0, -0.1, 1.5, 1.0001])
    def test_boundary_thresholds_return_zero(self, threshold: float):
        """Threshold outside (0, 1) exclusive returns exactly 0.0 —
        documented edge. Previously a threshold=1.0 would divide by
        zero in weight; this asserts the guard still holds."""
        y_true = np.asarray([0, 1, 1, 0], dtype=int)
        y_score = np.asarray([0.1, 0.9, 0.4, 0.3], dtype=float)
        nb = net_benefit(y_true, y_score, threshold)
        assert nb == 0.0

    def test_empty_input_returns_zero(self):
        """Documented edge: empty arrays return 0.0."""
        y_true = np.asarray([], dtype=int)
        y_score = np.asarray([], dtype=float)
        nb = net_benefit(y_true, y_score, 0.5)
        assert nb == 0.0
