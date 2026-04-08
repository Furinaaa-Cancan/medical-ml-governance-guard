"""Tests for scripts/tools/mlgg_web.py — Flask web UI wizard.

Covers security helpers, CSRF tokens, rate limiter, and app creation.
Does NOT start the actual Flask server.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

# Ensure the tool is importable
TOOL_PATH = Path(__file__).resolve().parent.parent / "scripts" / "tools" / "mlgg_web.py"


# ---------------------------------------------------------------------------
# Import helpers (Flask is required)
# ---------------------------------------------------------------------------
flask = pytest.importorskip("flask", reason="Flask required for mlgg_web tests")

# Import the module under test
sys.path.insert(0, str(TOOL_PATH.parent))
from mlgg_web import (  # noqa: E402
    _check_rate_limit,
    _generate_csrf_token,
    _sanitize_upload_filename,
    _validate_csrf_token,
    _validate_path_no_traversal,
    app,
    _rate_buckets,
    _rate_lock,
    _RATE_LIMIT_MAX_REQUESTS,
)


# ── _sanitize_upload_filename ────────────────────────────────────────────────

class TestSanitizeUploadFilename:
    """Security: uploaded filenames must be safe."""

    def test_simple_csv(self):
        assert _sanitize_upload_filename("data.csv") == "data.csv"

    def test_strips_directory_traversal(self):
        assert _sanitize_upload_filename("../../etc/passwd.csv") == "passwd.csv"

    def test_strips_absolute_path(self):
        assert _sanitize_upload_filename("/tmp/secret/upload.csv") == "upload.csv"

    def test_rejects_non_csv(self):
        with pytest.raises(ValueError):
            _sanitize_upload_filename("script.py")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid upload filename"):
            _sanitize_upload_filename("")

    def test_null_byte_stripped_from_filename(self):
        # Null bytes are stripped; "evil.csv" is a valid name after stripping
        result = _sanitize_upload_filename("evil\x00.csv")
        assert "\x00" not in result
        assert result == "evil.csv"

    def test_rejects_dotfile(self):
        with pytest.raises(ValueError, match="Invalid upload filename"):
            _sanitize_upload_filename(".hidden.csv")

    def test_unix_nested_path_traversal(self):
        """Deep traversal with unix separators gets stripped to basename."""
        result = _sanitize_upload_filename("/a/b/c/../../../data.csv")
        assert result == "data.csv"


# ── _validate_path_no_traversal ─────────────────────────────────────────────

class TestValidatePathNoTraversal:
    """Security: user-supplied paths must not escape to system dirs."""

    def test_normal_path(self, tmp_path):
        p = _validate_path_no_traversal(str(tmp_path), "test")
        assert p == tmp_path.resolve()

    def test_rejects_etc(self):
        with pytest.raises(ValueError, match="forbidden system path"):
            _validate_path_no_traversal("/etc/passwd", "test")

    def test_rejects_proc(self):
        with pytest.raises(ValueError, match="forbidden system path"):
            _validate_path_no_traversal("/proc/self/environ", "test")

    def test_rejects_dev(self):
        with pytest.raises(ValueError, match="forbidden system path"):
            _validate_path_no_traversal("/dev/null", "test")

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError, match="Null byte"):
            _validate_path_no_traversal("/tmp/evil\x00path", "test")

    def test_resolves_dotdot(self, tmp_path):
        """Even with .., the resolved path must be valid."""
        raw = str(tmp_path / "subdir" / "..")
        p = _validate_path_no_traversal(raw, "test")
        assert p == tmp_path.resolve()


# ── CSRF tokens ──────────────────────────────────────────────────────────────

class TestCSRFTokens:
    """CSRF tokens must be hex strings and validate correctly."""

    def test_generates_hex_string(self):
        token = _generate_csrf_token("test-sid-hex")
        assert isinstance(token, str)
        # 32 bytes -> 64 hex chars
        assert len(token) == 64
        assert re.fullmatch(r"[0-9a-f]+", token)

    def test_validates_correct_token(self):
        sid = "test-sid-validate"
        token = _generate_csrf_token(sid)
        assert _validate_csrf_token(sid, token) is True

    def test_rejects_wrong_token(self):
        sid = "test-sid-wrong"
        _generate_csrf_token(sid)
        assert _validate_csrf_token(sid, "deadbeef") is False

    def test_rejects_empty_token(self):
        sid = "test-sid-empty"
        _generate_csrf_token(sid)
        assert _validate_csrf_token(sid, "") is False

    def test_rejects_unknown_session(self):
        assert _validate_csrf_token("nonexistent-sid", "anything") is False


# ── Rate limiter ─────────────────────────────────────────────────────────────

class TestRateLimiter:
    """In-memory rate limiter helper."""

    def test_allows_normal_requests(self):
        ip = "test-ip-normal"
        # Clean up
        with _rate_lock:
            _rate_buckets.pop(ip, None)
        assert _check_rate_limit(ip) is True

    def test_blocks_after_max_requests(self):
        ip = "test-ip-flood"
        with _rate_lock:
            _rate_buckets.pop(ip, None)
        for _ in range(_RATE_LIMIT_MAX_REQUESTS):
            assert _check_rate_limit(ip) is True
        # Next request should be blocked
        assert _check_rate_limit(ip) is False

    def test_different_ips_independent(self):
        ip_a = "test-ip-a"
        ip_b = "test-ip-b"
        with _rate_lock:
            _rate_buckets.pop(ip_a, None)
            _rate_buckets.pop(ip_b, None)
        # Exhaust ip_a
        for _ in range(_RATE_LIMIT_MAX_REQUESTS):
            _check_rate_limit(ip_a)
        assert _check_rate_limit(ip_a) is False
        # ip_b still allowed
        assert _check_rate_limit(ip_b) is True


# ── Flask app creation ───────────────────────────────────────────────────────

class TestFlaskApp:
    """Flask app can be created and basic config is sane."""

    def test_app_exists(self):
        assert app is not None
        assert isinstance(app, flask.Flask)

    def test_max_content_length(self):
        assert app.config["MAX_CONTENT_LENGTH"] == 100 * 1024 * 1024

    def test_index_returns_200(self):
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_security_headers_set(self):
        client = app.test_client()
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "no-store" in resp.headers.get("Cache-Control", "")


# ── Module import smoke test ─────────────────────────────────────────────────

def test_module_importable():
    """mlgg_web.py module can be imported without error (syntax/import check).

    Note: mlgg_web.py has no argparse --help; it starts a Flask server in main().
    So we verify importability rather than running --help.
    """
    # If we got this far, the import at the top of the file succeeded.
    assert _sanitize_upload_filename is not None
    assert _validate_path_no_traversal is not None
    assert _generate_csrf_token is not None
    assert _check_rate_limit is not None
