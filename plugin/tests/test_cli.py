"""Tests for the CLI interface."""

import json
from pathlib import Path

from mlgg_lint.cli import main

SAMPLES_DIR = Path(__file__).parent / "samples"


def test_check_text_output(capsys):
    rc = main(["check", str(SAMPLES_DIR / "r001_bad.py"), "--no-color"])
    captured = capsys.readouterr()
    assert "R001" in captured.out
    assert rc == 0  # no --exit-code


def test_check_json_output(capsys):
    rc = main(["check", str(SAMPLES_DIR / "r001_bad.py"), "--format", "json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert any(d["rule_id"] == "R001" for d in data)


def test_check_sarif_output(capsys):
    rc = main(["check", str(SAMPLES_DIR / "r001_bad.py"), "--format", "sarif"])
    captured = capsys.readouterr()
    sarif = json.loads(captured.out)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    assert len(sarif["runs"][0]["results"]) > 0


def test_exit_code_error(capsys):
    rc = main(["check", str(SAMPLES_DIR / "r001_bad.py"), "--exit-code"])
    assert rc == 1  # R001 is ERROR severity


def test_exit_code_clean(capsys):
    rc = main(["check", str(SAMPLES_DIR / "r001_good.py"), "--exit-code",
               "--severity", "error"])
    # r001_good has no ERROR-severity issues; with --severity error other
    # severities are filtered out, so exit code must be 0
    assert rc == 0


def test_disable_flag(capsys):
    rc = main([
        "check", str(SAMPLES_DIR / "r001_bad.py"),
        "--disable", "R001",
        "--format", "json",
    ])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert not any(d["rule_id"] == "R001" for d in data)


def test_rules_subcommand(capsys):
    rc = main(["rules"])
    captured = capsys.readouterr()
    assert "R001" in captured.out
    assert "R010" in captured.out
    assert rc == 0


def test_no_args(capsys):
    rc = main([])
    assert rc == 0


def test_severity_filter_hides_info(capsys):
    """--severity warning should hide INFO-level findings."""
    rc = main([
        "check", str(SAMPLES_DIR / "r016_bad.py"),
        "--severity", "warning",
        "--format", "json",
    ])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # R016 is INFO severity, should be filtered out
    r016 = [d for d in data if d["rule_id"] == "R016"]
    assert len(r016) == 0


def test_severity_filter_shows_errors(capsys):
    """--severity warning should still show ERROR findings."""
    rc = main([
        "check", str(SAMPLES_DIR / "r001_bad.py"),
        "--severity", "warning",
        "--format", "json",
    ])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    r001 = [d for d in data if d["rule_id"] == "R001"]
    assert len(r001) >= 1


def test_exit_code_clean_file():
    """Clean file with --exit-code should return 0."""
    rc = main([
        "check", str(SAMPLES_DIR / "r001_good.py"),
        "--exit-code",
        "--severity", "error",
    ])
    assert rc == 0


def test_check_directory(tmp_path, capsys):
    """Scanning a directory should find issues in contained files."""
    bad = tmp_path / "leaky.py"
    bad.write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "X_scaled = scaler.fit_transform(X)\n"
        "X_train, X_test = train_test_split(X_scaled, y)\n"
    )
    rc = main(["check", str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) >= 1
    assert any(d["rule_id"] == "R001" for d in data)


def test_rules_lists_all_20(capsys):
    """Rules subcommand should list all 20 rules."""
    rc = main(["rules"])
    captured = capsys.readouterr()
    for rid in [f"R{i:03d}" for i in range(1, 21)]:
        assert rid in captured.out, f"Missing rule {rid} in output"
    assert rc == 0


def test_config_file_disables_rule(tmp_path, capsys):
    """Config file should disable specified rules."""
    code = tmp_path / "code.py"
    code.write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "X_scaled = scaler.fit_transform(X)\n"
        "X_train, X_test = train_test_split(X_scaled, y)\n"
    )
    config = tmp_path / ".mlgg-lint.toml"
    config.write_text(
        '[mlgg-lint.rules]\n'
        'R001 = false\n'
    )
    rc = main(["check", str(code), "--config", str(config), "--format", "json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    r001 = [d for d in data if d["rule_id"] == "R001"]
    assert len(r001) == 0, "R001 should be disabled by config"
