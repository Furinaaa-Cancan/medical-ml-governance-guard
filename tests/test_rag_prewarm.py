"""Tests for the prewarm() helper added in G3 (E4 cold-start mitigation)."""
import pytest
pytest.importorskip("sentence_transformers")

def test_prewarm_returns_status_dict() -> None:
    from scripts.rag.query import prewarm
    status = prewarm()
    assert isinstance(status, dict)
    for k in ("model_load_ms", "index_load_ms", "warm_query_ms", "n_concerns", "cache_was_warm"):
        assert k in status
    assert status["n_concerns"] > 0

def test_prewarm_idempotent() -> None:
    from scripts.rag.query import prewarm
    prewarm()  # warm up
    status = prewarm()
    assert status["model_load_ms"] < 100, f"second call should be cheap: {status['model_load_ms']}ms"

def test_prewarm_cli_flag() -> None:
    import subprocess, sys, json
    result = subprocess.run(
        [sys.executable, "scripts/rag/query.py", "--prewarm"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    status = json.loads(result.stdout.strip())
    assert "n_concerns" in status
