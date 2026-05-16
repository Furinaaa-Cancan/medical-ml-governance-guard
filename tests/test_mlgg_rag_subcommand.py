"""Tests for the `mlgg rag` subcommand added in G10."""
import subprocess
import sys

import pytest

pytest.importorskip("sentence_transformers")


def _run_mlgg(*args, timeout=60):
    """Run mlgg.py with given args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "scripts/orchestration/mlgg.py", *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def test_mlgg_rag_help() -> None:
    """`mlgg rag --help` returns exit 0 with usage line."""
    rc, out, err = _run_mlgg("rag", "--help")
    assert rc == 0, f"stderr: {err}"
    assert "usage" in (out + err).lower()


def test_mlgg_rag_basic_query() -> None:
    """`mlgg rag "calibration"` returns results table."""
    rc, out, err = _run_mlgg("rag", "calibration", "--top-k", "3")
    assert rc == 0, f"stderr: {err}"
    # Should print something resembling results (table or json or message)
    assert out.strip(), f"empty stdout; stderr: {err}"


def test_mlgg_rag_json_format() -> None:
    """`mlgg rag "..." --format json` produces parseable JSON.

    The orchestrator prints a trailing ``$ <forwarded cmd>`` echo line that
    can be flushed after the subprocess JSON output (stdout-buffering order
    when piped). Strip the trailing echo before parsing.
    """
    import json
    rc, out, err = _run_mlgg("rag", "calibration", "--format", "json", "--top-k", "2")
    assert rc == 0
    # Drop any trailing "$ ..." command-echo lines emitted by mlgg.py.
    body_lines = [
        line for line in out.splitlines()
        if not line.startswith("$ ")
    ]
    body = "\n".join(body_lines).strip()
    data = json.loads(body)
    assert isinstance(data, list)


def test_mlgg_rag_gate_anchored() -> None:
    """`mlgg rag "..." --gate G --codes C1,C2` works."""
    rc, out, err = _run_mlgg(
        "rag", "calibration",
        "--gate", "evaluation_quality_gate",
        "--codes", "MLGG-E01,MLGG-E02",
        "--top-k", "3",
    )
    assert rc == 0, f"stderr: {err}"
