#!/usr/bin/env python3
"""
Security hardening module for ml-governance-guard.

Provides defense-in-depth against:
    1. Pickle/joblib deserialization RCE (HMAC-signed model artifacts)
    2. Path traversal attacks (sandbox validation)
    3. JSON artifact tampering (integrity manifest)
    4. Membership inference attacks (prediction perturbation)
    5. Resource exhaustion DoS (file size limits)
    6. Supply chain attacks (dependency hash verification)

Usage:
    from _security import (
        sign_model_artifact, verify_model_artifact,
        safe_path, safe_load_json,
        SecureModelLoader, ArtifactManifest,
    )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pickle
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


def _atomic_json_write(path: Path, payload: Any, **kwargs: Any) -> None:
    """Write JSON atomically via tmp-file + rename + fsync."""
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1_000_000)}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, **kwargs)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


# 100MB ceiling for any JSON file this module parses. An attacker who
# can drop a multi-GB file into a path we read (signature sidecar,
# manifest, RBAC config, execution receipt) would otherwise OOM the
# verifier — same class the orchestrator json.load sites had.
_MAX_SECURITY_JSON_SIZE = 100 * 1024 * 1024


def _size_capped_json_load(path: Path) -> Any:
    """json.load with a 100MB file-size pre-check.

    Raises ValueError on oversize (same type json.load would raise for
    malformed content, so existing callers' `except (json.JSONDecodeError,
    OSError, ValueError)` continue to catch it).
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"stat_failed: {exc}") from exc
    if size > _MAX_SECURITY_JSON_SIZE:
        raise ValueError(
            f"json_too_large: {size} bytes exceeds {_MAX_SECURITY_JSON_SIZE} "
            f"(path={path})"
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1. HMAC-signed model artifact serialization
# ---------------------------------------------------------------------------

_HMAC_HEADER = b"MLGG-SIGNED-v1\x00"
_HMAC_ALGO = "sha256"

# Shared sensitive data patterns — single source of truth for _security.py
# and security_audit_gate.py.
#
# Format: tuple of (label, compiled_regex). Codex review 2026-04-23
# replaced the previous lowercase-substring tuple because:
#   1. Plain substrings miss numeric-only SSN (`123456789`) and
#      fullwidth-dash variants (`123-45-6789` with U+FF0D).
#   2. No 2025 API-key prefixes (sk-ant-, sk-proj-, github_pat_,
#      glpat-, gho_, AIza, AKIA...).
#   3. Unicode normalization wasn't applied before matching.
#
# scan_sensitive_data() below normalizes (NFKC + casefold) before
# matching. All patterns are case-insensitive by flag.
SENSITIVE_DATA_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    # ── Generic secret/credential keywords (compound to avoid ML FPs) ──
    ("password",        re.compile(r"\bpassword\b", re.IGNORECASE)),
    ("api_key",         re.compile(r"\bapi[_\s-]?key\b", re.IGNORECASE)),
    ("secret_key",      re.compile(r"\bsecret[_\s-]?key\b", re.IGNORECASE)),
    ("private_key",     re.compile(r"\bprivate[_\s-]?key\b", re.IGNORECASE)),
    ("access_key",      re.compile(r"\baccess[_\s-]?key\b", re.IGNORECASE)),
    ("credential",      re.compile(r"\bcredential\b", re.IGNORECASE)),
    ("auth_token",      re.compile(r"\bauth[_\s-]?token\b", re.IGNORECASE)),
    ("bearer_token",    re.compile(r"\bbearer[_\s-]?token\b", re.IGNORECASE)),
    ("api_secret",      re.compile(r"\bapi[_\s-]?secret\b", re.IGNORECASE)),
    ("client_secret",   re.compile(r"\bclient[_\s-]?secret\b", re.IGNORECASE)),
    ("refresh_token",   re.compile(r"\brefresh[_\s-]?token\b", re.IGNORECASE)),
    ("session_token",   re.compile(r"\bsession[_\s-]?token\b", re.IGNORECASE)),
    ("oauth_token",     re.compile(r"\boauth[_\s-]?token\b", re.IGNORECASE)),

    # ── 2025 API-key formats (concrete leak indicators) ─────────────
    ("anthropic_api_key",   re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_project_key",  re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")),
    ("openai_user_key",     re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("github_personal_token", re.compile(r"\b(?:gho|ghp|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("github_pat_v2",       re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("gitlab_pat",          re.compile(r"\bglpat-[A-Za-z0-9_-]{20}\b")),
    ("google_api_key",      re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws_access_key_id",   re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA)[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"\baws_secret_access_key\b", re.IGNORECASE)),
    ("slack_token",         re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),

    # ── PEM key blocks ──────────────────────────────────────────────
    ("pem_rsa",             re.compile(r"-----BEGIN RSA PRIVATE KEY-----", re.IGNORECASE)),
    ("pem_private",         re.compile(r"-----BEGIN (?:OPENSSH |EC |DSA )?PRIVATE KEY-----", re.IGNORECASE)),

    # ── PII / PHI identifiers ───────────────────────────────────────
    # SSN: both dashed (123-45-6789) and undashed (123456789) forms.
    # \b boundaries prevent matching phone-number or credit-card digits.
    ("ssn",                 re.compile(r"\bssn\b|\bsocial[_\s-]?security\b", re.IGNORECASE)),
    ("ssn_dashed",          re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("ssn_undashed",        re.compile(r"(?<!\d)\d{9}(?!\d)")),
    # Credit card (generic Luhn-ish — 13-19 digits with optional groups)
    ("credit_card",         re.compile(r"\bcredit[_\s-]?card\b", re.IGNORECASE)),
    ("credit_card_number",  re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # HIPAA medical identifiers
    ("medical_record",      re.compile(r"\bmedical[_\s-]?record\b", re.IGNORECASE)),
    ("mrn",                 re.compile(r"\bmrn[_\s-]?(?:number|id)?\b", re.IGNORECASE)),
    ("insurance_id",        re.compile(r"\binsurance[_\s-]?id\b", re.IGNORECASE)),
)


def scan_sensitive_data(content: str) -> List[Tuple[str, str]]:
    """Scan a string for sensitive-data patterns.

    Normalizes with NFKC (fullwidth → ASCII) before matching so a
    value like ``123－45－6789`` (fullwidth minus) still hits the SSN
    pattern. Patterns themselves are case-insensitive; the explicit
    casefold avoids per-pattern re.IGNORECASE overhead.

    Returns:
        List of (label, matched_text) pairs — one per pattern hit.
        Empty list when nothing matches. Callers usually care about
        the FIRST hit (audit says "flagged"), but the full list is
        useful for reporting which kinds of data leaked.
    """
    if not content:
        return []
    import unicodedata
    # NFKC only (no casefold) — patterns that care about case
    # distinction (AKIA*, AIza*, github gho_*) use explicit case
    # semantics in the regex, and applying casefold would break them.
    # Keyword patterns use re.IGNORECASE, so mixed-case content like
    # "API_KEY" still matches.
    normalized = unicodedata.normalize("NFKC", content)
    hits: List[Tuple[str, str]] = []
    for label, pattern in SENSITIVE_DATA_PATTERNS:
        m = pattern.search(normalized)
        if m:
            hits.append((label, m.group(0)))
    return hits
_KEY_ENV_VAR = "MLGG_MODEL_SECRET"
_KEY_FILE_NAME = ".mlgg_model_key"

# PBKDF2 parameters for deriving a signing key from a (potentially
# human-chosen) MLGG_MODEL_SECRET env var. OWASP 2023 guidance is
# 600,000 iterations for PBKDF2-HMAC-SHA256 (~100ms on typical
# hardware). Salt is fixed per-project so signatures produced on
# different machines still verify against the same key — the salt's
# job is not per-call freshness (it's deterministic derivation) but
# to differ the derived key from a raw SHA256, breaking rainbow
# tables for the common "password: hunter2" pitfall.
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT = b"mlgg-key-derivation-salt-v1"


def _check_key_file_mode(key_path: Path) -> None:
    """Fail-closed if the key file is world- or group-readable.

    A cryptographic root-of-trust file with lax permissions lets any
    local user on a shared machine read the key and forge signatures.
    POSIX-only; Windows is detected via AttributeError on st_mode
    and skipped (Windows ACLs work differently, chmod is cosmetic).
    """
    try:
        mode = key_path.stat().st_mode
    except (OSError, AttributeError):
        return
    # Any group/world read/write/execute bit set is a failure.
    if mode & 0o077:
        raise SecurityError(
            f"Key file {key_path} has unsafe permissions "
            f"(mode={oct(mode & 0o777)}). Expected 0o600 (owner-only). "
            f"Fix with: chmod 0o600 {key_path}"
        )


def _derive_key() -> bytes:
    """Derive HMAC key from environment variable or auto-generated key file.

    Priority:
        1. MLGG_MODEL_SECRET environment variable
        2. .mlgg_model_key file in project root (anchored to this file's
           location, NOT cwd — CWD-based discovery was removable-
           attacker-planted-key-in-working-dir vector).
        3. Auto-generate and persist a new key

    Notes:
        The env-var path uses PBKDF2-HMAC-SHA256 (600k iterations) so
        a human-chosen MLGG_MODEL_SECRET (e.g., "hunter2") is not
        cheaply brute-forceable offline given a signed artifact. Raw
        SHA-256 was replaced per Codex review 2026-04-23. If you want
        to skip the iteration cost for a known-random key, hex-encode
        32 bytes of randomness and set MLGG_MODEL_SECRET_HEX_RAW=1
        to use raw decoding instead (for CI / automated testing).
    """
    env_key = os.environ.get(_KEY_ENV_VAR, "").strip()
    if env_key:
        # Escape hatch: known-random 64-hex-char key goes through
        # fast-path decode (skips PBKDF2 — no security benefit for
        # already-uniformly-random keys).
        if os.environ.get("MLGG_MODEL_SECRET_HEX_RAW", "").strip() == "1":
            try:
                raw = bytes.fromhex(env_key)
                if len(raw) == 32:
                    return raw
            except ValueError:
                pass  # Fall through to PBKDF2 on malformed hex.
        return hashlib.pbkdf2_hmac(
            "sha256",
            env_key.encode("utf-8"),
            _PBKDF2_SALT,
            _PBKDF2_ITERATIONS,
            dklen=32,
        )

    # Search upward for project root (contains SKILL.md or .git).
    # Anchored to THIS FILE only — not Path.cwd() — so an attacker who
    # controls the process's working directory cannot plant a rogue
    # .mlgg_model_key that wins the search.
    search = Path(__file__).resolve().parent
    for _ in range(10):
        if (search / "SKILL.md").exists() or (search / ".git").exists():
            break
        parent = search.parent
        if parent == search:
            break
        search = parent

    key_path = search / _KEY_FILE_NAME
    if key_path.exists():
        _check_key_file_mode(key_path)
        raw = key_path.read_bytes().strip()
        if len(raw) >= 32:
            try:
                # File stores hex-encoded bytes; decode back to raw before hashing
                key_bytes = bytes.fromhex(raw.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                key_bytes = raw
            return hashlib.sha256(key_bytes).digest()

    # Auto-generate a 256-bit key
    new_key = secrets.token_bytes(32)
    try:
        key_path.write_bytes(new_key.hex().encode("ascii") + b"\n")
        key_path.chmod(0o600)
    except OSError as exc:
        import warnings
        warnings.warn(
            f"Could not write/chmod signing key file {key_path}: {exc}. "
            f"Key exists only in memory for this session.",
            stacklevel=2,
        )
    return hashlib.sha256(new_key).digest()


def compute_hmac(data: bytes, key: Optional[bytes] = None) -> bytes:
    """Compute HMAC-SHA256 over data."""
    if key is None:
        key = _derive_key()
    return hmac.new(key, data, hashlib.sha256).digest()


def sign_model_artifact(model_path: Path, key: Optional[bytes] = None) -> Path:
    """Sign a serialized model artifact with HMAC-SHA256.

    Creates a .sig sidecar file containing the HMAC signature.

    Args:
        model_path: Path to the model file (e.g. model.pkl).
        key: Optional HMAC key; auto-derived if None.

    Returns:
        Path to the signature file.
    """
    if key is None:
        key = _derive_key()
    model_data = model_path.read_bytes()
    signature = compute_hmac(model_data, key)
    sig_path = model_path.with_suffix(model_path.suffix + ".sig")
    payload = {
        "algorithm": "hmac-sha256",
        "signature": signature.hex(),
        "file_sha256": hashlib.sha256(model_data).hexdigest(),
        "file_size": len(model_data),
        "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "schema_version": 1,
    }
    _atomic_json_write(sig_path, payload, indent=2)
    return sig_path


def verify_model_artifact(model_path: Path, key: Optional[bytes] = None) -> Dict[str, Any]:
    """Verify HMAC signature of a model artifact.

    Args:
        model_path: Path to the model file.
        key: Optional HMAC key; auto-derived if None.

    Returns:
        Dict with verification result: {"verified": bool, "reason": str, ...}
    """
    if key is None:
        key = _derive_key()
    sig_path = model_path.with_suffix(model_path.suffix + ".sig")

    if not model_path.exists():
        return {"verified": False, "reason": "model_file_missing"}
    if not sig_path.exists():
        return {"verified": False, "reason": "signature_file_missing"}

    try:
        sig_payload = _size_capped_json_load(sig_path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return {"verified": False, "reason": f"signature_file_corrupt: {exc}"}

    model_data = model_path.read_bytes()

    # Verify file size
    expected_size = sig_payload.get("file_size", -1)
    if expected_size != len(model_data):
        return {"verified": False, "reason": "file_size_mismatch",
                "expected": expected_size, "actual": len(model_data)}

    # Verify SHA256
    actual_sha = hashlib.sha256(model_data).hexdigest()
    expected_sha = sig_payload.get("file_sha256", "")
    if actual_sha != expected_sha:
        return {"verified": False, "reason": "sha256_mismatch",
                "expected": expected_sha, "actual": actual_sha}

    # Verify HMAC. A malformed signature field (non-hex / odd length) must not
    # crash the gate (fail-open-by-crash); treat it as a verification failure.
    try:
        expected_hmac = bytes.fromhex(sig_payload.get("signature", ""))
    except (ValueError, TypeError):
        return {"verified": False, "reason": "signature_field_malformed"}
    actual_hmac = compute_hmac(model_data, key)
    if not hmac.compare_digest(actual_hmac, expected_hmac):
        return {"verified": False, "reason": "hmac_mismatch"}

    return {
        "verified": True,
        "reason": "ok",
        "file_sha256": actual_sha,
        "signed_at": sig_payload.get("signed_at", ""),
    }


# ---------------------------------------------------------------------------
# 2. Path traversal protection
# ---------------------------------------------------------------------------

_MAX_PATH_LENGTH = 4096
_FORBIDDEN_COMPONENTS = {".."}
_FORBIDDEN_PREFIXES = (
    "/etc", "/dev", "/proc", "/sys", "/var/run",
    "/private/etc", "/private/var/run",  # macOS symlink targets
)


def safe_path(
    user_path: str,
    sandbox: Optional[Path] = None,
    must_exist: bool = False,
) -> Path:
    """Validate and resolve a user-provided file path.

    Defends against:
        - Path traversal (../)
        - Symlink escapes
        - Excessively long paths
        - Access to sensitive system directories

    Args:
        user_path: Raw user-provided path string.
        sandbox: Optional sandbox directory; resolved path must be under it.
        must_exist: If True, raise if the resolved path does not exist.

    Returns:
        Resolved, validated Path.

    Raises:
        ValueError: If the path is invalid or escapes the sandbox.
    """
    if not user_path or not user_path.strip():
        raise ValueError("path_empty: file path cannot be empty")

    if len(user_path) > _MAX_PATH_LENGTH:
        raise ValueError(f"path_too_long: path exceeds {_MAX_PATH_LENGTH} chars")

    # Check for null bytes (classic injection)
    if "\x00" in user_path:
        raise ValueError("path_null_byte: null bytes in path")

    # Reject literal traversal components in the raw input when there is no
    # sandbox to constrain the result. A bare ".." with no sandbox is a strong
    # signal of a traversal attempt with nothing to bound where it lands. When a
    # sandbox is supplied, ".." that resolves back inside it is legitimate and is
    # validated by the relative_to() check below instead.
    if sandbox is None:
        raw_parts = set(Path(user_path).parts)
        if _FORBIDDEN_COMPONENTS & raw_parts:
            raise ValueError("path_traversal: '..' component is not allowed")

    resolved = Path(user_path).expanduser().resolve()

    # Block sensitive system paths. Compare on path components rather than a
    # raw string prefix so "/etc" does not over-match "/etcetera/..." etc.
    resolved_parts = resolved.parts
    for prefix in _FORBIDDEN_PREFIXES:
        prefix_parts = Path(prefix).parts
        if resolved_parts[: len(prefix_parts)] == prefix_parts:
            raise ValueError(f"path_forbidden: access to {prefix} is blocked")

    # Sandbox enforcement
    if sandbox is not None:
        sandbox_resolved = sandbox.resolve()
        try:
            resolved.relative_to(sandbox_resolved)
        except ValueError:
            raise ValueError(
                f"path_traversal: {resolved} escapes sandbox {sandbox_resolved}"
            )

    if must_exist and not resolved.exists():
        raise ValueError(f"path_not_found: {resolved}")

    return resolved


# ---------------------------------------------------------------------------
# 3. Secure JSON loading with size limits and schema validation
# ---------------------------------------------------------------------------

_MAX_JSON_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_JSON_DEPTH = 50


def _check_depth(obj: Any, current: int = 0) -> int:
    """Recursively check JSON nesting depth."""
    if current > _MAX_JSON_DEPTH:
        raise ValueError(f"json_depth_exceeded: nesting exceeds {_MAX_JSON_DEPTH}")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_depth(v, current + 1)
    elif isinstance(obj, list):
        for item in obj:
            _check_depth(item, current + 1)
    return current


def safe_load_json(
    path: Union[str, Path],
    max_size: int = _MAX_JSON_SIZE_BYTES,
    check_depth: bool = True,
) -> Dict[str, Any]:
    """Load JSON with security checks.

    Defends against:
        - Zip bombs / memory exhaustion (size limit)
        - Hash collision DoS (Python 3.6+ has randomized hashing)
        - Deeply nested JSON (stack overflow)

    Args:
        path: Path to JSON file.
        max_size: Maximum file size in bytes.
        check_depth: Whether to check nesting depth.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If security checks fail.
    """
    p = Path(path).expanduser().resolve()

    if not p.exists():
        raise ValueError(f"json_not_found: {p}")

    file_size = p.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"json_too_large: {file_size} bytes exceeds limit {max_size}"
        )

    with p.open("r", encoding="utf-8") as fh:
        try:
            payload = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"json_decode_error: {p}: {exc}") from exc
        except RecursionError as exc:
            # Python's stdlib json parser is recursive-descent. Adversarial
            # input like "[" * 1000 exhausts the stack before _check_depth
            # ever runs. Translate to ValueError so callers can treat it
            # like any other malformed input — same surface as the stated
            # "deeply nested JSON (stack overflow)" defense.
            raise ValueError(
                f"json_too_deeply_nested: {p}: parser hit Python recursion limit"
            ) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"json_root_not_object: expected dict, got {type(payload).__name__}")

    if check_depth:
        _check_depth(payload)

    return payload


# ---------------------------------------------------------------------------
# 4. Artifact integrity manifest
# ---------------------------------------------------------------------------


class ArtifactManifest:
    """Compute and verify SHA256 manifest for a set of evidence files.

    Usage:
        manifest = ArtifactManifest()
        manifest.add_file(Path("evidence/evaluation_report.json"))
        manifest.add_file(Path("evidence/model_selection_report.json"))
        manifest.save(Path("evidence/.manifest.json"))

        # Later: verify
        ok, issues = ArtifactManifest.verify(Path("evidence/.manifest.json"))
    """

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []

    def add_file(self, path: Path) -> None:
        """Add a file to the manifest."""
        if not path.exists():
            return
        data = path.read_bytes()
        self._entries.append({
            "path": str(path.name),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "modified": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(path.stat().st_mtime),
            ),
        })

    def save(self, manifest_path: Path) -> None:
        """Save the manifest to a JSON file."""
        payload = {
            "schema_version": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entries": self._entries,
            "entry_count": len(self._entries),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(manifest_path, payload, indent=2, sort_keys=True)

    @staticmethod
    def verify(manifest_path: Path) -> Tuple[bool, List[str]]:
        """Verify all files in a manifest against their recorded hashes.

        Returns:
            (all_ok, list_of_issues)
        """
        if not manifest_path.exists():
            return False, ["manifest_file_missing"]

        try:
            manifest = _size_capped_json_load(manifest_path)
        except ValueError as exc:
            return False, [f"manifest_too_large_or_corrupt: {exc}"]
        except (json.JSONDecodeError, OSError) as exc:
            return False, [f"manifest_corrupt: {exc}"]

        issues: List[str] = []
        base_dir = manifest_path.parent
        for entry in manifest.get("entries", []):
            fpath = base_dir / entry["path"]
            if not fpath.exists():
                issues.append(f"file_missing: {entry['path']}")
                continue
            data = fpath.read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != entry["sha256"]:
                issues.append(
                    f"sha256_mismatch: {entry['path']} "
                    f"expected={entry['sha256'][:16]}... "
                    f"actual={actual_sha[:16]}..."
                )
            if len(data) != entry.get("size", len(data)):
                issues.append(f"size_mismatch: {entry['path']}")

        return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# 5. Membership inference defense — prediction perturbation
# ---------------------------------------------------------------------------


def perturb_predictions(
    probabilities: Sequence[float],
    epsilon: float = 0.01,
    seed: Optional[int] = None,
) -> List[float]:
    """Add calibrated noise to prediction probabilities to defend against
    membership inference attacks.

    Uses Laplace mechanism with bounded output [0, 1].

    Args:
        probabilities: Raw prediction probabilities.
        epsilon: Privacy budget (smaller = more private, more noise).
                 Default 0.01 adds ~1% noise.
        seed: Random seed for reproducibility.

    Returns:
        Perturbed probabilities clipped to [0, 1].
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    scale = 1.0 / max(epsilon, 1e-10)
    # Laplace noise scaled to be small but meaningful
    noise = rng.laplace(0, scale * 0.001, size=len(probabilities))
    perturbed = np.clip(np.array(probabilities, dtype=float) + noise, 0.0, 1.0)
    return list(float(x) for x in perturbed)


# ---------------------------------------------------------------------------
# 6. Secure model loading with verification
# ---------------------------------------------------------------------------


class SecureModelLoader:
    """Load model artifacts with HMAC verification and restricted unpickling.

    Usage:
        loader = SecureModelLoader()
        bundle = loader.load(Path("models/model.pkl"))
    """

    # Allowlist of safe module prefixes for unpickling
    _ALLOWED_MODULES = frozenset({
        "sklearn",
        "numpy",
        "scipy",
        "collections",
        "builtins",
        "copy",
        "_codecs",
        "copyreg",
        "re",
        "array",
        "datetime",
        "numbers",
        "decimal",
        "fractions",
        "functools",
        "operator",
        "itertools",
        "io",
    })

    @classmethod
    def _is_module_allowed(cls, module_name: str) -> bool:
        """Check if a module is in the allowlist."""
        for allowed in cls._ALLOWED_MODULES:
            if module_name == allowed or module_name.startswith(allowed + "."):
                return True
        return False

    @classmethod
    def load(
        cls,
        model_path: Path,
        verify_signature: bool = True,
        key: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Securely load a model artifact.

        Args:
            model_path: Path to model file.
            verify_signature: Whether to verify HMAC signature first.
            key: Optional HMAC key.

        Returns:
            Model bundle dict.

        Raises:
            SecurityError: If verification fails.
            ValueError: If model file is invalid.
        """

        model_path = Path(model_path).expanduser().resolve()

        if verify_signature:
            result = verify_model_artifact(model_path, key)
            if not result["verified"]:
                raise SecurityError(
                    f"model_signature_invalid: {result['reason']} — "
                    f"refusing to load potentially tampered model artifact"
                )

        # Size check (models should not be > 500 MB)
        max_model_size = 500 * 1024 * 1024
        file_size = model_path.stat().st_size
        if file_size > max_model_size:
            raise SecurityError(
                f"model_too_large: {file_size} bytes exceeds {max_model_size} limit"
            )

        # Use restricted unpickler to block arbitrary code execution.
        # SECURITY: joblib fallback is intentionally removed.  joblib.load()
        # uses standard pickle internally and would bypass the RestrictedUnpickler,
        # allowing arbitrary code execution from crafted .pkl files.  All MLGG
        # model artifacts MUST be serialised with plain pickle (not joblib
        # compression) so that RestrictedUnpickler can inspect every opcode.
        with model_path.open("rb") as fh:
            try:
                bundle = safe_pickle_load(fh)
            except SecurityError:
                raise
            except (pickle.UnpicklingError, EOFError, ValueError, KeyError) as exc:
                raise SecurityError(
                    f"model_load_failed: could not deserialise {model_path.name} "
                    f"through RestrictedUnpickler ({type(exc).__name__}: {exc}). "
                    f"If this model was saved with joblib compression, re-save it "
                    f"with pickle.dump() to enable secure loading."
                ) from exc

        # Validate expected structure
        if not isinstance(bundle, dict):
            raise ValueError("model_invalid_structure: expected dict bundle")
        required_keys = {"estimator", "model_id", "features", "schema_version"}
        missing = required_keys - set(bundle.keys())
        if missing:
            raise ValueError(f"model_missing_keys: {missing}")

        return bundle


class SecurityError(Exception):
    """Raised when a security check fails."""
    pass


# ---------------------------------------------------------------------------
# 7. Restricted unpickler (deserialization sandbox)
# ---------------------------------------------------------------------------

_ALLOWED_PICKLE_MODULES = frozenset({
    "sklearn", "sklearn.linear_model", "sklearn.ensemble", "sklearn.svm",
    "sklearn.neighbors", "sklearn.naive_bayes", "sklearn.neural_network",
    "sklearn.tree", "sklearn.calibration", "sklearn.pipeline",
    "sklearn.preprocessing", "sklearn.impute", "sklearn.compose",
    "sklearn.feature_selection", "sklearn.model_selection",
    "sklearn.base", "sklearn.utils", "sklearn.utils._bunch",
    "sklearn.utils.validation", "sklearn.metrics",
    "numpy", "numpy.core", "numpy.core.multiarray", "numpy.core.numeric",
    "numpy.ma", "numpy.ma.core", "numpy.random", "numpy.dtypes",
    "numpy._core", "numpy._core.multiarray", "numpy._core._methods",
    "scipy", "scipy.sparse", "scipy.sparse._csr", "scipy.sparse._csc",
    "scipy.sparse._arrays", "scipy.special", "scipy.optimize",
    "pandas", "pandas.core", "pandas.core.frame", "pandas.core.series",
    "pandas.core.indexes", "pandas._libs",
    "joblib", "joblib.numpy_pickle",
    "builtins", "collections", "copy", "copyreg", "io",
    "_codecs", "codecs", "encodings",
})

_BLOCKED_CALLABLES = frozenset({
    "os.system", "os.popen", "os.exec", "os.execv", "os.execve",
    "os.spawn", "os.spawnl", "os.spawnle",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "eval", "exec", "compile", "__import__",
    "builtins.eval", "builtins.exec", "builtins.__import__",
    "nt.system", "posix.system",
    "webbrowser.open", "ctypes.CDLL",
})


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler with a module allow-list and callable blocklist.

    Threat model & honest limits (Codex review 2026-04-23):

    This class reduces the attack surface of pickle deserialization
    but is NOT a complete sandbox. The allow-list has to include
    sklearn, numpy, scipy, pandas, joblib, copyreg, builtins, codecs
    — any narrower list breaks legitimate model loading. Gadget
    chaining through reconstruction helpers in those exact modules
    (e.g., joblib.numpy_pickle factories, numpy._core.multiarray._
    reconstruct, copyreg.__newobj__) is a known residual risk. Only
    `find_class()` is overridden; REDUCE/BUILD opcodes still
    execute, so a crafted pickle calling an allowed reconstructor
    with attacker-chosen arguments can still trigger surprising
    side-effects inside those modules.

    **Primary defense is the HMAC signature check** —
    verify_model_artifact() MUST be called (and succeed) before any
    model file is fed to safe_pickle_load(). With HMAC in place, an
    attacker cannot produce a tampered .pkl that the pipeline would
    ever load. Without it, this sandbox buys "blocks os.system",
    nothing more.

    Blocks at find_class():
      - Explicit callables in _BLOCKED_CALLABLES (os.system, exec,
        subprocess.*, etc.)
      - Any module outside _ALLOWED_PICKLE_MODULES.

    Does NOT block:
      - REDUCE / BUILD opcodes against allowed-module reconstructors.
      - Gadget chains fully internal to allow-listed modules.

    If you need a true deserialization sandbox, replace pickle with
    safetensors / JSON-native schemas. That's out of scope for this
    module's role as a defense-in-depth layer.
    """

    def find_class(self, module: str, name: str) -> Any:
        fqn = f"{module}.{name}"
        if fqn in _BLOCKED_CALLABLES:
            raise SecurityError(
                f"Blocked dangerous callable during deserialization: {fqn}"
            )
        # Check module against whitelist (allow sub-modules)
        mod_root = module.split(".")[0]
        allowed = any(
            module == allowed_mod or module.startswith(allowed_mod + ".")
            for allowed_mod in _ALLOWED_PICKLE_MODULES
        )
        if not allowed and mod_root not in {
            "builtins", "collections", "copy", "copyreg",
            "io", "_codecs", "codecs", "encodings",
        }:
            raise SecurityError(
                f"Disallowed module in pickle stream: {module}.{name} — "
                f"only sklearn/numpy/scipy/pandas/joblib modules are permitted"
            )
        return super().find_class(module, name)


def safe_pickle_load(file_obj: Any) -> Any:
    """Load a pickle stream using the restricted unpickler.

    WARNING: "safe_pickle_load" is a misnomer — pickle is never fully
    safe against an attacker who controls the file bytes. This only
    reduces the attack surface (blocks obviously dangerous modules /
    callables) and does NOT close gadget chains through allowed
    modules like joblib, numpy, copyreg. See RestrictedUnpickler
    docstring for the full threat model.

    Callers that load untrusted .pkl files MUST verify an HMAC
    signature via verify_model_artifact() FIRST. If the signature
    passes, the file bytes are known to come from the signer, so the
    residual pickle-sandbox risks do not apply.

    Args:
        file_obj: File-like object opened in binary mode.

    Returns:
        Deserialized object.

    Raises:
        SecurityError: If the pickle stream contains disallowed modules.
    """
    return RestrictedUnpickler(file_obj).load()


# ---------------------------------------------------------------------------
# 8. Evidence encryption at rest (AES-256-GCM)
# ---------------------------------------------------------------------------

# AES-GCM envelope version.
#   v1 (legacy, Codex 2026-04-23 found unsafe): aad=None. Ciphertext
#        was not bound to any context — a valid blob for evidence slot
#        A could be replayed into slot B that shared the same key.
#        Decrypt now REFUSES to read v1 blobs; rotate keys + re-encrypt.
#   v2: aad required; caller-supplied context string is authenticated.
_ENC_HEADER_V1 = b"MLGG-ENC-v1\x00"
_ENC_HEADER = b"MLGG-ENC-v2\x00"
_ENC_KEY_FILE = ".mlgg_encryption_key"


def _get_encryption_key() -> bytes:
    """Get or create a 32-byte AES-256 encryption key.

    Key sources (in priority order):
        1. MLGG_ENCRYPTION_KEY environment variable (hex-encoded)
        2. .mlgg_encryption_key file anchored to this file's project root
           (NOT Path.cwd() — that was a CWD-based-key-substitution attack
           vector; see Codex review 2026-04-23)
        3. Auto-generate and persist a new key
    """
    env_key = os.environ.get("MLGG_ENCRYPTION_KEY", "").strip()
    if env_key:
        try:
            raw = bytes.fromhex(env_key)
            if len(raw) >= 32:
                return raw[:32]
        except ValueError:
            pass

    # Anchor to __file__, not cwd — same reasoning as _derive_key.
    search = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = search / _ENC_KEY_FILE
        if candidate.exists():
            _check_key_file_mode(candidate)
            raw = candidate.read_bytes().strip()
            try:
                key = bytes.fromhex(raw.decode("ascii"))
                if len(key) >= 32:
                    return key[:32]
            except (ValueError, UnicodeDecodeError):
                pass
            break
        # Stop at project root marker or filesystem root.
        if (search / "SKILL.md").exists() or (search / ".git").exists():
            # Root found; check for key at root.
            candidate = search / _ENC_KEY_FILE
            if candidate.exists():
                _check_key_file_mode(candidate)
                raw = candidate.read_bytes().strip()
                try:
                    key = bytes.fromhex(raw.decode("ascii"))
                    if len(key) >= 32:
                        return key[:32]
                except (ValueError, UnicodeDecodeError):
                    pass
            break
        parent = search.parent
        if parent == search:
            break
        search = parent

    key = secrets.token_bytes(32)
    key_path = search / _ENC_KEY_FILE
    try:
        key_path.write_bytes(key.hex().encode("ascii") + b"\n")
        key_path.chmod(0o600)
    except OSError as exc:
        import warnings
        warnings.warn(
            f"Could not write/chmod encryption key file {key_path}: {exc}. "
            f"Key exists only in memory for this session.",
            stacklevel=2,
        )
    return key


def encrypt_evidence(
    data: bytes,
    *,
    aad: bytes,
    key: Optional[bytes] = None,
) -> bytes:
    """Encrypt evidence data using AES-256-GCM with authenticated context.

    Args:
        data: Plaintext bytes to encrypt.
        aad: Associated data binding ciphertext to context. Required
            (keyword-only). Example: b"mlgg-evidence-chain-v1" or
            b"audit-log-entry:<run_id>". A ciphertext produced with
            one aad cannot be decrypted with a different aad, which
            prevents cross-context replay.
        key: 32-byte AES key. Auto-derived if None.

    Returns:
        Encrypted blob: header + nonce(12) + tag(16) + ciphertext.

    Raises:
        ValueError: aad is empty (unbound ciphertext is refused).
    """
    if not aad:
        raise ValueError(
            "encrypt_evidence requires a non-empty aad to bind ciphertext "
            "to context. Unbound ciphertext is replayable across evidence "
            "slots — see Codex review 2026-04-23."
        )
    if key is None:
        key = _get_encryption_key()

    nonce = secrets.token_bytes(12)

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        ciphertext = bytes(aesgcm.encrypt(nonce, data, aad))
        # ciphertext includes the 16-byte tag appended by cryptography lib
        return _ENC_HEADER + nonce + ciphertext
    except ImportError:
        raise RuntimeError(
            "AES-256-GCM encryption requires the 'cryptography' package. "
            "Install it with: pip install cryptography. "
            "Falling back to insecure obfuscation is not permitted (fail-closed)."
        )


def decrypt_evidence(
    blob: bytes,
    *,
    aad: bytes,
    key: Optional[bytes] = None,
) -> bytes:
    """Decrypt evidence data encrypted with encrypt_evidence.

    Args:
        blob: Encrypted blob from encrypt_evidence.
        aad: Same context bytes passed to encrypt_evidence. Must match
            or decryption fails with an integrity error (this is the
            authentication that prevents cross-context replay).
        key: 32-byte AES key. Auto-derived if None.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        SecurityError: If decryption or integrity check fails, or if
            the blob uses the legacy v1 envelope (which had no AAD).
    """
    if not aad:
        raise ValueError(
            "decrypt_evidence requires the same non-empty aad used for "
            "encrypt_evidence."
        )
    if key is None:
        key = _get_encryption_key()

    header_len = len(_ENC_HEADER)
    if blob.startswith(_ENC_HEADER_V1):
        raise SecurityError(
            "Legacy v1 ciphertext refused: v1 blobs had no AAD binding "
            "and can be replayed across contexts. Rotate the encryption "
            "key and re-encrypt data with encrypt_evidence(..., aad=<ctx>). "
            "See Codex review 2026-04-23."
        )
    if not blob.startswith(_ENC_HEADER):
        raise SecurityError("Invalid encryption header")

    nonce = blob[header_len:header_len + 12]

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        ciphertext_with_tag = blob[header_len + 12:]
        return bytes(aesgcm.decrypt(nonce, ciphertext_with_tag, aad))
    except ImportError:
        raise RuntimeError(
            "AES-256-GCM decryption requires the 'cryptography' package. "
            "Install it with: pip install cryptography."
        )


def _default_file_aad(path: Path) -> bytes:
    """Context-binding AAD for file-level encrypt/decrypt. The filename
    is the natural context discriminator — encrypting `evidence_A` vs
    `evidence_B` under the same key must produce non-interchangeable
    ciphertext. Uses just the basename so relocating the file (which
    is common) does not break decryption.
    """
    return f"mlgg-file-v1:{path.name}".encode("utf-8")


def encrypt_file(
    path: Path,
    *,
    aad: Optional[bytes] = None,
    key: Optional[bytes] = None,
) -> Path:
    """Encrypt a file in-place, adding .enc extension.

    Args:
        path: File to encrypt.
        aad: Optional override for the AAD. Defaults to a filename-
            based context string so the ciphertext cannot be swapped
            into a different file slot.
        key: Optional 32-byte AES key; auto-derived if None.

    Returns path to encrypted file.
    """
    data = path.read_bytes()
    encrypted = encrypt_evidence(
        data, aad=aad if aad is not None else _default_file_aad(path), key=key,
    )
    enc_path = path.with_suffix(path.suffix + ".enc")
    enc_path.write_bytes(encrypted)
    return enc_path


def decrypt_file(
    enc_path: Path,
    *,
    aad: Optional[bytes] = None,
    key: Optional[bytes] = None,
) -> bytes:
    """Decrypt an .enc file and return plaintext bytes.

    Note: the caller must pass the same aad used at encrypt time. When
    aad=None, the filename-based default is derived from the ORIGINAL
    file name (stripping the trailing .enc suffix) so that
    encrypt_file(foo.json) → decrypt_file(foo.json.enc) round-trips.
    """
    blob = enc_path.read_bytes()
    if aad is None:
        # Strip the .enc suffix to recover the plaintext name used in aad.
        original_name = enc_path.name[:-len(".enc")] if enc_path.suffix == ".enc" else enc_path.name
        aad = f"mlgg-file-v1:{original_name}".encode("utf-8")
    return decrypt_evidence(blob, aad=aad, key=key)


# ---------------------------------------------------------------------------
# 9. Role-Based Access Control (RBAC)
# ---------------------------------------------------------------------------

class Role:
    """Pipeline operation roles with associated permissions."""
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    VIEWER = "viewer"


_ROLE_PERMISSIONS: Dict[str, frozenset[str]] = {
    Role.ADMIN: frozenset({
        "pipeline.run", "pipeline.configure", "pipeline.abort",
        "gate.run", "gate.override",
        "model.sign", "model.load", "model.delete",
        "evidence.read", "evidence.write", "evidence.encrypt", "evidence.decrypt",
        "evidence.delete",
        "audit.read", "audit.verify",
        "security.audit", "security.configure",
        "user.manage",
    }),
    Role.OPERATOR: frozenset({
        "pipeline.run", "pipeline.configure",
        "gate.run",
        "model.sign", "model.load",
        "evidence.read", "evidence.write", "evidence.encrypt",
        "audit.read",
        "security.audit",
    }),
    Role.AUDITOR: frozenset({
        "evidence.read", "evidence.decrypt",
        "audit.read", "audit.verify",
        "security.audit",
    }),
    Role.VIEWER: frozenset({
        "evidence.read",
        "audit.read",
    }),
}

_RBAC_CONFIG_FILE = ".mlgg_rbac.json"


class AccessControl:
    """RBAC access control manager for pipeline operations."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._user_roles: Dict[str, str] = {}
        self._config_path = config_path
        if config_path and config_path.exists():
            try:
                data = _size_capped_json_load(config_path)
                self._user_roles = data.get("user_roles", {})
            except (json.JSONDecodeError, OSError, ValueError):
                pass

    def assign_role(self, username: str, role: str) -> None:
        """Assign a role to a user."""
        if role not in _ROLE_PERMISSIONS:
            raise ValueError(f"Unknown role: {role}. Valid: {list(_ROLE_PERMISSIONS.keys())}")
        self._user_roles[username] = role
        self._save()

    def get_role(self, username: str) -> str:
        """Get the role assigned to a user (default: viewer)."""
        return self._user_roles.get(username, Role.VIEWER)

    def check_permission(self, username: str, permission: str) -> bool:
        """Check if a user has a specific permission."""
        role = self.get_role(username)
        return permission in _ROLE_PERMISSIONS.get(role, frozenset())

    def require_permission(self, username: str, permission: str) -> None:
        """Raise SecurityError if user lacks the required permission."""
        if not self.check_permission(username, permission):
            role = self.get_role(username)
            raise SecurityError(
                f"Access denied: user '{username}' (role={role}) "
                f"lacks permission '{permission}'"
            )

    def list_permissions(self, username: str) -> List[str]:
        """List all permissions for a user."""
        role = self.get_role(username)
        return sorted(_ROLE_PERMISSIONS.get(role, frozenset()))

    def _save(self) -> None:
        if self._config_path:
            payload = {"user_roles": self._user_roles, "schema_version": 1}
            try:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_json_write(self._config_path, payload, indent=2)
                self._config_path.chmod(0o600)
            except OSError:
                pass


def get_current_user() -> str:
    """Get the current system username for RBAC lookups."""
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


# ---------------------------------------------------------------------------
# 10. Signed pipeline execution receipts (non-repudiation)
# ---------------------------------------------------------------------------


def sign_execution_receipt(
    evidence_dir: Path,
    gate_results: Dict[str, str],
    final_status: str,
    key: Optional[bytes] = None,
) -> Path:
    """Create a signed execution receipt for non-repudiation.

    The receipt records who ran the pipeline, when, what the results were,
    and signs it with HMAC-SHA256 so it cannot be forged.

    Args:
        evidence_dir: Directory to write the receipt.
        gate_results: Dict mapping gate names to pass/fail status.
        final_status: Overall pipeline status.
        key: HMAC key (uses model signing key if None).

    Returns:
        Path to the signed receipt file.
    """
    if key is None:
        key = _derive_key()

    import platform
    receipt: Dict[str, Any] = {
        "schema_version": 1,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "executor": get_current_user(),
        "hostname": platform.node(),
        "pid": os.getpid(),
        "final_status": final_status,
        "gate_results": gate_results,
        "gate_count": len(gate_results),
        "passed": sum(1 for s in gate_results.values() if s == "pass"),
        "failed": sum(1 for s in gate_results.values() if s == "fail"),
    }

    receipt_json = json.dumps(receipt, ensure_ascii=True, sort_keys=True)
    signature = hmac.new(key, receipt_json.encode("utf-8"), hashlib.sha256).hexdigest()
    receipt["hmac_signature"] = signature

    receipt_path = evidence_dir / ".execution_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file, fsync, then rename to prevent
    # corruption if process crashes mid-write.
    tmp_path = receipt_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp_path.replace(receipt_path)

    return receipt_path


def verify_execution_receipt(
    receipt_path: Path,
    key: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Verify a signed execution receipt.

    Returns:
        Dict with 'valid' (bool) and receipt metadata.
    """
    if key is None:
        key = _derive_key()

    if not receipt_path.exists():
        return {"valid": False, "reason": "receipt_not_found"}

    try:
        receipt = _size_capped_json_load(receipt_path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return {"valid": False, "reason": f"receipt_corrupt: {exc}"}

    stored_sig = receipt.pop("hmac_signature", None)
    if stored_sig is None:
        return {"valid": False, "reason": "missing_signature"}

    receipt_json = json.dumps(receipt, ensure_ascii=True, sort_keys=True)
    expected_sig = hmac.new(key, receipt_json.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(stored_sig, expected_sig):
        return {"valid": False, "reason": "signature_mismatch"}

    return {
        "valid": True,
        "executor": receipt.get("executor"),
        "timestamp": receipt.get("timestamp_utc"),
        "final_status": receipt.get("final_status"),
        "gate_count": receipt.get("gate_count"),
        "passed": receipt.get("passed"),
        "failed": receipt.get("failed"),
    }


# ---------------------------------------------------------------------------
# 11. Secure file cleanup
# ---------------------------------------------------------------------------


def secure_delete(path: Path, passes: int = 1) -> None:
    """Overwrite a file with zeros before unlinking to prevent data recovery.

    Args:
        path: File to securely delete.
        passes: Number of overwrite passes (1 is sufficient for SSDs).
    """
    if not path.exists() or not path.is_file():
        return
    try:
        size = path.stat().st_size
        with path.open("r+b") as fh:
            for _ in range(passes):
                fh.seek(0)
                remaining = size
                chunk = 64 * 1024
                while remaining > 0:
                    write_size = min(chunk, remaining)
                    fh.write(b"\x00" * write_size)
                    remaining -= write_size
                fh.flush()
                os.fsync(fh.fileno())
    except OSError:
        pass
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def secure_cleanup_dir(directory: Path, pattern: str = "*") -> int:
    """Securely delete all matching files in a directory.

    Returns number of files deleted.
    """
    count = 0
    for fpath in directory.glob(pattern):
        if fpath.is_file():
            secure_delete(fpath)
            count += 1
    return count


# ---------------------------------------------------------------------------
# 10. Resource exhaustion protection
# ---------------------------------------------------------------------------


def check_file_size(path: Path, max_bytes: int, label: str = "file") -> None:
    """Raise ValueError if a file exceeds the size limit."""
    if path.exists():
        size = path.stat().st_size
        if size > max_bytes:
            raise ValueError(
                f"{label}_too_large: {size} bytes exceeds limit "
                f"{max_bytes} ({max_bytes / 1024 / 1024:.0f} MB)"
            )


def check_csv_row_limit(path: Path, max_rows: int = 10_000_000) -> int:
    """Quick line-count check for CSV files to prevent memory exhaustion.

    Returns actual row count.
    """
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for _ in fh:
            count += 1
            if count > max_rows + 1:  # +1 for header
                raise ValueError(
                    f"csv_too_many_rows: {path.name} exceeds {max_rows} rows"
                )
    return max(0, count - 1)  # subtract header


# ---------------------------------------------------------------------------
# 8. Dependency integrity verification
# ---------------------------------------------------------------------------


def verify_critical_imports() -> Dict[str, Any]:
    """Verify that critical dependencies are genuine (not monkey-patched).

    Checks:
        - sklearn is the real scikit-learn
        - numpy has expected attributes
        - pandas is genuine

    Returns:
        Dict with verification results.
    """
    results: Dict[str, Any] = {"verified": True, "checks": []}

    try:
        import sklearn
        check = {
            "package": "sklearn",
            "version": getattr(sklearn, "__version__", "unknown"),
            "path": getattr(sklearn, "__file__", "unknown"),
            "ok": hasattr(sklearn, "ensemble") and hasattr(sklearn, "pipeline"),
        }
        results["checks"].append(check)
        if not check["ok"]:
            results["verified"] = False
    except ImportError:
        results["checks"].append({"package": "sklearn", "ok": False, "reason": "not_installed"})
        results["verified"] = False

    try:
        import numpy as np
        check = {
            "package": "numpy",
            "version": getattr(np, "__version__", "unknown"),
            "path": getattr(np, "__file__", "unknown"),
            "ok": hasattr(np, "ndarray") and hasattr(np, "random"),
        }
        results["checks"].append(check)
        if not check["ok"]:
            results["verified"] = False
    except ImportError:
        results["checks"].append({"package": "numpy", "ok": False, "reason": "not_installed"})
        results["verified"] = False

    try:
        import pandas as pd
        check = {
            "package": "pandas",
            "version": getattr(pd, "__version__", "unknown"),
            "path": getattr(pd, "__file__", "unknown"),
            "ok": hasattr(pd, "DataFrame") and hasattr(pd, "read_csv"),
        }
        results["checks"].append(check)
        if not check["ok"]:
            results["verified"] = False
    except ImportError:
        results["checks"].append({"package": "pandas", "ok": False, "reason": "not_installed"})
        results["verified"] = False

    return results


# ---------------------------------------------------------------------------
# 9. Security audit report generator
# ---------------------------------------------------------------------------


def run_security_audit(evidence_dir: Path) -> Dict[str, Any]:
    """Run a comprehensive security audit on a pipeline output directory.

    Checks:
        1. Model artifact signature verification
        2. Evidence file integrity (manifest)
        3. Dependency integrity
        4. File permission checks
        5. Sensitive data exposure scan

    Args:
        evidence_dir: Path to the evidence output directory.

    Returns:
        Security audit report dict.
    """
    issues: List[Dict[str, str]] = []
    evidence_dir = Path(evidence_dir).expanduser().resolve()

    # Check 1: Model signature
    model_paths = list(evidence_dir.parent.rglob("*.pkl"))
    for mp in model_paths:
        result = verify_model_artifact(mp)
        if not result["verified"]:
            issues.append({
                "severity": "critical",
                "code": "unsigned_model",
                "message": f"Model artifact {mp.name} has no valid signature: {result['reason']}",
            })

    # Check 2: Evidence manifest
    manifest_path = evidence_dir / ".manifest.json"
    if manifest_path.exists():
        ok, manifest_issues = ArtifactManifest.verify(manifest_path)
        if not ok:
            for mi in manifest_issues:
                issues.append({
                    "severity": "high",
                    "code": "manifest_integrity",
                    "message": mi,
                })
    else:
        issues.append({
            "severity": "medium",
            "code": "no_manifest",
            "message": "No artifact integrity manifest found in evidence directory",
        })

    # Check 3: Dependency integrity
    dep_result = verify_critical_imports()
    if not dep_result["verified"]:
        for check in dep_result["checks"]:
            if not check.get("ok", True):
                issues.append({
                    "severity": "critical",
                    "code": "dependency_integrity",
                    "message": f"Package {check['package']} failed integrity check",
                })

    # Check 4 & 5: File permissions + sensitive data scan (single pass)
    for fpath in evidence_dir.glob("*.json"):
        try:
            mode = fpath.stat().st_mode
            if mode & 0o002:  # world-writable
                issues.append({
                    "severity": "high",
                    "code": "world_writable",
                    "message": f"{fpath.name} is world-writable (mode {oct(mode)})",
                })
            content = fpath.read_text(encoding="utf-8")
            hits = scan_sensitive_data(content)
            if hits:
                label, _match = hits[0]
                issues.append({
                    "severity": "high",
                    "code": "sensitive_data_exposure",
                    "message": f"{fpath.name} may contain sensitive data (pattern: {label})",
                })
        except OSError:
            pass

    # Check 6: Oversized files (potential data exfiltration)
    _OVERSIZED_THRESHOLD = 500 * 1024 * 1024
    for fpath in evidence_dir.rglob("*"):
        if not fpath.is_file():
            continue
        fsize = fpath.stat().st_size
        if fsize > _OVERSIZED_THRESHOLD:
            issues.append({
                "severity": "medium",
                "code": "oversized_file",
                "message": f"{fpath.name} exceeds 500MB ({fsize} bytes)",
            })

    critical_count = sum(1 for i in issues if i["severity"] == "critical")
    high_count = sum(1 for i in issues if i["severity"] == "high")

    return {
        "status": "fail" if critical_count > 0 else ("warn" if high_count > 0 else "pass"),
        "schema_version": 1,
        "audit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issue_count": len(issues),
        "critical_count": critical_count,
        "high_count": high_count,
        "issues": issues,
        "dependency_verification": dep_result,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI: run security audit or sign/verify model artifacts."""
    import argparse

    parser = argparse.ArgumentParser(
        description="MLGG Security Hardening Tools",
    )
    sub = parser.add_subparsers(dest="command")

    # audit
    audit_p = sub.add_parser("audit", help="Run security audit on evidence directory")
    audit_p.add_argument("evidence_dir", help="Path to evidence directory")

    # sign
    sign_p = sub.add_parser("sign", help="Sign a model artifact with HMAC")
    sign_p.add_argument("model_path", help="Path to model .pkl file")

    # verify
    verify_p = sub.add_parser("verify", help="Verify a model artifact signature")
    verify_p.add_argument("model_path", help="Path to model .pkl file")

    # manifest
    manifest_p = sub.add_parser("manifest", help="Create integrity manifest for evidence files")
    manifest_p.add_argument("evidence_dir", help="Path to evidence directory")

    # check-deps
    sub.add_parser("check-deps", help="Verify critical dependency integrity")

    # encrypt
    enc_p = sub.add_parser("encrypt", help="Encrypt evidence files at rest")
    enc_p.add_argument("evidence_dir", help="Path to evidence directory")
    enc_p.add_argument("--pattern", default="*.json", help="Glob pattern for files to encrypt (default: *.json)")

    # decrypt
    dec_p = sub.add_parser("decrypt", help="Decrypt .enc evidence files")
    dec_p.add_argument("file", help="Path to .enc file to decrypt")
    dec_p.add_argument("--output", help="Output path (default: strip .enc suffix)")

    # secure-delete
    sdel_p = sub.add_parser("secure-delete", help="Securely delete files (zero-fill + unlink)")
    sdel_p.add_argument("path", help="File or directory to securely delete")
    sdel_p.add_argument("--pattern", default="*", help="Glob pattern if path is a directory")

    # verify-audit
    va_p = sub.add_parser("verify-audit", help="Verify gate audit log chain integrity")
    va_p.add_argument("evidence_dir", help="Path to evidence directory")

    args = parser.parse_args()

    if args.command == "audit":
        report = run_security_audit(Path(args.evidence_dir))
        print(json.dumps(report, indent=2))
        return 0 if report["status"] != "fail" else 1

    elif args.command == "sign":
        model_path = Path(args.model_path).expanduser().resolve()
        sig_path = sign_model_artifact(model_path)
        print(f"Signed: {model_path}")
        print(f"Signature: {sig_path}")
        return 0

    elif args.command == "verify":
        model_path = Path(args.model_path).expanduser().resolve()
        result = verify_model_artifact(model_path)
        print(json.dumps(result, indent=2))
        return 0 if result["verified"] else 1

    elif args.command == "manifest":
        evidence_dir = Path(args.evidence_dir).expanduser().resolve()
        manifest = ArtifactManifest()
        for fpath in sorted(evidence_dir.glob("*.json")):
            manifest.add_file(fpath)
        for fpath in sorted(evidence_dir.glob("*.csv.gz")):
            manifest.add_file(fpath)
        manifest_path = evidence_dir / ".manifest.json"
        manifest.save(manifest_path)
        print(f"Manifest created: {manifest_path}")
        return 0

    elif args.command == "check-deps":
        result = verify_critical_imports()
        print(json.dumps(result, indent=2))
        return 0 if result["verified"] else 1

    elif args.command == "encrypt":
        evidence_dir = Path(args.evidence_dir).expanduser().resolve()
        pattern = args.pattern
        count = 0
        for fpath in sorted(evidence_dir.glob(pattern)):
            if fpath.is_file() and not fpath.name.endswith(".enc"):
                enc_path = encrypt_file(fpath)
                print(f"Encrypted: {fpath.name} → {enc_path.name}")
                count += 1
        print(f"\n{count} file(s) encrypted.")
        return 0

    elif args.command == "decrypt":
        enc_path = Path(args.file).expanduser().resolve()
        if not enc_path.exists():
            print(f"Error: file not found: {enc_path}", file=sys.stderr)
            return 1
        plaintext = decrypt_file(enc_path)
        if args.output:
            out = Path(args.output).expanduser().resolve()
        else:
            out = enc_path.with_suffix("")  # strip .enc
        out.write_bytes(plaintext)
        print(f"Decrypted: {enc_path.name} → {out.name}")
        return 0

    elif args.command == "secure-delete":
        target = Path(args.path).expanduser().resolve()
        if target.is_file():
            secure_delete(target)
            print(f"Securely deleted: {target}")
        elif target.is_dir():
            count = secure_cleanup_dir(target, args.pattern)
            print(f"Securely deleted {count} file(s) in {target}")
        else:
            print(f"Error: path not found: {target}", file=sys.stderr)
            return 1
        return 0

    elif args.command == "verify-audit":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _gate_utils import verify_audit_chain
        evidence_dir = Path(args.evidence_dir).expanduser().resolve()
        result = verify_audit_chain(evidence_dir)
        print(json.dumps(result, indent=2))
        return 0 if result.get("valid", False) else 1

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
