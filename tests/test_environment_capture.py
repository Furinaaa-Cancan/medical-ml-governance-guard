"""Reproducibility: build_report_envelope binds the numerical environment (F2.4).

Package versions (sklearn/numpy/pandas/scipy) are captured into every sealed
report so a reviewer can reconstruct the environment that produced the metrics —
the "package versions never bound into the bundle" review finding.
"""
from __future__ import annotations

from _gate_framework import build_report_envelope, capture_environment


def test_capture_environment_shape():
    env = capture_environment()
    assert isinstance(env["python"], str) and env["python"]
    pkgs = env["packages"]
    for name in ("numpy", "pandas", "scikit-learn", "scipy"):
        assert name in pkgs  # value may be None if a package is not installed


def test_capture_environment_is_cached_identical():
    assert capture_environment() == capture_environment()


def test_envelope_includes_environment():
    env = build_report_envelope(
        gate_name="g", status="pass", strict_mode=False, failures=[], warnings=[],
    )
    assert "environment" in env
    assert "python" in env["environment"]
    assert set(env["environment"]["packages"]) == {"numpy", "pandas", "scikit-learn", "scipy"}
