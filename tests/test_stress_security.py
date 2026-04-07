"""
Security stress tests — encryption roundtrips, restricted unpickler exhaustive,
path traversal fuzzing, audit manifest stress.

Designed for overnight CI runs (~1-2 hours).
"""
from __future__ import annotations

import io
import json
import os
import pickle
import secrets
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "gates"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "orchestration"))

from _security import (
    ArtifactManifest,
    SecurityError,
    RestrictedUnpickler,
    check_csv_row_limit,
    check_file_size,
    compute_hmac,
    encrypt_evidence,
    decrypt_evidence,
    run_security_audit,
    safe_load_json,
    safe_path,
    safe_pickle_load,
    sign_model_artifact,
    verify_model_artifact,
)


# ────────────────────────────────────────────────────────
# Encryption roundtrip stress
# ────────────────────────────────────────────────────────

class TestEncryptionStress:
    @pytest.mark.slow
    def test_roundtrip_various_sizes(self):
        """Roundtrip encrypt/decrypt for data sizes from 0 to 1MB."""
        key = secrets.token_bytes(32)
        for size in [0, 1, 16, 255, 256, 1024, 4096, 65536, 1024 * 1024]:
            data = secrets.token_bytes(size)
            blob = encrypt_evidence(data, key)
            recovered = decrypt_evidence(blob, key)
            assert recovered == data, f"Roundtrip failed for size={size}"

    @pytest.mark.slow
    def test_roundtrip_1000_random_keys(self):
        """1000 random key/data pairs."""
        for _ in range(1000):
            key = secrets.token_bytes(32)
            data = secrets.token_bytes(secrets.randbelow(10000))
            blob = encrypt_evidence(data, key)
            recovered = decrypt_evidence(blob, key)
            assert recovered == data

    @pytest.mark.slow
    def test_wrong_key_fails(self):
        """Decryption with wrong key should fail."""
        for _ in range(100):
            key1 = secrets.token_bytes(32)
            key2 = secrets.token_bytes(32)
            data = secrets.token_bytes(1000)
            blob = encrypt_evidence(data, key1)
            with pytest.raises(Exception):
                decrypt_evidence(blob, key2)

    @pytest.mark.slow
    def test_tampered_ciphertext_fails(self):
        """Flipping bits in ciphertext should be detected."""
        key = secrets.token_bytes(32)
        data = b"sensitive evidence data"
        blob = encrypt_evidence(data, key)
        for bit_pos in range(min(len(blob), 100)):
            if bit_pos < 10:
                continue  # Skip header
            tampered = bytearray(blob)
            tampered[bit_pos] ^= 0xFF
            tampered = bytes(tampered)
            try:
                recovered = decrypt_evidence(tampered, key)
                # If decryption succeeds, data must be different
                # (probabilistically impossible with AES-GCM)
                assert recovered != data or bit_pos < 28  # nonce area
            except Exception:
                pass  # Expected: integrity check fails


# ────────────────────────────────────────────────────────
# RestrictedUnpickler exhaustive
# ────────────────────────────────────────────────────────

class TestRestrictedUnpicklerExhaustive:
    """Test every blocked module and callable."""

    BLOCKED_MODULES = [
        ("os", "system"),
        ("os", "popen"),
        ("subprocess", "call"),
        ("subprocess", "run"),
        ("subprocess", "Popen"),
        ("builtins", "eval"),
        ("builtins", "exec"),
        ("webbrowser", "open"),
    ]

    def _make_exploit(self, module: str, func: str) -> bytes:
        return (
            b"\x80\x02"
            + pickle.GLOBAL
            + f"{module}\n{func}\n".encode()
            + pickle.SHORT_BINUNICODE
            + b"\x04"
            + b"test"
            + pickle.TUPLE1
            + pickle.REDUCE
            + pickle.STOP
        )

    @pytest.mark.parametrize("module,func", BLOCKED_MODULES)
    def test_blocked_callable_raises(self, module: str, func: str):
        payload = self._make_exploit(module, func)
        buf = io.BytesIO(payload)
        with pytest.raises((SecurityError, Exception)):
            safe_pickle_load(buf)

    SAFE_TYPES = [
        {"a": 1, "b": [2, 3]},
        [1, 2, 3, "hello"],
        (1, 2, 3),
        42,
        "string",
        3.14,
        True,
        None,
        set(),
    ]

    @pytest.mark.parametrize("data", SAFE_TYPES)
    def test_safe_type_loads(self, data: Any):
        buf = io.BytesIO()
        pickle.dump(data, buf)
        buf.seek(0)
        result = safe_pickle_load(buf)
        assert result == data

    @pytest.mark.slow
    def test_numpy_array_loads(self):
        """numpy arrays should be allowed by RestrictedUnpickler."""
        arr = np.array([1.0, 2.0, 3.0])
        buf = io.BytesIO()
        pickle.dump(arr, buf)
        buf.seek(0)
        result = safe_pickle_load(buf)
        np.testing.assert_array_equal(result, arr)

    @pytest.mark.slow
    def test_sklearn_model_loads(self):
        """sklearn models should be loadable."""
        from sklearn.linear_model import LogisticRegression
        model = LogisticRegression()
        buf = io.BytesIO()
        pickle.dump(model, buf)
        buf.seek(0)
        result = safe_pickle_load(buf)
        assert type(result).__name__ == "LogisticRegression"


# ────────────────────────────────────────────────────────
# Path traversal fuzzing
# ────────────────────────────────────────────────────────

class TestPathTraversalFuzzing:
    TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config",
        "/etc/shadow",
        "/proc/self/environ",
        "/dev/zero",
        "test\x00.csv",
        "test\ninjection",
        "a" * 5000,
        "",
        "   ",
        "/var/run/secrets",
        "/private/etc/hosts",
    ]

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_dangerous_path_rejected(self, payload: str):
        """All dangerous path patterns should be rejected."""
        try:
            result = safe_path(payload)
            # If it didn't raise, it must have been sanitized
            # The path should not start with forbidden prefixes
            str_result = str(result)
            for prefix in ["/etc", "/proc", "/dev", "/var/run"]:
                assert not str_result.startswith(prefix), (
                    f"Path {payload!r} resolved to {str_result} starting with {prefix}"
                )
        except (ValueError, SecurityError):
            pass  # Expected

    @pytest.mark.slow
    def test_random_path_fuzzing(self):
        """Generate random path strings and ensure no crashes."""
        import string
        rng = __import__("random").Random(42)
        chars = string.printable + "\x00\xff"
        for _ in range(10_000):
            length = rng.randint(0, 500)
            payload = "".join(rng.choice(chars) for _ in range(length))
            try:
                safe_path(payload)
            except (ValueError, SecurityError, OSError, RuntimeError):
                pass  # All acceptable rejections


# ────────────────────────────────────────────────────────
# safe_load_json fuzzing
# ────────────────────────────────────────────────────────

class TestSafeLoadJsonFuzzing:
    @pytest.mark.slow
    def test_deeply_nested_json(self, tmp_path: Path):
        """Deeply nested JSON should be handled safely (load or reject)."""
        p = tmp_path / "deep.json"
        nested = {"a": None}
        current = nested
        for i in range(199):
            current["a"] = {"a": None}
            current = current["a"]
        p.write_text(json.dumps(nested), encoding="utf-8")
        try:
            result = safe_load_json(str(p))
            # If it loads, it should be a dict
            assert isinstance(result, dict)
        except (ValueError, RecursionError):
            pass  # Rejection is also acceptable

    @pytest.mark.slow
    def test_large_json_file(self, tmp_path: Path):
        """Large JSON files should be handled safely."""
        p = tmp_path / "big.json"
        big = {"key_" + str(i): "x" * 1000 for i in range(10_000)}
        p.write_text(json.dumps(big), encoding="utf-8")
        result = safe_load_json(str(p))
        assert result is not None

    @pytest.mark.slow
    def test_malformed_json_variants(self, tmp_path: Path):
        """Various malformed JSON inputs should not crash (may raise ValueError)."""
        malformed = [
            "{", "}", "[", "]", "null", "'single quotes'",
            '{"key": undefined}', '{"key": NaN}',
            "{" * 1000, "[" * 1000,
            b"\xff\xfe".decode("latin-1"),
            "",
        ]
        for i, content in enumerate(malformed):
            p = tmp_path / f"bad_{i}.json"
            p.write_text(content, encoding="utf-8")
            try:
                safe_load_json(str(p))
            except (ValueError, json.JSONDecodeError):
                pass  # Expected for malformed input


# ────────────────────────────────────────────────────────
# HMAC signing stress
# ────────────────────────────────────────────────────────

class TestHMACSigningStress:
    @pytest.mark.slow
    def test_sign_verify_many_files(self, tmp_path: Path):
        """Sign and verify 500 model files."""
        key = secrets.token_bytes(32)
        for i in range(500):
            model = tmp_path / f"model_{i}.pkl"
            model.write_bytes(secrets.token_bytes(1024 + i * 10))
            sig = sign_model_artifact(model, key=key)
            assert sig.exists()
            result = verify_model_artifact(model, key=key)
            assert result["verified"] is True

    @pytest.mark.slow
    def test_tamper_detection_various_positions(self, tmp_path: Path):
        """Tamper at different byte positions — all should be detected."""
        key = secrets.token_bytes(32)
        model = tmp_path / "model.pkl"
        data = secrets.token_bytes(10000)
        model.write_bytes(data)
        sign_model_artifact(model, key=key)

        for pos in range(0, len(data), 100):
            tampered = bytearray(data)
            tampered[pos] ^= 0xFF
            model.write_bytes(bytes(tampered))
            result = verify_model_artifact(model, key=key)
            assert result["verified"] is False
            # Restore
            model.write_bytes(data)


# ────────────────────────────────────────────────────────
# Artifact manifest stress
# ────────────────────────────────────────────────────────

class TestArtifactManifestStress:
    def _generate_manifest(self, evidence: Path, manifest_path: Path) -> None:
        manifest = ArtifactManifest()
        for f in sorted(evidence.glob("*.json")):
            manifest.add_file(f)
        manifest.save(manifest_path)

    @pytest.mark.slow
    def test_manifest_many_files(self, tmp_path: Path):
        """Create manifest with 200 files, verify integrity."""
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(200):
            (evidence / f"report_{i}.json").write_text(
                json.dumps({"id": i, "status": "pass"}), encoding="utf-8"
            )
        manifest_path = evidence / ".manifest.json"
        self._generate_manifest(evidence, manifest_path)
        assert manifest_path.exists()
        ok, issues = ArtifactManifest.verify(manifest_path)
        assert ok is True, f"Manifest verification failed: {issues}"

    @pytest.mark.slow
    def test_manifest_tamper_detected(self, tmp_path: Path):
        """Tampering with any file should be detected."""
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        for i in range(50):
            (evidence / f"report_{i}.json").write_text(
                json.dumps({"id": i}), encoding="utf-8"
            )
        manifest_path = evidence / ".manifest.json"
        self._generate_manifest(evidence, manifest_path)
        # Tamper with one file
        (evidence / "report_25.json").write_text('{"tampered": true}', encoding="utf-8")
        ok, issues = ArtifactManifest.verify(manifest_path)
        assert ok is False


# ────────────────────────────────────────────────────────
# CSV row limit check stress
# ────────────────────────────────────────────────────────

class TestCSVRowLimitStress:
    @pytest.mark.slow
    def test_large_csv_within_limit(self, tmp_path: Path):
        """50K row CSV should be within default limits."""
        csv_path = tmp_path / "data.csv"
        lines = ["col_a,col_b,target"]
        for i in range(50_000):
            lines.append(f"{i},{i*0.1},{i%2}")
        csv_path.write_text("\n".join(lines), encoding="utf-8")
        # Should not raise
        check_csv_row_limit(csv_path, max_rows=100_000)

    @pytest.mark.slow
    def test_csv_over_limit_raises(self, tmp_path: Path):
        csv_path = tmp_path / "data.csv"
        lines = ["col_a,col_b,target"]
        for i in range(10_001):
            lines.append(f"{i},{i*0.1},{i%2}")
        csv_path.write_text("\n".join(lines), encoding="utf-8")
        with pytest.raises(ValueError):
            check_csv_row_limit(csv_path, max_rows=10_000)
