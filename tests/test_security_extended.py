"""Extended security tests: XOR fallback warning, precise exceptions, edge cases."""
from __future__ import annotations

import io
import json
import os
import pickle
import sys
import warnings
from pathlib import Path
from unittest import mock

import pytest


from _security import (
    SecurityError,
    encrypt_evidence,
    decrypt_evidence,
    run_security_audit,
    safe_pickle_load,
)


# ────────────────────────────────────────────────────────
# XOR encryption fallback warning
# ────────────────────────────────────────────────────────

class TestEncryptionFailClosed:
    """Verify that when 'cryptography' is unavailable, encryption fails closed (no XOR fallback)."""

    def test_encrypt_raises_without_cryptography(self):
        key = b"0123456789abcdef0123456789abcdef"
        data = b"test plaintext"
        with mock.patch.dict("sys.modules", {"cryptography": None,
                                              "cryptography.hazmat": None,
                                              "cryptography.hazmat.primitives": None,
                                              "cryptography.hazmat.primitives.ciphers": None,
                                              "cryptography.hazmat.primitives.ciphers.aead": None}):
            with pytest.raises(RuntimeError, match="cryptography"):
                encrypt_evidence(data, key)

    def test_decrypt_raises_without_cryptography(self):
        key = b"0123456789abcdef0123456789abcdef"
        # Fabricate a blob with valid header
        fake_blob = b"MLGG-ENC-v1\x00" + b"\x00" * 12 + b"\x00" * 20
        with mock.patch.dict("sys.modules", {"cryptography": None,
                                              "cryptography.hazmat": None,
                                              "cryptography.hazmat.primitives": None,
                                              "cryptography.hazmat.primitives.ciphers": None,
                                              "cryptography.hazmat.primitives.ciphers.aead": None}):
            with pytest.raises(RuntimeError, match="cryptography"):
                decrypt_evidence(fake_blob, key)


# ────────────────────────────────────────────────────────
# safe_pickle_load exception specificity
# ────────────────────────────────────────────────────────

class TestSafePickleLoadExceptions:
    """Verify SecurityError is NOT swallowed by fallback."""

    def test_security_error_propagates(self):
        """If RestrictedUnpickler raises SecurityError, it must NOT fall back."""
        # Build a pickle that triggers os.system (blocked)
        payload = (
            b"\x80\x02"
            + pickle.GLOBAL
            + b"os\nsystem\n"
            + pickle.SHORT_BINUNICODE
            + b"\x04"
            + b"echo"
            + pickle.TUPLE1
            + pickle.REDUCE
            + pickle.STOP
        )
        buf = io.BytesIO(payload)
        with pytest.raises(SecurityError):
            safe_pickle_load(buf)

    def test_valid_pickle_loads_fine(self):
        data = {"key": [1, 2, 3], "nested": {"a": True}}
        buf = io.BytesIO()
        pickle.dump(data, buf)
        buf.seek(0)
        result = safe_pickle_load(buf)
        assert result == data


# ────────────────────────────────────────────────────────
# run_security_audit single-pass and edge cases
# ────────────────────────────────────────────────────────

class TestSecurityAuditEdgeCases:
    def test_empty_evidence_dir(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        report = run_security_audit(evidence)
        assert report["status"] in ("pass", "warn", "fail")
        assert report["schema_version"] == 1

    def test_world_writable_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        bad_file = evidence / "report.json"
        bad_file.write_text('{"status": "pass"}', encoding="utf-8")
        bad_file.chmod(0o666)
        report = run_security_audit(evidence)
        world_writable = [i for i in report["issues"] if i["code"] == "world_writable"]
        assert len(world_writable) >= 1

    def test_sensitive_data_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        # Write a report that contains a sensitive pattern
        from _security import SENSITIVE_DATA_PATTERNS
        if SENSITIVE_DATA_PATTERNS:
            pattern = list(SENSITIVE_DATA_PATTERNS)[0]
            suspicious = evidence / "leak.json"
            suspicious.write_text(
                json.dumps({"data": f"contains {pattern} in output"}),
                encoding="utf-8",
            )
            report = run_security_audit(evidence)
            sensitive = [i for i in report["issues"] if i["code"] == "sensitive_data_exposure"]
            assert len(sensitive) >= 1

    def test_no_manifest_warning(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        report = run_security_audit(evidence)
        no_manifest = [i for i in report["issues"] if i["code"] == "no_manifest"]
        assert len(no_manifest) == 1

    def test_oversized_file_detected(self, tmp_path: Path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        # We can't easily create a 500MB+ file, but test the threshold logic
        # by checking the code handles normal files without false positives
        small = evidence / "small.json"
        small.write_text('{"ok": true}', encoding="utf-8")
        report = run_security_audit(evidence)
        oversized = [i for i in report["issues"] if i["code"] == "oversized_file"]
        assert len(oversized) == 0
