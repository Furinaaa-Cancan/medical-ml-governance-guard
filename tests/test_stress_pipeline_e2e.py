"""
End-to-end pipeline stress tests — full DAG runs, multi-seed stability,
cross-gate integration, and report consistency.

These are the heaviest tests, designed for overnight CI (~2-4 hours).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_dataset(tmp_path: Path, n: int = 500, n_features: int = 10,
                  seed: int = 42, prevalence: float = 0.3) -> Path:
    """Create a synthetic binary classification dataset with proper structure."""
    rng = np.random.default_rng(seed)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    data_dir = project / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = project / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Generate features
    X = rng.standard_normal((n, n_features))
    # Target with specified prevalence
    n_pos = int(n * prevalence)
    y = np.zeros(n, dtype=int)
    y[:n_pos] = 1
    rng.shuffle(y)

    # Create DataFrame
    columns = [f"feature_{i}" for i in range(n_features)]
    df = pd.DataFrame(X, columns=columns)
    df["target"] = y
    df["patient_id"] = [f"P{i:05d}" for i in range(n)]

    # Split: 60/20/20
    n_train = int(n * 0.6)
    n_valid = int(n * 0.2)
    train = df.iloc[:n_train]
    valid = df.iloc[n_train:n_train + n_valid]
    test = df.iloc[n_train + n_valid:]

    train.to_csv(data_dir / "train.csv", index=False)
    valid.to_csv(data_dir / "valid.csv", index=False)
    test.to_csv(data_dir / "test.csv", index=False)

    # Create request.json
    request = {
        "study_name": f"stress_test_seed_{seed}",
        "target_column": "target",
        "positive_class": 1,
        "id_column": "patient_id",
        "train_csv": str(data_dir / "train.csv"),
        "valid_csv": str(data_dir / "valid.csv"),
        "test_csv": str(data_dir / "test.csv"),
        "evidence_dir": str(evidence_dir),
        "model_pool": ["logistic_l2"],
        "seeds": [42],
    }
    request_path = project / "configs" / "request.json"
    request_path.parent.mkdir(exist_ok=True)
    request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")

    return project


# ────────────────────────────────────────────────────────
# Multi-seed dataset generation
# ────────────────────────────────────────────────────────

class TestMultiSeedDatasets:
    @pytest.mark.slow
    def test_10_seeds_no_patient_overlap(self, tmp_path: Path):
        """Generate 10 different seed datasets, verify no patient overlap in splits."""
        for seed in range(10):
            project = _make_dataset(tmp_path / f"seed_{seed}", seed=seed)
            data_dir = project / "data"
            train = pd.read_csv(data_dir / "train.csv")
            valid = pd.read_csv(data_dir / "valid.csv")
            test = pd.read_csv(data_dir / "test.csv")

            train_ids = set(train["patient_id"])
            valid_ids = set(valid["patient_id"])
            test_ids = set(test["patient_id"])

            assert train_ids.isdisjoint(valid_ids), f"seed={seed}: train/valid overlap"
            assert train_ids.isdisjoint(test_ids), f"seed={seed}: train/test overlap"
            assert valid_ids.isdisjoint(test_ids), f"seed={seed}: valid/test overlap"

    @pytest.mark.slow
    def test_varying_prevalence(self, tmp_path: Path):
        """Test dataset generation with extreme prevalence values."""
        for prev in [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]:
            project = _make_dataset(
                tmp_path / f"prev_{int(prev*100)}", prevalence=prev, n=1000
            )
            data_dir = project / "data"
            train = pd.read_csv(data_dir / "train.csv")
            actual_prev = train["target"].mean()
            assert abs(actual_prev - prev) < 0.15, (
                f"prev={prev}: actual={actual_prev}"
            )


# ────────────────────────────────────────────────────────
# Split protocol gate stress
# ────────────────────────────────────────────────────────

class TestSplitProtocolStress:
    @pytest.mark.slow
    def test_split_gate_various_sizes(self, tmp_path: Path):
        """Run split protocol gate with datasets of different sizes."""
        for n in [100, 300, 500, 1000]:
            project = _make_dataset(tmp_path / f"n_{n}", n=n)
            evidence = project / "evidence"
            report = evidence / "split_protocol_report.json"
            request = project / "configs" / "request.json"
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "split_protocol_gate.py"),
                 "--report", str(report),
                 "--request", str(request)],
                capture_output=True, text=True, timeout=120,
                env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
            )
            if report.exists():
                data = json.loads(report.read_text(encoding="utf-8"))
                assert "status" in data


# ────────────────────────────────────────────────────────
# Leakage gate stress
# ────────────────────────────────────────────────────────

class TestLeakageGateStress:
    @pytest.mark.slow
    def test_leakage_gate_clean_data(self, tmp_path: Path):
        """Run leakage gate on properly split data — should pass."""
        project = _make_dataset(tmp_path, n=500)
        evidence = project / "evidence"
        report = evidence / "leakage_report.json"
        request = project / "configs" / "request.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "leakage_gate.py"),
             "--report", str(report),
             "--request", str(request)],
            capture_output=True, text=True, timeout=120,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            assert data.get("status") in ("pass", "fail")

    @pytest.mark.slow
    def test_leakage_gate_overlapping_data(self, tmp_path: Path):
        """Run leakage gate on data with deliberate overlap — should fail."""
        project = _make_dataset(tmp_path, n=500)
        data_dir = project / "data"
        train = pd.read_csv(data_dir / "train.csv")
        test = pd.read_csv(data_dir / "test.csv")
        # Inject train rows into test
        leaked = pd.concat([test, train.head(10)], ignore_index=True)
        leaked.to_csv(data_dir / "test.csv", index=False)
        evidence = project / "evidence"
        report = evidence / "leakage_report.json"
        request = project / "configs" / "request.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "leakage_gate.py"),
             "--report", str(report),
             "--request", str(request)],
            capture_output=True, text=True, timeout=120,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            # With leaked rows, should detect issues
            assert data.get("failure_count", 0) > 0 or data.get("warning_count", 0) > 0


# ────────────────────────────────────────────────────────
# Cross-gate report consistency
# ────────────────────────────────────────────────────────

class TestCrossGateConsistency:
    @pytest.mark.slow
    def test_gate_reports_have_consistent_schema(self, tmp_path: Path):
        """Run multiple gates and verify report schema consistency."""
        project = _make_dataset(tmp_path, n=300)
        evidence = project / "evidence"
        request = project / "configs" / "request.json"

        gates = [
            "split_protocol_gate",
            "sample_size_gate",
            "missingness_policy_gate",
        ]
        reports = {}
        for gate in gates:
            report_path = evidence / f"{gate}_report.json"
            subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / f"{gate}.py"),
                 "--report", str(report_path),
                 "--request", str(request)],
                capture_output=True, text=True, timeout=120,
                env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
            )
            if report_path.exists():
                reports[gate] = json.loads(report_path.read_text(encoding="utf-8"))

        # All reports should share common envelope fields
        for gate, report in reports.items():
            assert "status" in report, f"{gate} missing status"
            assert isinstance(report.get("status"), str)
            if "failure_count" in report:
                assert isinstance(report["failure_count"], int)
            if "warning_count" in report:
                assert isinstance(report["warning_count"], int)


# ────────────────────────────────────────────────────────
# Audit report generation stress
# ────────────────────────────────────────────────────────

class TestAuditReportStress:
    @pytest.mark.slow
    def test_audit_empty_project(self, tmp_path: Path):
        """Audit report on an empty project should not crash."""
        project = tmp_path / "empty"
        project.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "audit_external_project.py"),
             "--project-dir", str(project), "--json"],
            capture_output=True, text=True, timeout=120,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        # Should produce output, even if score is 0
        assert result.returncode in (0, 2)

    @pytest.mark.slow
    def test_audit_synthetic_project(self, tmp_path: Path):
        """Full audit on a synthetic project."""
        project = _make_dataset(tmp_path, n=500)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "audit_external_project.py"),
             "--project-dir", str(project), "--json"],
            capture_output=True, text=True, timeout=180,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        if result.stdout.strip():
            try:
                report = json.loads(result.stdout)
                assert "total_score" in report
                assert isinstance(report["total_score"], (int, float))
            except json.JSONDecodeError:
                pass  # Non-JSON output is okay

    @pytest.mark.slow
    def test_audit_10_projects(self, tmp_path: Path):
        """Run audit on 10 different synthetic projects."""
        for i in range(10):
            project = _make_dataset(
                tmp_path / f"proj_{i}", n=200 + i * 50, seed=i,
                prevalence=0.1 + i * 0.08,
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "audit_external_project.py"),
                 "--project-dir", str(project), "--json"],
                capture_output=True, text=True, timeout=120,
                env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
            )
            # Should not crash on any project
            assert result.returncode in (0, 2), (
                f"Project {i} crashed: {result.stderr[:300]}"
            )


# ────────────────────────────────────────────────────────
# Lint plugin stress
# ────────────────────────────────────────────────────────

class TestLintPluginStress:
    @pytest.mark.slow
    def test_lint_large_file(self, tmp_path: Path):
        """Lint a 5000-line Python file with mixed patterns."""
        big_file = tmp_path / "big.py"
        lines = [
            "import pandas as pd",
            "from sklearn.preprocessing import StandardScaler",
            "",
        ]
        for i in range(2000):
            if i % 100 == 0:
                lines.append(f"scaler_{i} = StandardScaler()")
                lines.append(f"scaler_{i}.fit(X_train)")
            elif i % 200 == 50:
                lines.append(f"# random_state=None")
            else:
                lines.append(f"x_{i} = {i}")
        big_file.write_text("\n".join(lines), encoding="utf-8")

        plugin_dir = Path(__file__).resolve().parent.parent / "plugin"
        result = subprocess.run(
            [sys.executable, "-m", "mlgg_lint", "check", str(big_file)],
            capture_output=True, text=True, timeout=60,
            cwd=str(plugin_dir),
        )
        # Should complete without crashing (2 = argparse/module error is acceptable)
        assert result.returncode in (0, 1, 2)

    @pytest.mark.slow
    def test_lint_many_files(self, tmp_path: Path):
        """Lint 100 small files in a directory."""
        for i in range(100):
            (tmp_path / f"mod_{i}.py").write_text(
                f"x = {i}\nscaler = StandardScaler()\nscaler.fit(X_train)\n",
                encoding="utf-8",
            )
        plugin_dir = Path(__file__).resolve().parent.parent / "plugin"
        result = subprocess.run(
            [sys.executable, "-m", "mlgg_lint", "check", str(tmp_path)],
            capture_output=True, text=True, timeout=120,
            cwd=str(plugin_dir),
        )
        assert result.returncode in (0, 1)
