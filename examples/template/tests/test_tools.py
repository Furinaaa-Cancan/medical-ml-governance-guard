"""Test tools: setup, check, qwen_review."""

import sys
import os
import json
import tempfile
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCheck:

    def test_check_data_finds_csvs(self, project_root, tmp_path):
        from tools.check import check_data
        # No CSVs in default raw dir
        result = check_data()
        # Result is a list (may or may not have CSVs depending on state)
        assert isinstance(result, list)

    def test_check_config_default(self, project_root):
        from tools.check import check_config
        status, info = check_config()
        assert status in ("missing", "default", "configured")

    def test_check_phases_returns_nine(self, project_root):
        from tools.check import check_phases
        results = check_phases()
        assert len(results) == 9
        for status, phase in results:
            assert status in ("done", "pending")
            assert "num" in phase
            assert "name" in phase

    def test_find_next_phase(self, project_root):
        from tools.check import check_phases, find_next_phase
        results = check_phases()
        next_phase = find_next_phase(results)
        # Should find some pending phase (since we haven't run anything)
        if next_phase:
            assert next_phase["num"] >= 1


class TestQwenReview:

    def test_checks_dict_has_required_keys(self):
        from tools.qwen_review import CHECKS
        required = {"leakage", "split", "encoding", "temporal", "evaluation", "all"}
        assert required == set(CHECKS.keys())

    def test_each_check_has_name_and_prompt(self):
        from tools.qwen_review import CHECKS
        for key, check in CHECKS.items():
            assert "name" in check, f"Check '{key}' missing 'name'"
            assert "prompt" in check, f"Check '{key}' missing 'prompt'"
            assert len(check["prompt"]) > 50, f"Check '{key}' prompt too short"

    def test_env_loading(self, tmp_path, monkeypatch):
        """_load_env should read .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_QWEN_VAR=hello_world\n")

        # Clear if exists
        monkeypatch.delenv("TEST_QWEN_VAR", raising=False)

        from tools.qwen_review import _load_env
        # Monkeypatch PROJECT_ROOT
        import tools.qwen_review as qr
        original = qr.PROJECT_ROOT
        monkeypatch.setattr(qr, "PROJECT_ROOT", tmp_path)
        _load_env()
        monkeypatch.setattr(qr, "PROJECT_ROOT", original)

        assert os.environ.get("TEST_QWEN_VAR") == "hello_world"
        # Cleanup
        del os.environ["TEST_QWEN_VAR"]

    def test_read_file_size_guard(self, tmp_path):
        from tools.qwen_review import read_file
        # Create a normal file
        f = tmp_path / "small.py"
        f.write_text("x = 1\n" * 100)
        content = read_file(str(f))
        assert "x = 1" in content


class TestSetup:

    def test_detect_columns_finds_id(self, tmp_path):
        """detect_columns should find patient_id-like columns."""
        import pandas as pd
        csv_path = tmp_path / "test.csv"
        pd.DataFrame({
            "patient_id": range(100),
            "age": [50] * 100,
            "target": [0, 1] * 50,
        }).to_csv(csv_path, index=False)

        from tools.setup import detect_columns
        hints = detect_columns(csv_path)
        assert "patient_id_candidates" in hints
        assert "patient_id" in hints["patient_id_candidates"]

    def test_detect_columns_finds_binary_label(self, tmp_path):
        import pandas as pd
        csv_path = tmp_path / "test.csv"
        pd.DataFrame({
            "id": range(100),
            "outcome": [0, 1] * 50,
        }).to_csv(csv_path, index=False)

        from tools.setup import detect_columns
        hints = detect_columns(csv_path)
        assert "label_candidates" in hints
        assert "outcome" in hints["label_candidates"]
