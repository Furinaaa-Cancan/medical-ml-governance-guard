"""Tests for scripts/training/generate_demo_medical_dataset.py.

Focused on: output file creation, column schema, patient ID disjointness,
binary target, deterministic seeding, and CLI --help smoke test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TOOL_SCRIPT = SCRIPTS_DIR / "training" / "generate_demo_medical_dataset.py"


import generate_demo_medical_dataset as gd

SEED = 20260227

EXPECTED_SPLITS = ["train", "valid", "test", "external_2025_q4", "external_site_b"]

EXPECTED_COLUMNS = [
    "patient_id", "event_time", "y",
    "age", "sex_male", "bmi", "systolic_bp", "heart_rate",
    "wbc", "creatinine", "lactate", "crp",
    "comorbidity_index", "smoke_status",
]


@pytest.fixture()
def generated_data(tmp_path: Path) -> Path:
    """Run main() once and return the project root used."""
    sys.argv = ["prog", "--project-root", str(tmp_path), "--seed", str(SEED)]
    rc = gd.main()
    assert rc == 0, f"main() returned {rc}"
    return tmp_path


# ── Output files exist and are non-empty ─────────────────────────────────────

class TestOutputFiles:
    def test_expected_csvs_exist(self, generated_data: Path):
        data_dir = generated_data / "data"
        for name in EXPECTED_SPLITS:
            csv_path = data_dir / f"{name}.csv"
            assert csv_path.exists(), f"Missing {csv_path}"
            df = pd.read_csv(csv_path)
            assert len(df) > 0, f"{name}.csv is empty"

    def test_report_json_created(self, generated_data: Path):
        report = generated_data / "evidence" / "demo_dataset_report.json"
        assert report.exists(), "Report JSON not created"


# ── Column schema ────────────────────────────────────────────────────────────

class TestColumnSchema:
    def test_train_columns(self, generated_data: Path):
        df = pd.read_csv(generated_data / "data" / "train.csv")
        assert list(df.columns) == EXPECTED_COLUMNS

    def test_valid_columns(self, generated_data: Path):
        df = pd.read_csv(generated_data / "data" / "valid.csv")
        assert list(df.columns) == EXPECTED_COLUMNS

    def test_test_columns(self, generated_data: Path):
        df = pd.read_csv(generated_data / "data" / "test.csv")
        assert list(df.columns) == EXPECTED_COLUMNS


# ── Patient ID disjointness across splits ────────────────────────────────────

class TestPatientDisjoint:
    def test_patient_ids_disjoint(self, generated_data: Path):
        data_dir = generated_data / "data"
        id_sets = {}
        for name in EXPECTED_SPLITS:
            df = pd.read_csv(data_dir / f"{name}.csv")
            id_sets[name] = set(df["patient_id"].unique())

        split_names = list(id_sets.keys())
        for i, a in enumerate(split_names):
            for b in split_names[i + 1 :]:
                overlap = id_sets[a] & id_sets[b]
                assert len(overlap) == 0, (
                    f"Patient overlap between {a} and {b}: {overlap}"
                )


# ── Target column is binary (0/1) ───────────────────────────────────────────

class TestTargetBinary:
    def test_y_values_binary(self, generated_data: Path):
        data_dir = generated_data / "data"
        for name in EXPECTED_SPLITS:
            df = pd.read_csv(data_dir / f"{name}.csv")
            unique_vals = set(df["y"].unique())
            assert unique_vals <= {0, 1}, (
                f"{name} target has non-binary values: {unique_vals}"
            )


# ── Deterministic output with same seed ──────────────────────────────────────

class TestDeterminism:
    def test_same_seed_produces_identical_output(self, tmp_path: Path):
        root_a = tmp_path / "run_a"
        root_b = tmp_path / "run_b"
        root_a.mkdir()
        root_b.mkdir()

        for root in (root_a, root_b):
            sys.argv = ["prog", "--project-root", str(root), "--seed", str(SEED)]
            gd.main()

        for name in EXPECTED_SPLITS:
            df_a = pd.read_csv(root_a / "data" / f"{name}.csv")
            df_b = pd.read_csv(root_b / "data" / f"{name}.csv")
            pd.testing.assert_frame_equal(df_a, df_b, obj=f"{name} determinism")


# ── CLI --help smoke test ────────────────────────────────────────────────────

class TestCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "project-root" in result.stdout.lower()
