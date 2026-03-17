"""Tests for output formatters."""

import json

from mlgg_lint.formatters import format_json, format_sarif, format_text
from mlgg_lint.models import Diagnostic, Location, Severity


def _make_diag(rule_id="R001", severity=Severity.ERROR, line=10):
    return Diagnostic(
        rule_id=rule_id,
        rule_name="test-rule",
        severity=severity,
        message="Test message.",
        location=Location(file="test.py", line=line, col=0),
        remediation="Fix it.",
    )


def test_format_text_no_diags():
    out = format_text([], color=False)
    assert "No issues" in out


def test_format_text_with_diags():
    out = format_text([_make_diag()], color=False)
    assert "R001" in out
    assert "error" in out.lower()


def test_format_json_structure():
    out = format_json([_make_diag()])
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["rule_id"] == "R001"
    assert data[0]["location"]["line"] == 10


def test_format_sarif_structure():
    out = format_sarif([_make_diag()])
    sarif = json.loads(out)
    assert sarif["version"] == "2.1.0"
    runs = sarif["runs"]
    assert len(runs) == 1
    assert runs[0]["tool"]["driver"]["name"] == "mlgg-lint"
    assert len(runs[0]["results"]) == 1


def test_format_sarif_empty():
    out = format_sarif([])
    sarif = json.loads(out)
    assert len(sarif["runs"][0]["results"]) == 0
