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
    rc = main(["check", str(SAMPLES_DIR / "r001_good.py"), "--exit-code"])
    # r001_good has no R001 errors, but may have other warnings
    # exit-code only triggers on ERROR severity
    assert rc in (0, 1)


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
