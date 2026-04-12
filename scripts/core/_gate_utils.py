"""
Shared utility functions for ml-governance-guard gate scripts.

This module consolidates common helper functions that are duplicated across
gate scripts. Each gate script remains independently runnable; importing
from this module is optional and does not change gate semantics.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    import numpy
    import pandas




# ═══════════════════════════════════════════════════════════════
# Issue Reporting
# ═══════════════════════════════════════════════════════════════

def add_issue(
    bucket: List[Dict[str, Any]],
    code: str,
    message: str,
    details: Dict[str, Any],
) -> None:
    """Append a structured issue dict to a bucket list."""
    bucket.append({"code": code, "message": message, "details": details})


_MAX_JSON_FILE_SIZE = 100 * 1024 * 1024  # 100 MB safety limit
_MAX_CSV_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB safety limit
_WARN_CSV_FILE_SIZE = 500 * 1024 * 1024  # 500 MB warning threshold




# ═══════════════════════════════════════════════════════════════
# CSV Validation
# ═══════════════════════════════════════════════════════════════

def check_csv_file_size(path: Path) -> None:
    """Warn on large CSV files, raise on extremely large ones."""
    try:
        size = path.stat().st_size
        if size > _MAX_CSV_FILE_SIZE:
            raise ValueError(
                f"CSV file too large: {path.name} is {size / (1024**3):.1f} GB "
                f"(limit {_MAX_CSV_FILE_SIZE // (1024**3)} GB). "
                f"Consider sampling or chunked processing."
            )
        if size > _WARN_CSV_FILE_SIZE:
            print(
                f"[WARN] Large CSV: {path.name} is {size / (1024**2):.0f} MB. "
                f"Processing may be slow.",
                file=sys.stderr,
            )
    except OSError:
        pass


def _check_json_file_size(path: Path) -> None:
    """Raise ValueError if a JSON file exceeds the safety size limit."""
    try:
        size = path.stat().st_size
        if size > _MAX_JSON_FILE_SIZE:
            raise ValueError(
                f"JSON file too large: {path} is {size} bytes "
                f"(limit {_MAX_JSON_FILE_SIZE // (1024*1024)} MB)"
            )
    except OSError:
        pass  # File may not exist yet; let caller handle


def load_json(path: Union[str, Path]) -> Dict[str, Any]:
    """Load and validate a JSON object from a string or Path."""
    p = Path(path).expanduser().resolve() if isinstance(path, str) else path
    _check_json_file_size(p)
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {p}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be object: {p}")
    return payload


# Backward-compatible aliases
load_json_from_path = load_json
load_json_from_str = load_json


def load_json_optional(path: Path) -> Optional[Dict[str, Any]]:
    """Load a JSON object if the file exists, else return None."""
    if not path.exists():
        return None
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (json.JSONDecodeError, OSError, ValueError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively coerce objects to JSON-safe Python primitives.

    Handles: non-finite floats (NaN/Inf → None), numpy scalars/arrays,
    pandas Timestamps, sets, bytes. Without this, json.dump(allow_nan=False)
    raises TypeError on numpy.int64/float64 — the most common crash path
    when serializing sklearn/pandas outputs.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, set):
        return [_sanitize_for_json(v) for v in sorted(obj, key=str)]
    # numpy scalars/arrays (imported lazily to avoid hard dep)
    try:
        import numpy as _np
        if isinstance(obj, _np.integer):
            return int(obj)
        if isinstance(obj, _np.floating):
            val = float(obj)
            return val if math.isfinite(val) else None
        if isinstance(obj, _np.ndarray):
            return [_sanitize_for_json(v) for v in obj.tolist()]
        if isinstance(obj, _np.bool_):
            return bool(obj)
    except ImportError:
        pass
    # pandas Timestamp
    try:
        import pandas as _pd
        if isinstance(obj, _pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj




# ═══════════════════════════════════════════════════════════════
# File I/O
# ═══════════════════════════════════════════════════════════════

def write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write a JSON object to a file.

    Non-finite floats (NaN, ±Infinity) are replaced with ``null`` before
    serialisation.  ``allow_nan=False`` is set as a hard backstop so any
    value that slips past the sanitizer raises immediately rather than
    producing silently invalid JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = _sanitize_for_json(payload)
    tmp_path = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1_000_000)}"
    )
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=True, indent=2, sort_keys=True,
                  allow_nan=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp_path.replace(path)


_FORBIDDEN_PATH_PREFIXES = [
    "/etc", "/private/etc", "/proc", "/sys", "/dev",
    "/var/run", "/boot", "/sbin",
]




# ═══════════════════════════════════════════════════════════════
# Path Security
# ═══════════════════════════════════════════════════════════════

def resolve_path(base: Path, value: str, sandbox: Optional[Path] = None) -> Path:
    """Resolve a potentially relative path against a base directory.

    Args:
        base: Base directory for relative paths.
        value: Raw path string to resolve.
        sandbox: If provided, the resolved path must be under this directory.

    Raises:
        ValueError: If the path contains null bytes or targets forbidden system paths.
    """
    if "\x00" in value:
        raise ValueError(f"Null byte in path: {value!r}")
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base / p).resolve()
    else:
        p = p.resolve()
    resolved = str(p)
    for prefix in _FORBIDDEN_PATH_PREFIXES:
        if resolved.startswith(prefix + "/") or resolved == prefix:
            raise ValueError(f"Path targets forbidden system location: {p}")
    if sandbox is not None:
        sandbox_resolved = sandbox.resolve()
        try:
            p.relative_to(sandbox_resolved)
        except ValueError:
            raise ValueError(
                f"Path escapes sandbox: {p} is not under {sandbox_resolved}"
            )
    return p


_gate_start_time: Optional[float] = None




# ═══════════════════════════════════════════════════════════════
# Timing & Timeout
# ═══════════════════════════════════════════════════════════════

def start_gate_timer() -> None:
    """Record the gate start time for execution timing."""
    global _gate_start_time
    _gate_start_time = time.time()


def get_gate_elapsed() -> float:
    """Return elapsed seconds since start_gate_timer() was called."""
    if _gate_start_time is None:
        return 0.0
    return time.time() - _gate_start_time


def inject_execution_time(report: Dict[str, Any]) -> Dict[str, Any]:
    """Add execution_time_seconds to a gate report dict.

    Args:
        report: Gate report dict to augment.

    Returns:
        The same dict with execution_time_seconds added.
    """
    report["execution_time_seconds"] = round(get_gate_elapsed(), 3)
    return report


class GateTimeoutError(Exception):
    """Raised when a gate exceeds its configured timeout."""


def add_timeout_argument(parser: argparse.ArgumentParser) -> None:
    """Add a --timeout argument to a gate argparse parser.

    Args:
        parser: ArgumentParser to add the --timeout flag to.
    """
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Maximum execution time in seconds (0=unlimited).",
    )


def install_gate_timeout(
    timeout_seconds: int,
    report_path: Optional[Path] = None,
    gate_name: str = "unknown_gate",
) -> None:
    """Install a SIGALRM-based timeout for a gate script.

    When the timeout fires, a timeout report is written (if report_path
    is provided) and the process exits with code 2 (fail).

    Args:
        timeout_seconds: Seconds before timeout (0 = disabled).
        report_path: Path to write the timeout report JSON.
        gate_name: Name of the gate for the report.
    """
    if timeout_seconds <= 0:
        return
    if not hasattr(signal, "SIGALRM"):
        return

    def _handler(signum: int, frame: Any) -> None:
        payload: Dict[str, Any] = {
            "status": "fail",
            "gate_name": gate_name,
            "strict_mode": True,
            "timeout_seconds": timeout_seconds,
            "failures": [
                {
                    "code": "gate_timeout",
                    "message": f"Gate exceeded {timeout_seconds}s timeout.",
                    "details": {"timeout_seconds": timeout_seconds},
                }
            ],
            "warnings": [],
        }
        if report_path is not None:
            try:
                write_json(report_path, payload)
            except Exception:
                pass
        print(
            f"TIMEOUT: {gate_name} exceeded {timeout_seconds}s limit.",
            file=sys.stderr,
        )
        sys.exit(2)

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_seconds)




# ═══════════════════════════════════════════════════════════════
# Time Parsing
# ═══════════════════════════════════════════════════════════════

def try_parse_time(value: str) -> Optional[float]:
    """Parse a time string to epoch float, trying multiple formats.

    All naive (timezone-unaware) timestamps are interpreted as **UTC** to
    ensure deterministic, platform-independent comparisons.  Previously,
    naive dates used local time (``datetime.timestamp()``), causing the
    same date string to produce different epoch values on machines in
    different timezones.

    Args:
        value: Raw time string (ISO-8601, date, or numeric epoch).

    Returns:
        Epoch timestamp as float (always UTC-based), or None if unparseable.
    """
    import datetime as _dt

    _UTC = _dt.timezone.utc

    s = value.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    # ISO-8601 with Z or offset
    iso = s.replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(iso)
        # If already aware, use as-is; otherwise treat as UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return dt.timestamp()
    except ValueError:
        pass
    # Common date/datetime formats — all treated as UTC
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            dt = _dt.datetime.strptime(s, fmt).replace(tzinfo=_UTC)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def epoch_to_iso(ts: Optional[float]) -> Optional[str]:
    """Convert epoch timestamp to UTC ISO-8601 string.

    Args:
        ts: Epoch timestamp, or None.

    Returns:
        ISO-8601 string with Z suffix, or None for non-finite values.
    """
    import datetime as _dt

    if ts is None:
        return None
    if not math.isfinite(ts):
        return None
    try:
        return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None




# ═══════════════════════════════════════════════════════════════
# Type Conversion & Normalization
# ═══════════════════════════════════════════════════════════════

def to_float(value: Any) -> Optional[float]:
    """Safely convert a value to float, rejecting inf/nan and non-numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            parsed = float(token)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


# ---------------------------------------------------------------------------
# Shared numeric helpers used by multiple gate scripts
# ---------------------------------------------------------------------------


# Common Cyrillic/Greek → Latin confusable mappings (Unicode TR39 subset).
# Only includes characters that are visually identical to Latin letters
# and commonly used in homoglyph attacks.
_CONFUSABLE_MAP = {
    "\u0410": "A", "\u0430": "a",  # Cyrillic А/а
    "\u0412": "B", "\u0432": "b",  # Cyrillic В/в (visual B/b)
    "\u0421": "C", "\u0441": "c",  # Cyrillic С/с
    "\u0415": "E", "\u0435": "e",  # Cyrillic Е/е
    "\u041d": "H", "\u043d": "h",  # Cyrillic Н/н (visual H/h)
    "\u041a": "K", "\u043a": "k",  # Cyrillic К/к
    "\u041c": "M", "\u043c": "m",  # Cyrillic М/м
    "\u041e": "O", "\u043e": "o",  # Cyrillic О/о
    "\u0420": "P", "\u0440": "p",  # Cyrillic Р/р
    "\u0422": "T", "\u0442": "t",  # Cyrillic Т/т
    "\u0425": "X", "\u0445": "x",  # Cyrillic Х/х
    "\u0443": "y",                  # Cyrillic у
    "\u0392": "B",                  # Greek Β
    "\u0395": "E",                  # Greek Ε
    "\u0397": "H",                  # Greek Η
    "\u039a": "K",                  # Greek Κ
    "\u039c": "M",                  # Greek Μ
    "\u039d": "N",                  # Greek Ν
    "\u039f": "O",                  # Greek Ο
    "\u03a1": "P",                  # Greek Ρ
    "\u03a4": "T",                  # Greek Τ
    "\u03a7": "X",                  # Greek Χ
}


def _normalize_unicode(value: str) -> str:
    """Normalize Unicode to NFKD + strip invisible chars + map confusables.

    Defends against:
    - Compatibility variants (ﬁ→fi, ™→TM via NFKD)
    - Cyrillic/Greek lookalikes (е→e, Ρ→P via confusable map)
    - Zero-width spaces, joiners, and other invisible characters
    """
    import unicodedata
    # Step 1: NFKD decomposes compatibility characters
    nfkd = unicodedata.normalize("NFKD", value)
    # Step 2: Map known Cyrillic/Greek confusables to Latin
    mapped = "".join(_CONFUSABLE_MAP.get(ch, ch) for ch in nfkd)
    # Step 3: Strip zero-width and invisible Unicode (category Cf)
    cleaned = "".join(
        ch for ch in mapped
        if unicodedata.category(ch) not in ("Cf",)
    )
    return cleaned


def contains_test_token(value: Optional[str]) -> bool:
    """Return True if *value* contains a 'test' token indicating test-data usage.

    Applies Unicode NFKD normalization and strips invisible characters before
    checking, to defend against Cyrillic/Greek lookalike and zero-width bypass.

    Handles negative prefixes (``no_test``, ``without_test``, ``exclude_test``,
    ``notest``) and benign words (``latest``, ``attest``, ``tested``,
    ``testing``) to avoid false positives.

    Returns ``False`` for ``None`` or empty strings.
    """
    import re

    if not value:
        return False
    # Normalize Unicode before any comparison
    token = _normalize_unicode(value).strip().lower()
    # Negative prefixes → explicitly excluding test data, not leakage.
    if "no_test" in token or "without_test" in token or "exclude_test" in token or "notest" in token:
        return False
    parts = [p for p in re.split(r"[^a-z0-9]+", token) if p]
    if "test" in parts:
        return True
    _benign = {"latest", "attest", "tested", "testing"}
    for part in parts:
        if part.startswith("test") or part.endswith("test"):
            if part not in _benign:
                return True
    return False


def canonical_metric_token(value: str) -> str:
    """Normalize a metric name to a canonical lowercase token for comparison."""
    import re
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def is_finite_number(value: Any) -> bool:
    """Check whether *value* is a finite int or float (excluding bool)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def to_int(value: Any) -> Optional[int]:
    """Safely convert *value* to int if it is integer-like, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and math.isfinite(value) and float(value).is_integer():
        return int(value)
    return None


def safe_ratio(num: float, den: float) -> float:
    """Return *num / den*, or 0.0 when *den* is non-positive."""
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def confusion_counts(
    y_true: "numpy.ndarray[Any, Any]", y_pred: "numpy.ndarray[Any, Any]"  # noqa: F821
) -> Dict[str, int]:
    """Compute TP/FP/TN/FN from binary label arrays.

    Args:
        y_true: Ground-truth binary labels (0/1).
        y_pred: Predicted binary labels (0/1).

    Returns:
        Dict with keys ``tp``, ``fp``, ``tn``, ``fn``.
    """
    import numpy as np  # local import to keep module lightweight

    yt = y_true.astype(int)
    yp = y_pred.astype(int)
    tp = int(np.sum((yt == 1) & (yp == 1)))
    fp = int(np.sum((yt == 0) & (yp == 1)))
    tn = int(np.sum((yt == 0) & (yp == 0)))
    fn = int(np.sum((yt == 1) & (yp == 0)))
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def normalize_binary(values: "pandas.Series") -> Optional[Any]:  # noqa: F821
    """Coerce a pandas Series to a binary int ndarray, or None on failure.

    Returns None when the series contains non-finite or non-{0,1} values.
    """
    import numpy as np
    import pandas as pd

    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(arr)):
        return None
    if not np.all(np.isin(arr, [0.0, 1.0])):
        return None
    return arr.astype(int)


def metric_panel(
    y_true: "numpy.ndarray[Any, Any]",  # noqa: F821
    y_score: "numpy.ndarray[Any, Any]",  # noqa: F821
    y_pred: "numpy.ndarray[Any, Any]",  # noqa: F821
    beta: float,
) -> tuple[Any, ...]:
    """Compute a standard binary-classification metric panel.

    Args:
        y_true: Ground-truth binary labels (0/1).
        y_score: Predicted probabilities in [0, 1].
        y_pred: Hard predictions (0/1).
        beta: Beta for F-beta score (typically 2.0).

    Returns:
        ``(metrics_dict, confusion_matrix_dict)`` tuple.
    """
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    cm = confusion_counts(y_true, y_pred)
    tp = float(cm["tp"])
    fp = float(cm["fp"])
    tn = float(cm["tn"])
    fn = float(cm["fn"])
    precision = safe_ratio(tp, tp + fp)
    sensitivity = safe_ratio(tp, tp + fn)
    specificity = safe_ratio(tn, tn + fp)
    npv = safe_ratio(tn, tn + fn)
    accuracy = safe_ratio(tp + tn, tp + fp + tn + fn)
    f1 = (
        0.0
        if (precision + sensitivity) <= 0
        else (2.0 * precision * sensitivity) / (precision + sensitivity)
    )
    beta_sq = beta * beta
    f2 = (
        0.0
        if ((beta_sq * precision) + sensitivity) <= 0
        else ((1.0 + beta_sq) * precision * sensitivity)
        / ((beta_sq * precision) + sensitivity)
    )
    roc_auc = float(roc_auc_score(y_true, y_score))
    pr_auc = float(average_precision_score(y_true, y_score))
    brier = float(brier_score_loss(y_true, y_score))
    import math as _math

    # Matthews Correlation Coefficient (Chicco & Jurman, BMC Genomics 2020)
    mcc_denom = _math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn) - (fp * fn)) / mcc_denom if mcc_denom > 0 else 0.0

    # Likelihood ratios (clinical decision-making gold standard)
    # Cap at 1000 to avoid JSON-incompatible Infinity (consistent with
    # train_select_evaluate.py Round 3 fix).
    _LR_CAP = 1000.0
    lr_positive = min(sensitivity / (1.0 - specificity), _LR_CAP) if specificity < 1.0 else _LR_CAP
    lr_negative = min((1.0 - sensitivity) / specificity, _LR_CAP) if specificity > 0 else _LR_CAP

    metrics = {
        "accuracy": accuracy,
        "precision": precision,
        "ppv": precision,
        "npv": npv,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "f1": f1,
        "f2_beta": f2,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "brier": brier,
        "mcc": mcc,
        "lr_positive": lr_positive,
        "lr_negative": lr_negative,
    }
    return metrics, cm




# ═══════════════════════════════════════════════════════════════
# Calibration Metrics
# ═══════════════════════════════════════════════════════════════

def calibration_metrics(
    y_true: "numpy.ndarray[Any, Any]",
    y_score: "numpy.ndarray[Any, Any]",
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Compute calibration three-piece suite per Van Calster 2019.

    Returns:
        Dict with calibration_intercept, calibration_slope, oe_ratio,
        ece, hosmer_lemeshow_stat, hosmer_lemeshow_p, brier_skill_score,
        and per-bin calibration data.

    References:
        Van Calster B et al. BMC Med. 2019;17:230.
        Steyerberg EW. Clinical Prediction Models, 2nd ed. 2019.
    """
    import numpy as np

    y_t = np.asarray(y_true, dtype=float)
    y_s = np.asarray(y_score, dtype=float)
    n = len(y_t)

    # Guard: degenerate inputs
    if n == 0:
        return {"error": "empty_input", "n_samples": 0}
    if np.allclose(y_s, y_s[0]):
        return {
            "error": "constant_y_score",
            "y_score_value": round(float(y_s[0]), 6),
            "n_samples": n,
            "message": "y_score is constant; calibration metrics are undefined.",
        }
    if len(np.unique(y_t)) < 2:
        return {
            "error": "single_class_y_true",
            "n_samples": n,
            "message": "y_true has only one class; calibration metrics require both classes.",
        }
    if n < n_bins:
        n_bins = max(n // 2, 2)  # Reduce bins for small samples

    # --- Calibration slope & intercept (logistic recalibration) ---
    # Fit: logit(y) ~ a + b * logit(y_score)
    # Using sklearn LogisticRegression on logit(y_score) as single feature
    eps = 1e-7
    logit_s = np.log(np.clip(y_s, eps, 1 - eps) / (1 - np.clip(y_s, eps, 1 - eps)))

    from sklearn.linear_model import LogisticRegression
    import sklearn
    _sklearn_version = tuple(int(x) for x in sklearn.__version__.split(".")[:2])
    if _sklearn_version >= (1, 8):
        # sklearn 1.8 deprecated penalty=None; use C=np.inf instead.
        lr = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000)
    elif _sklearn_version >= (1, 2):
        # penalty=None supported from sklearn 1.2+; unpenalised logistic
        # regression gives unbiased calibration slope (Van Calster 2019).
        lr = LogisticRegression(penalty=None, solver="lbfgs", max_iter=1000)
    else:
        # Fallback: very large C ≈ no regularisation
        lr = LogisticRegression(C=1e10, solver="lbfgs", max_iter=1000)
    lr.fit(logit_s.reshape(-1, 1), y_t)
    cal_intercept = float(lr.intercept_[0])
    cal_slope = float(lr.coef_[0][0])

    # --- O:E ratio ---
    observed = float(y_t.sum())
    expected = float(y_s.sum())
    oe_ratio = observed / expected if expected > 0 else float("nan")

    # --- ECE (Expected Calibration Error) ---
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    bin_data = []
    hl_stat = 0.0  # Hosmer-Lemeshow chi-sq

    for i in range(n_bins):
        mask = (y_s >= bin_edges[i]) & (y_s < bin_edges[i + 1])
        if i == n_bins - 1:
            mask = (y_s >= bin_edges[i]) & (y_s <= bin_edges[i + 1])
        n_bin = int(mask.sum())
        if n_bin == 0:
            bin_data.append({"bin": i, "n": 0, "mean_predicted": 0, "fraction_positive": 0})
            continue
        mean_pred = float(y_s[mask].mean())
        frac_pos = float(y_t[mask].mean())
        ece += abs(frac_pos - mean_pred) * (n_bin / n)

        # Hosmer-Lemeshow contribution
        e_pos = mean_pred * n_bin
        e_neg = (1 - mean_pred) * n_bin
        o_pos = float(y_t[mask].sum())
        o_neg = n_bin - o_pos
        if e_pos > 0:
            hl_stat += (o_pos - e_pos) ** 2 / e_pos
        if e_neg > 0:
            hl_stat += (o_neg - e_neg) ** 2 / e_neg

        bin_data.append({
            "bin": i,
            "n": n_bin,
            "mean_predicted": round(mean_pred, 4),
            "fraction_positive": round(frac_pos, 4),
        })

    # HL p-value (chi-sq with n_bins - 2 df)
    from scipy.stats import chi2
    hl_df = max(n_bins - 2, 1)
    hl_p = float(1 - chi2.cdf(hl_stat, hl_df))

    # --- Brier Skill Score ---
    prevalence = float(y_t.mean())
    brier_model = float(np.mean((y_t - y_s) ** 2))
    brier_ref = prevalence * (1 - prevalence)
    brier_skill = 1 - (brier_model / brier_ref) if brier_ref > 0 else 0.0

    return {
        "calibration_intercept": round(cal_intercept, 4),
        "calibration_slope": round(cal_slope, 4),
        "oe_ratio": round(oe_ratio, 4),
        "ece": round(ece, 4),
        "hosmer_lemeshow_chi2": round(hl_stat, 4),
        "hosmer_lemeshow_p": round(hl_p, 4),
        "hosmer_lemeshow_df": hl_df,
        "brier_score": round(brier_model, 4),
        "brier_skill_score": round(brier_skill, 4),
        "brier_reference": round(brier_ref, 4),
        "n_bins": n_bins,
        "bin_data": bin_data,
    }


def learning_curve_data(
    estimator: Any,
    X_train: Any,
    y_train: Any,
    X_test: Any,
    y_test: Any,
    fractions: Optional[list] = None,
    metric: str = "pr_auc",
    seed: int = 42,
) -> list:
    """Compute learning curve: performance vs training set fraction.

    Returns list of dicts with fraction, n_train, train_score, test_score.
    """
    import numpy as np
    from sklearn.base import clone
    from sklearn.metrics import average_precision_score, roc_auc_score

    if fractions is None:
        fractions = [0.1, 0.2, 0.3, 0.5, 0.7, 0.85, 1.0]

    rng = np.random.default_rng(seed)
    n = X_train.shape[0]
    results = []

    score_fn = average_precision_score if metric == "pr_auc" else roc_auc_score

    for frac in fractions:
        k = max(int(n * frac), 20)
        idx = rng.choice(n, k, replace=False) if k < n else np.arange(n)

        if hasattr(X_train, "iloc"):
            X_sub = X_train.iloc[idx]
        else:
            X_sub = X_train[idx]
        y_sub = y_train.iloc[idx] if hasattr(y_train, "iloc") else np.asarray(y_train)[idx]

        if len(np.unique(y_sub)) < 2:
            continue

        try:
            est = clone(estimator)
            est.fit(X_sub, y_sub)
            train_score = float(score_fn(y_sub, est.predict_proba(X_sub)[:, 1]))
            test_score = float(score_fn(y_test, est.predict_proba(X_test)[:, 1]))
        except Exception as exc:
            print(f"[learning_curve] fraction={frac}: {exc}", file=sys.stderr)
            continue

        results.append({
            "fraction": round(frac, 2),
            "n_train": k,
            "train_score": round(train_score, 4),
            "test_score": round(test_score, 4),
        })

    return results


def compute_nri_idi(
    y_true: "numpy.ndarray[Any, Any]",
    y_score_old: "numpy.ndarray[Any, Any]",
    y_score_new: "numpy.ndarray[Any, Any]",
    threshold: float = 0.5,
) -> Dict[str, float]:
    """Compute Net Reclassification Improvement (NRI) and
    Integrated Discrimination Improvement (IDI).

    Args:
        y_true: Binary ground truth.
        y_score_old: Predicted probabilities from reference model.
        y_score_new: Predicted probabilities from new model.
        threshold: Classification threshold for categorical NRI.

    Returns:
        Dict with categorical_nri, continuous_nri, idi, event_nri, nonevent_nri.

    References:
        Pencina MJ et al. Stat Med. 2008;27:157-172.
        Pencina MJ et al. Stat Med. 2011;30:11-21.
    """
    import numpy as np

    y_t = np.asarray(y_true, dtype=float)
    p_old = np.asarray(y_score_old, dtype=float)
    p_new = np.asarray(y_score_new, dtype=float)

    events = y_t == 1
    nonevents = y_t == 0

    n_events = float(events.sum())
    n_nonevents = float(nonevents.sum())
    if n_events == 0 or n_nonevents == 0:
        return {
            "categorical_nri": None,
            "continuous_nri": None,
            "idi": None,
            "event_nri": None,
            "nonevent_nri": None,
            "error": "NRI/IDI undefined: requires both events and non-events.",
        }

    # Categorical NRI (based on threshold)
    old_class = (p_old >= threshold).astype(int)
    new_class = (p_new >= threshold).astype(int)

    up_events = float(((new_class > old_class) & events).sum())
    down_events = float(((new_class < old_class) & events).sum())
    up_nonevents = float(((new_class > old_class) & nonevents).sum())
    down_nonevents = float(((new_class < old_class) & nonevents).sum())

    event_nri = (up_events - down_events) / n_events if n_events > 0 else 0.0
    nonevent_nri = (down_nonevents - up_nonevents) / n_nonevents if n_nonevents > 0 else 0.0
    cat_nri = event_nri + nonevent_nri

    # Continuous NRI (Pencina 2011: proportion among events/nonevents, not full sample)
    cont_event_nri = float((p_new[events] > p_old[events]).mean() - (p_new[events] < p_old[events]).mean()) if n_events > 0 else 0.0
    cont_nonevent_nri = float((p_new[nonevents] < p_old[nonevents]).mean() - (p_new[nonevents] > p_old[nonevents]).mean()) if n_nonevents > 0 else 0.0
    cont_nri = cont_event_nri + cont_nonevent_nri

    # IDI
    idi = float((p_new[events].mean() - p_old[events].mean()) - (p_new[nonevents].mean() - p_old[nonevents].mean()))

    return {
        "categorical_nri": round(cat_nri, 4),
        "continuous_nri": round(cont_nri, 4),
        "idi": round(idi, 4),
        "event_nri": round(event_nri, 4),
        "nonevent_nri": round(nonevent_nri, 4),
    }


# ---------------------------------------------------------------------------
# Multicollinearity Detection (VIF)
# Ref: PMC4888898, PMC11093476 — VIF > 5 investigate, > 10 critical
# ---------------------------------------------------------------------------



# ═══════════════════════════════════════════════════════════════
# Feature Analysis (VIF, Nonlinearity, Ablation)
# ═══════════════════════════════════════════════════════════════

def compute_vif(
    X: Any,
    feature_names: Optional[list] = None,
    threshold_warn: float = 5.0,
    threshold_critical: float = 10.0,
) -> Dict[str, Any]:
    """Compute Variance Inflation Factor for each feature.

    VIF_j = 1 / (1 - R²_j) where R²_j is from regressing feature j on all others.

    Args:
        X: Feature matrix (numpy array or DataFrame). Must be imputed (no NaN).
        feature_names: Column names. Inferred from DataFrame if not provided.
        threshold_warn: VIF above this triggers warning (default 5.0).
        threshold_critical: VIF above this triggers critical flag (default 10.0).

    Returns:
        Dict with per_feature VIF table, flagged features, and summary.

    References:
        PMC4888898 — Multicollinearity in epidemiologic studies.
        PMC11093476 — Stepwise regression is inappropriate for multicollinearity.
    """
    import numpy as np

    X_arr = np.asarray(X, dtype=float)
    n, p = X_arr.shape

    if feature_names is None:
        if hasattr(X, "columns"):
            feature_names = list(X.columns)
        else:
            feature_names = [f"feature_{i}" for i in range(p)]

    if n < p + 1:
        return {
            "error": f"Cannot compute VIF: n={n} < p+1={p+1}. More features than samples.",
            "n_features": p,
            "n_samples": n,
        }

    # Center features for numerical stability
    X_centered = X_arr - X_arr.mean(axis=0)

    vif_values = []
    for j in range(p):
        y_j = X_centered[:, j]
        X_others = np.delete(X_centered, j, axis=1)

        # OLS: R² = 1 - SS_res / SS_tot
        try:
            coef, residuals, _, _ = np.linalg.lstsq(X_others, y_j, rcond=None)
            y_pred = X_others @ coef
            ss_res = float(np.sum((y_j - y_pred) ** 2))
            ss_tot = float(np.sum((y_j - y_j.mean()) ** 2))
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            vif = 1.0 / (1.0 - r2) if r2 < 1.0 else float("inf")
        except Exception as exc:
            print(f"[compute_vif] feature={feature_names[j]}: {exc}", file=sys.stderr)
            vif = float("nan")

        vif_values.append({
            "feature": feature_names[j],
            "vif": round(vif, 2) if np.isfinite(vif) else None,
            "flag": "critical" if vif > threshold_critical else ("warn" if vif > threshold_warn else "ok"),
        })

    # Sort by VIF descending
    vif_values.sort(key=lambda x: -(x["vif"] or 0))

    warn_features = [v["feature"] for v in vif_values if v["flag"] == "warn"]
    critical_features = [v["feature"] for v in vif_values if v["flag"] == "critical"]

    return {
        "vif_table": vif_values,
        "n_features": p,
        "warn_features": warn_features,
        "critical_features": critical_features,
        "max_vif": vif_values[0]["vif"] if vif_values else None,
        "threshold_warn": threshold_warn,
        "threshold_critical": threshold_critical,
    }


# ---------------------------------------------------------------------------
# Nonlinearity Check for Continuous Predictors
# Ref: Harrell 2015 Ch.2, Austin 2022 (Stat Med)
# ---------------------------------------------------------------------------

def check_nonlinearity(
    X: Any,
    y: Any,
    feature_names: Optional[list] = None,
    n_knots: int = 4,
    p_threshold: float = 0.05,
    fdr_method: Optional[str] = "fdr_bh",
) -> list:
    """Test linearity assumption for continuous predictors using likelihood ratio.

    For each continuous feature, compares a linear logistic model vs a model
    with natural cubic spline terms. Significant LR test → nonlinear relationship.

    Multiple testing correction: When testing N features, the false positive rate
    inflates (e.g., 20 features at α=0.05 → expect 1 false positive). By default,
    Benjamini-Hochberg FDR correction is applied to control the false discovery rate.

    Args:
        X: Feature matrix.
        y: Binary target.
        feature_names: Column names.
        n_knots: Number of knots for spline (default 4 → 3 df nonlinear).
        p_threshold: P-value threshold for flagging nonlinearity.
        fdr_method: Multiple testing correction method. Options:
            - "fdr_bh" (default): Benjamini-Hochberg FDR correction
            - "holm": Holm-Bonferroni (controls FWER, more conservative)
            - "bonferroni": Bonferroni (most conservative)
            - None: No correction (use raw p-values, NOT recommended for >5 features)

    Returns:
        List of dicts with feature, lr_chi2, p_value, p_value_adjusted,
        nonlinear flag (based on adjusted p-value when correction applied).

    References:
        Harrell FE. Regression Modeling Strategies. 2nd ed. 2015. Ch. 2.
        Benjamini Y, Hochberg Y. Controlling the FDR. JRSS-B. 1995;57(1):289-300.
    """
    import numpy as np
    from scipy.stats import chi2

    X_arr = np.asarray(X, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    n, p = X_arr.shape

    if feature_names is None:
        if hasattr(X, "columns"):
            feature_names = list(X.columns)
        else:
            feature_names = [f"feature_{i}" for i in range(p)]

    results = []
    for j in range(p):
        x_j = X_arr[:, j]

        # Skip constant or near-constant features
        if np.std(x_j) < 1e-10:
            results.append({
                "feature": feature_names[j],
                "lr_chi2": None,
                "p_value": None,
                "nonlinear": False,
                "note": "constant feature",
            })
            continue

        # Skip low-cardinality (categorical) — nonlinearity test only for continuous
        if len(np.unique(x_j[~np.isnan(x_j)])) < 10:
            results.append({
                "feature": feature_names[j],
                "lr_chi2": None,
                "p_value": None,
                "nonlinear": False,
                "note": "low cardinality (skip)",
            })
            continue

        # Fit linear logistic: logit(y) ~ β₀ + β₁·x
        # Unpenalised MLE required for valid LR test likelihoods.
        from sklearn.linear_model import LogisticRegression
        import sklearn as _sk_nl
        _sk_nl_ver = tuple(int(x) for x in _sk_nl.__version__.split(".")[:2])
        _lr_kwargs: Dict[str, Any] = {"max_iter": 500, "solver": "lbfgs"}
        if _sk_nl_ver >= (1, 8):
            _lr_kwargs["C"] = float("inf")
        elif _sk_nl_ver >= (1, 2):
            _lr_kwargs["penalty"] = None
        else:
            _lr_kwargs["C"] = 1e10
        try:
            lr_linear = LogisticRegression(**_lr_kwargs)
            lr_linear.fit(x_j.reshape(-1, 1), y_arr)
            ll_linear = float(np.sum(
                y_arr * np.log(np.clip(lr_linear.predict_proba(x_j.reshape(-1, 1))[:, 1], 1e-10, 1 - 1e-10))
                + (1 - y_arr) * np.log(np.clip(1 - lr_linear.predict_proba(x_j.reshape(-1, 1))[:, 1], 1e-10, 1 - 1e-10))
            ))
        except Exception:
            results.append({
                "feature": feature_names[j],
                "lr_chi2": None,
                "p_value": None,
                "nonlinear": False,
                "note": "linear fit failed",
            })
            continue

        # Fit spline logistic: add natural cubic spline basis functions
        try:
            knots = np.percentile(x_j[~np.isnan(x_j)], np.linspace(5, 95, n_knots))
            # Natural cubic spline basis: (x - knot)³_+ for each interior knot
            spline_cols = [x_j.reshape(-1, 1)]
            for k in knots[1:-1]:  # interior knots only
                term = np.maximum(x_j - k, 0) ** 3
                spline_cols.append(term.reshape(-1, 1))
            X_spline = np.hstack(spline_cols)

            lr_spline = LogisticRegression(**_lr_kwargs)
            lr_spline.fit(X_spline, y_arr)
            ll_spline = float(np.sum(
                y_arr * np.log(np.clip(lr_spline.predict_proba(X_spline)[:, 1], 1e-10, 1 - 1e-10))
                + (1 - y_arr) * np.log(np.clip(1 - lr_spline.predict_proba(X_spline)[:, 1], 1e-10, 1 - 1e-10))
            ))
        except Exception:
            results.append({
                "feature": feature_names[j],
                "lr_chi2": None,
                "p_value": None,
                "nonlinear": False,
                "note": "spline fit failed",
            })
            continue

        # Likelihood ratio test: 2 * (ll_spline - ll_linear) ~ chi²(df = n_interior_knots)
        lr_stat = 2.0 * (ll_spline - ll_linear)
        lr_stat = max(lr_stat, 0.0)
        df = max(len(knots) - 2, 1)
        p_val = float(1.0 - chi2.cdf(lr_stat, df))

        results.append({
            "feature": feature_names[j],
            "lr_chi2": round(lr_stat, 4),
            "p_value": round(p_val, 4),
            "df": df,
            "nonlinear": False,  # will be set after FDR correction
        })

    # ── Multiple testing correction ──
    # Collect raw p-values from features that were actually tested
    tested_indices = [i for i, r in enumerate(results) if r["p_value"] is not None]
    raw_pvals = [results[i]["p_value"] for i in tested_indices]

    if raw_pvals and fdr_method is not None and len(raw_pvals) > 1:
        try:
            from statsmodels.stats.multitest import multipletests
            reject, pvals_adj, _, _ = multipletests(raw_pvals, alpha=p_threshold, method=fdr_method)
            for idx, ti in enumerate(tested_indices):
                results[ti]["p_value_adjusted"] = round(float(pvals_adj[idx]), 4)
                results[ti]["nonlinear"] = bool(reject[idx])
                results[ti]["fdr_method"] = fdr_method
        except ImportError:
            # statsmodels not available — fall back to raw p-values with warning
            for ti in tested_indices:
                results[ti]["p_value_adjusted"] = results[ti]["p_value"]
                results[ti]["nonlinear"] = results[ti]["p_value"] < p_threshold
                results[ti]["fdr_method"] = "none (statsmodels not installed)"
    else:
        # Single test or no correction requested — use raw p-values
        for ti in tested_indices:
            results[ti]["p_value_adjusted"] = results[ti]["p_value"]
            results[ti]["nonlinear"] = results[ti]["p_value"] < p_threshold
            results[ti]["fdr_method"] = "none" if fdr_method is None else "single_test"

    return results


# ---------------------------------------------------------------------------
# Calibration per-bin Bootstrap CI (NC Reviewer #2 Comment 8)
# ---------------------------------------------------------------------------

def calibration_bin_ci(
    y_true: Any,
    y_score: Any,
    n_bins: int = 10,
    n_bootstrap: int = 1000,
    ci_level: float = 0.95,
    seed: int = 42,
) -> list:
    """Bootstrap 95% CI for calibration per risk-decile bin.

    For each bin (risk centile), compute fraction_positive with CI.
    Reviewers require these for calibration plots (NC Reviewer #2).

    Returns list of dicts per bin with mean_predicted, fraction_positive,
    ci_lower, ci_upper, n.
    """
    import numpy as np

    y_t = np.asarray(y_true, dtype=float)
    y_s = np.asarray(y_score, dtype=float)
    rng = np.random.default_rng(seed)

    bin_edges = np.linspace(0, 1, n_bins + 1)
    alpha = 1 - ci_level
    results = []

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (y_s >= lo) & (y_s < hi) if i < n_bins - 1 else (y_s >= lo) & (y_s <= hi)
        yt_bin = y_t[mask]
        ys_bin = y_s[mask]
        n_bin = len(yt_bin)

        if n_bin < 2:
            results.append({
                "bin": i, "bin_range": f"{lo:.2f}-{hi:.2f}",
                "n": n_bin, "mean_predicted": round(float(ys_bin.mean()), 4) if n_bin > 0 else None,
                "fraction_positive": round(float(yt_bin.mean()), 4) if n_bin > 0 else None,
                "ci_lower": None, "ci_upper": None,
            })
            continue

        boot_fracs = []
        for _ in range(n_bootstrap):
            idx = rng.choice(n_bin, n_bin, replace=True)
            boot_fracs.append(float(yt_bin[idx].mean()))

        ci_lo = float(np.percentile(boot_fracs, 100 * alpha / 2))
        ci_hi = float(np.percentile(boot_fracs, 100 * (1 - alpha / 2)))

        results.append({
            "bin": i, "bin_range": f"{lo:.2f}-{hi:.2f}",
            "n": n_bin,
            "mean_predicted": round(float(ys_bin.mean()), 4),
            "fraction_positive": round(float(yt_bin.mean()), 4),
            "ci_lower": round(ci_lo, 4),
            "ci_upper": round(ci_hi, 4),
        })

    return results


# ---------------------------------------------------------------------------
# Model Coefficients Export (NC Reviewer #1 Comment 4)
# ---------------------------------------------------------------------------

def export_model_coefficients(
    estimator: Any,
    feature_names: list,
) -> Optional[list]:
    """Export model coefficients or feature importances as a table.

    Works for: LogisticRegression (coef_), LinearSVM, tree-based (.feature_importances_).
    Returns list of dicts with feature, coefficient/importance, rank.
    """
    import numpy as np
    from sklearn.pipeline import Pipeline

    clf = estimator
    if isinstance(estimator, Pipeline):
        steps = list(estimator.named_steps.keys())
        clf = estimator.named_steps[steps[-1]]

    coefs = None
    coef_type = "coefficient"

    if hasattr(clf, "coef_"):
        coefs = clf.coef_.ravel()
        coef_type = "coefficient"
    elif hasattr(clf, "feature_importances_"):
        coefs = clf.feature_importances_
        coef_type = "importance"
    else:
        return None

    if len(coefs) != len(feature_names):
        return None

    results = []
    order = np.argsort(-np.abs(coefs))
    for rank, idx in enumerate(order, 1):
        results.append({
            "rank": rank,
            "feature": feature_names[idx],
            coef_type: round(float(coefs[idx]), 6),
            f"abs_{coef_type}": round(float(abs(coefs[idx])), 6),
        })

    return results


# ---------------------------------------------------------------------------
# Rubin's Rules for Multiple Imputation (NC Reviewer #2 Comment 7)
# ---------------------------------------------------------------------------

def rubins_rules_combine(
    estimates: list,
    variances: Optional[list] = None,
) -> Dict[str, float]:
    """Combine estimates across multiple imputations using Rubin's rules.

    Args:
        estimates: List of point estimates from each imputed dataset.
        variances: List of within-imputation variances (optional).
                   If None, only pooled mean and between-imputation variance reported.

    Returns:
        Dict with pooled_estimate, between_variance, within_variance,
        total_variance, and degrees_of_freedom.

    References:
        Rubin DB. Multiple Imputation for Nonresponse in Surveys. Wiley; 1987.
    """
    import numpy as np

    ests = np.asarray(estimates, dtype=float)
    m = len(ests)

    if m < 2:
        return {"pooled_estimate": float(ests[0]) if m == 1 else None, "error": "need >=2 imputations"}

    # Pooled estimate: mean across imputations
    q_bar = float(ests.mean())

    # Between-imputation variance
    b = float(np.var(ests, ddof=1))

    if variances is not None:
        vars_arr = np.asarray(variances, dtype=float)
        # Within-imputation variance: mean of variances
        u_bar = float(vars_arr.mean())
        # Total variance: Rubin's formula
        t = u_bar + (1 + 1 / m) * b
        # Degrees of freedom (Barnard-Rubin)
        if b > 0 and u_bar > 0:
            r = (1 + 1 / m) * b / u_bar
            df = (m - 1) * (1 + 1 / r) ** 2
        else:
            df = float("inf")
    else:
        u_bar = None
        t = (1 + 1 / m) * b
        df = m - 1

    return {
        "pooled_estimate": round(q_bar, 6),
        "between_variance": round(b, 6),
        "within_variance": round(u_bar, 6) if u_bar is not None else None,
        "total_variance": round(t, 6),
        "total_se": round(float(np.sqrt(t)), 6),
        "degrees_of_freedom": round(df, 2),
        "n_imputations": m,
    }


# ---------------------------------------------------------------------------
# Baseline Comparisons (Nature ML Checklist 4D)
# ---------------------------------------------------------------------------

def baseline_comparisons(
    y_true: Any,
    y_score: Any,
    y_pred: Any,
) -> Dict[str, Any]:
    """Compare model performance against trivial baselines.

    Baselines:
      1. Prevalence model: always predicts base rate P(y=1)
      2. Random classifier: coin flip at base rate
      3. All-positive: predicts everyone as positive
      4. All-negative: predicts everyone as negative

    Returns dict with model metrics and each baseline's metrics,
    plus improvement deltas.

    Required by Nature Portfolio ML Checklist Item 4D.
    """
    import numpy as np
    from sklearn.metrics import (
        average_precision_score, brier_score_loss, roc_auc_score,
    )

    y_t = np.asarray(y_true, dtype=float)
    y_s = np.asarray(y_score, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    n = len(y_t)
    prev = float(y_t.mean())

    # Model performance (use pr_auc/roc_auc consistently with metric_panel)
    model = {
        "roc_auc": round(float(roc_auc_score(y_t, y_s)), 4),
        "pr_auc": round(float(average_precision_score(y_t, y_s)), 4),
        "brier": round(float(brier_score_loss(y_t, y_s)), 4),
    }

    # Prevalence baseline: predict P(y=1) for everyone
    prev_scores = np.full(n, prev)
    prevalence_baseline = {
        "roc_auc": 0.5,  # by definition
        "pr_auc": round(prev, 4),  # AP = prevalence for constant predictions
        "brier": round(float(brier_score_loss(y_t, prev_scores)), 4),
    }

    # All-positive
    all_pos = {
        "sensitivity": 1.0, "specificity": 0.0,
        "ppv": round(prev, 4), "npv": None,
    }

    # All-negative
    all_neg = {
        "sensitivity": 0.0, "specificity": 1.0,
        "ppv": None, "npv": round(1 - prev, 4),
    }

    # Improvements over prevalence baseline
    improvement = {
        "roc_auc_over_random": round(model["roc_auc"] - 0.5, 4),
        "pr_auc_over_prevalence": round(model["pr_auc"] - prev, 4),
        "brier_skill_score": round(
            1 - model["brier"] / prevalence_baseline["brier"], 4
        ) if prevalence_baseline["brier"] > 0 else None,
    }

    return {
        "model": model,
        "prevalence_baseline": prevalence_baseline,
        "all_positive": all_pos,
        "all_negative": all_neg,
        "improvement_over_baseline": improvement,
        "prevalence": round(prev, 4),
    }


# ---------------------------------------------------------------------------
# Feature Ablation Study (Nature ML Checklist 4F)
# ---------------------------------------------------------------------------

def feature_ablation(
    estimator: Any,
    X_train: Any,
    y_train: Any,
    X_test: Any,
    y_test: Any,
    feature_names: list,
    top_n: int = 10,
    metric: str = "pr_auc",
    seed: int = 42,
) -> list:
    """Ablation study: measure performance drop when removing top features.

    For each of the top-N most important features (by permutation importance
    or SHAP ranking), remove it and retrain, measuring the performance delta.

    Args:
        estimator: Fitted estimator to clone.
        X_train, y_train, X_test, y_test: Data arrays.
        feature_names: Column names matching X columns.
        top_n: Number of features to ablate (default 10).
        metric: Performance metric.
        seed: Random seed.

    Returns:
        List of dicts with feature, score_without, score_full, delta.

    Required by Nature Portfolio ML Checklist Item 4F.
    """
    import numpy as np
    from sklearn.base import clone
    from sklearn.metrics import average_precision_score, roc_auc_score

    X_tr = np.asarray(X_train, dtype=float)
    X_te = np.asarray(X_test, dtype=float)
    y_tr = np.asarray(y_train, dtype=int)
    y_te = np.asarray(y_test, dtype=int)

    score_fn = average_precision_score if metric == "pr_auc" else roc_auc_score

    # Full model score
    try:
        full_est = clone(estimator)
        full_est.fit(X_tr, y_tr)
        full_score = float(score_fn(y_te, full_est.predict_proba(X_te)[:, 1]))
    except Exception as exc:
        print(f"[feature_ablation] full model fit failed: {exc}", file=sys.stderr)
        return []

    # Permutation importance to determine ablation order
    rng = np.random.default_rng(seed)
    importances = []
    for j in range(min(len(feature_names), X_te.shape[1])):
        X_perm = X_te.copy()
        X_perm[:, j] = rng.permutation(X_perm[:, j])
        try:
            perm_score = float(score_fn(y_te, full_est.predict_proba(X_perm)[:, 1]))
            importances.append((j, full_score - perm_score))
        except Exception as exc:
            print(f"[feature_ablation] permutation j={j}: {exc}", file=sys.stderr)
            importances.append((j, 0.0))

    # Sort by importance descending
    importances.sort(key=lambda x: -x[1])

    results = []
    for rank, (j, imp) in enumerate(importances[:top_n]):
        # Remove feature j and retrain
        mask = np.ones(X_tr.shape[1], dtype=bool)
        mask[j] = False
        try:
            abl_est = clone(estimator)
            abl_est.fit(X_tr[:, mask], y_tr)
            abl_score = float(score_fn(y_te, abl_est.predict_proba(X_te[:, mask])[:, 1]))
        except Exception as exc:
            print(f"[feature_ablation] ablate {feature_names[j] if j < len(feature_names) else j}: {exc}", file=sys.stderr)
            abl_score = None

        results.append({
            "rank": rank + 1,
            "feature": feature_names[j] if j < len(feature_names) else f"feature_{j}",
            "permutation_importance": round(imp, 4),
            "score_full": round(full_score, 4),
            "score_without": round(abl_score, 4) if abl_score is not None else None,
            "delta": round(full_score - abl_score, 4) if abl_score is not None else None,
        })

    return results


# ---------------------------------------------------------------------------
# Computational Resource Tracking (Nature ML Checklist 5A/5B)
# ---------------------------------------------------------------------------

def compute_resource_report(
    start_time: float,
    end_time: float,
    model_name: str = "",
    n_train: int = 0,
    n_features: int = 0,
) -> Dict[str, Any]:
    """Generate computational resource report.

    Args:
        start_time: time.time() at start.
        end_time: time.time() at end.
        model_name: Model identifier.
        n_train: Training samples.
        n_features: Feature count.

    Returns:
        Dict with wall_time, hardware info, and dataset size.

    Required by Nature Portfolio ML Checklist Items 5A and 5B.
    """
    import platform
    import os

    wall_seconds = end_time - start_time

    return {
        "model": model_name,
        "wall_time_seconds": round(wall_seconds, 2),
        "wall_time_human": f"{int(wall_seconds // 60)}m {int(wall_seconds % 60)}s",
        "n_train_samples": n_train,
        "n_features": n_features,
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(),
            "python_version": platform.python_version(),
        },
    }


# ---------------------------------------------------------------------------
# Bootstrap Optimism Correction (Steyerberg 2019 Ch.17)
# ---------------------------------------------------------------------------

def bootstrap_optimism_correction(
    estimator: Any,
    X_train: Any,
    y_train: Any,
    n_bootstrap: int = 200,
    metric: str = "pr_auc",
    seed: int = 42,
) -> Dict[str, Any]:
    """Bootstrap optimism correction for internal validation.

    Estimates how much the apparent (training) performance overestimates
    the true performance. The optimism-corrected estimate is:
      corrected = apparent - mean(optimism)

    Algorithm (Steyerberg 2019):
      For b = 1..B:
        1. Bootstrap resample training data (with replacement)
        2. Fit model on bootstrap sample → compute score on bootstrap = S_boot
        3. Apply bootstrap model to ORIGINAL training data → score = S_orig
        4. Optimism_b = S_boot - S_orig
      Optimism = mean(Optimism_b)
      Corrected = Apparent - Optimism

    Args:
        estimator: Unfitted estimator (cloned per bootstrap).
        X_train, y_train: Training data.
        n_bootstrap: Number of bootstrap resamples (≥100, default 200).
        metric: 'pr_auc' or 'roc_auc'.
        seed: Random seed.

    Returns:
        Dict with apparent, mean_optimism, corrected, ci_optimism, per_bootstrap.

    References:
        Steyerberg EW. Clinical Prediction Models. 2nd ed. 2019. Ch.17.
        Harrell FE. Regression Modeling Strategies. 2nd ed. 2015. Ch.5.
    """
    import numpy as np
    from sklearn.base import clone
    from sklearn.metrics import average_precision_score, roc_auc_score

    X = np.asarray(X_train, dtype=float)
    y = np.asarray(y_train, dtype=int)
    n = X.shape[0]
    rng = np.random.default_rng(seed)
    score_fn = average_precision_score if metric == "pr_auc" else roc_auc_score

    # Apparent performance (train on full, evaluate on full)
    try:
        full_est = clone(estimator)
        full_est.fit(X, y)
        apparent = float(score_fn(y, full_est.predict_proba(X)[:, 1]))
    except Exception:
        return {"error": "apparent performance computation failed"}

    optimisms = []
    for b in range(n_bootstrap):
        boot_idx = rng.choice(n, n, replace=True)
        X_boot, y_boot = X[boot_idx], y[boot_idx]

        if len(np.unique(y_boot)) < 2:
            continue

        try:
            est = clone(estimator)
            est.fit(X_boot, y_boot)
            s_boot = float(score_fn(y_boot, est.predict_proba(X_boot)[:, 1]))
            s_orig = float(score_fn(y, est.predict_proba(X)[:, 1]))
            optimisms.append(s_boot - s_orig)
        except Exception as exc:
            print(f"[bootstrap_optimism] bootstrap {b}: {exc}", file=sys.stderr)
            continue

    if len(optimisms) < 10:
        return {"error": f"only {len(optimisms)} valid bootstrap samples (need ≥10)"}

    opt_arr = np.array(optimisms)
    mean_opt = float(opt_arr.mean())
    corrected = apparent - mean_opt

    return {
        "apparent": round(apparent, 4),
        "mean_optimism": round(mean_opt, 4),
        "corrected": round(corrected, 4),
        "optimism_std": round(float(opt_arr.std()), 4),
        "optimism_ci_95": [
            round(float(np.percentile(opt_arr, 2.5)), 4),
            round(float(np.percentile(opt_arr, 97.5)), 4),
        ],
        "n_valid_bootstrap": len(optimisms),
        "metric": metric,
        "shrinkage_factor": round(corrected / apparent, 4) if apparent > 0 else None,
    }


# ---------------------------------------------------------------------------
# Robustness Stress Test (outlier, noise, dropout)
# ---------------------------------------------------------------------------



# ═══════════════════════════════════════════════════════════════
# Robustness & Stress Testing
# ═══════════════════════════════════════════════════════════════

def robustness_stress_test(
    estimator: Any,
    X_train: Any,
    y_train: Any,
    X_test: Any,
    y_test: Any,
    metric: str = "pr_auc",
    seed: int = 42,
    *,
    outlier_fraction: float = 0.05,
    outlier_sigma: float = 3.0,
    noise_fraction: float = 0.1,
    dropout_fraction: float = 0.1,
    top_n_features: int = 5,
    robustness_threshold_pct: float = 5.0,
) -> Dict[str, Any]:
    """Systematic robustness check: how stable is the model under perturbation?

    Tests 4 types of perturbation on the TEST set:
      1. Outlier injection: replace *outlier_fraction* of values with
         *outlier_sigma* × std extremes
      2. Gaussian noise: add N(0, *noise_fraction* × std) to numeric features
      3. Sample dropout: randomly drop *dropout_fraction* of test rows
      4. Feature dropout: zero out one feature at a time (top-N by variance)

    All perturbations are applied to TEST DATA ONLY — training is untouched.

    Args:
        estimator: Fitted sklearn estimator.
        X_train, y_train: Training data (only for feature importance ordering).
        X_test, y_test: Test data (perturbations applied here).
        metric: Performance metric.
        seed: Random seed.
        outlier_fraction: Fraction of test values to replace (default 0.05).
        outlier_sigma: Outlier magnitude in std units (default 3.0).
        noise_fraction: Gaussian noise magnitude as fraction of feature std
            (default 0.1).
        dropout_fraction: Fraction of test rows to drop (default 0.1).
        top_n_features: Number of top-variance features for zeroing test
            (default 5).
        robustness_threshold_pct: Max acceptable relative performance drop
            percent (default 5.0). Below this → "robust".

    Returns:
        Dict with baseline_score, perturbation results, and robustness verdict.

    Note:
        This function NEVER modifies training data or removes outliers.
        It only tests whether the model's predictions are sensitive to
        data perturbations — the decision to act is the researcher's.

    References:
        Perturbation fractions follow Schulam & Saria (AISTATS 2019) recommendations
        for stress-testing clinical prediction models. Users should run multiple
        perturbation levels and report the sensitivity curve rather than relying
        on a single pass/fail threshold.
    """
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score

    rng = np.random.default_rng(seed)
    X_te = np.asarray(X_test, dtype=float)
    y_te = np.asarray(y_test, dtype=int)

    if X_te.shape[0] == 0 or y_te.size == 0:
        return {"error": "empty_test_set", "robust": False, "verdict": "error"}
    if len(np.unique(y_te)) < 2 and metric != "pr_auc":
        # roc_auc_score requires both classes; pr_auc works with single class
        return {"error": "single_class_test_set", "robust": False, "verdict": "error"}

    score_fn = average_precision_score if metric == "pr_auc" else roc_auc_score

    # Baseline
    try:
        baseline = float(score_fn(y_te, estimator.predict_proba(X_te)[:, 1]))
    except Exception:
        return {"error": "baseline prediction failed"}

    results = {"baseline": round(baseline, 4), "perturbations": []}

    # 1. Outlier injection
    X_outlier = X_te.copy()
    n_inject = max(1, int(X_te.size * outlier_fraction))
    flat_idx = rng.choice(X_te.size, n_inject, replace=False)
    for idx in flat_idx:
        r, c = divmod(idx, X_te.shape[1])
        col_std = float(np.std(X_te[:, c]))
        X_outlier.flat[idx] = float(np.mean(X_te[:, c])) + outlier_sigma * col_std * rng.choice([-1, 1])
    try:
        s = float(score_fn(y_te, estimator.predict_proba(X_outlier)[:, 1]))
        results["perturbations"].append({
            "type": f"outlier_injection_{int(outlier_fraction*100)}pct", "score": round(s, 4),
            "delta": round(s - baseline, 4), "relative_drop_pct": round((baseline - s) / max(baseline, 1e-10) * 100, 2),
        })
    except Exception as exc:
        print(f"[robustness] outlier_injection: {exc}", file=sys.stderr)
        results["perturbations"].append({"type": f"outlier_injection_{int(outlier_fraction*100)}pct", "score": None})

    # 2. Gaussian noise
    X_noisy = X_te.copy()
    for c in range(X_te.shape[1]):
        noise = rng.normal(0, max(float(np.std(X_te[:, c])) * noise_fraction, 1e-6), X_te.shape[0])
        X_noisy[:, c] += noise
    try:
        s = float(score_fn(y_te, estimator.predict_proba(X_noisy)[:, 1]))
        results["perturbations"].append({
            "type": f"gaussian_noise_{int(noise_fraction*100)}pct_std", "score": round(s, 4),
            "delta": round(s - baseline, 4), "relative_drop_pct": round((baseline - s) / max(baseline, 1e-10) * 100, 2),
        })
    except Exception as exc:
        print(f"[robustness] gaussian_noise: {exc}", file=sys.stderr)
        results["perturbations"].append({"type": f"gaussian_noise_{int(noise_fraction*100)}pct_std", "score": None})

    # 3. Sample dropout
    n_keep = min(X_te.shape[0], max(10, int(X_te.shape[0] * (1.0 - dropout_fraction))))
    keep_idx = rng.choice(X_te.shape[0], n_keep, replace=False)
    try:
        s = float(score_fn(y_te[keep_idx], estimator.predict_proba(X_te[keep_idx])[:, 1]))
        results["perturbations"].append({
            "type": f"sample_dropout_{int(dropout_fraction*100)}pct", "score": round(s, 4),
            "delta": round(s - baseline, 4), "relative_drop_pct": round((baseline - s) / max(baseline, 1e-10) * 100, 2),
        })
    except Exception as exc:
        print(f"[robustness] sample_dropout: {exc}", file=sys.stderr)
        results["perturbations"].append({"type": f"sample_dropout_{int(dropout_fraction*100)}pct", "score": None})

    # 4. Feature zeroing (zero out top-N features by variance)
    feat_var = np.var(X_te, axis=0)
    top_n = np.argsort(-feat_var)[:min(top_n_features, X_te.shape[1])]
    feat_zero_results = []
    for fi in top_n:
        X_zero = X_te.copy()
        X_zero[:, fi] = 0.0
        try:
            s = float(score_fn(y_te, estimator.predict_proba(X_zero)[:, 1]))
            feat_zero_results.append({
                "feature_index": int(fi), "score": round(s, 4),
                "delta": round(s - baseline, 4),
            })
        except Exception as exc:
            print(f"[robustness] feature_zero fi={fi}: {exc}", file=sys.stderr)
    results["perturbations"].append({
        "type": f"feature_zeroing_top{top_n_features}", "per_feature": feat_zero_results,
        "max_drop": round(min(f["delta"] for f in feat_zero_results), 4) if feat_zero_results else None,
    })

    # Verdict
    drops = [p.get("relative_drop_pct", 0) for p in results["perturbations"] if isinstance(p.get("relative_drop_pct"), (int, float))]
    max_drop = max(drops) if drops else 0
    results["max_relative_drop_pct"] = round(max_drop, 2)
    results["robust"] = max_drop < robustness_threshold_pct
    results["verdict"] = "robust" if results["robust"] else "sensitive"

    # Actionable guidance
    if not results["robust"]:
        guidance = []
        for p in results["perturbations"]:
            drop = p.get("relative_drop_pct", 0)
            if isinstance(drop, (int, float)) and drop > 5:
                ptype = p.get("type", "")
                if "outlier" in ptype:
                    guidance.append(
                        "Model sensitive to outliers → consider: "
                        "(1) verify no data entry errors in extreme values, "
                        "(2) use tree-based models (more robust to outliers than LR/SVM), "
                        "(3) add more training data from extreme-value patients."
                    )
                elif "noise" in ptype:
                    guidance.append(
                        "Model sensitive to feature noise → consider: "
                        "(1) standardize features before training, "
                        "(2) apply stronger regularization (increase L2 penalty), "
                        "(3) reduce feature count (feature selection may help)."
                    )
                elif "dropout" in ptype:
                    guidance.append(
                        "Model sensitive to sample dropout → consider: "
                        "(1) increase training data, "
                        "(2) use bootstrap aggregation (bagging), "
                        "(3) check for influential observations."
                    )
        results["guidance"] = guidance if guidance else ["Review perturbation results for specific vulnerabilities."]
    else:
        results["guidance"] = ["Model is robust to standard perturbations. No action needed."]

    return results


# ---------------------------------------------------------------------------
# Module 1: MNAR Sensitivity Analysis (δ-adjustment + tipping point)
# Ref: Cro S et al. Stat Med 2020;39(21):2815-2842; doi:10.1002/sim.8569
# ---------------------------------------------------------------------------

def mnar_sensitivity_analysis(
    estimator: Any,
    X_train: Any,
    y_train: Any,
    X_test: Any,
    y_test: Any,
    missing_mask_train: Any,
    missing_mask_test: Any,
    deltas: Optional[list] = None,
    metric: str = "pr_auc",
    seed: int = 42,
) -> Dict[str, Any]:
    """MNAR sensitivity analysis via δ-adjustment on imputed values.

    Shifts imputed values by δ (simulating MNAR departure from MAR) and
    re-evaluates model performance. Reports tipping point where conclusion
    changes (AUROC drops below baseline prevalence model).

    Args:
        estimator: Fitted sklearn estimator (will be cloned and re-fit).
        X_train, y_train: Training data (already imputed under MAR).
        X_test, y_test: Test data (already imputed under MAR).
        missing_mask_train: Boolean mask (True=was missing, same shape as X).
        missing_mask_test: Same for test.
        deltas: List of δ values to test. Default: [-0.5, -0.2, -0.1, 0, 0.1, 0.2, 0.5].
        metric: Primary metric for tipping point detection.
        seed: Random seed.

    Returns:
        Dict with delta_results (list of {delta, metric_value}),
        tipping_point (smallest |δ| that flips conclusion), and baseline.

    References:
        Cro S et al. Stat Med. 2020;39(21):2815-2834.
        PMC10481859 — MI-based sensitivity analysis for MNAR.
    """
    import numpy as np
    from sklearn.base import clone
    from sklearn.metrics import average_precision_score, roc_auc_score

    if deltas is None:
        deltas = [-0.5, -0.3, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.3, 0.5]

    X_tr = np.asarray(X_train, dtype=float)
    X_te = np.asarray(X_test, dtype=float)
    m_tr = np.asarray(missing_mask_train, dtype=bool)
    m_te = np.asarray(missing_mask_test, dtype=bool)

    score_fn = average_precision_score if metric == "pr_auc" else roc_auc_score

    results = []
    baseline_score = None

    for delta in sorted(deltas):
        X_tr_shifted = X_tr.copy()
        X_te_shifted = X_te.copy()
        X_tr_shifted[m_tr] += delta
        X_te_shifted[m_te] += delta

        try:
            est = clone(estimator)
            est.fit(X_tr_shifted, y_train)
            y_score = est.predict_proba(X_te_shifted)[:, 1]
            score = float(score_fn(y_test, y_score))
        except Exception as exc:
            print(f"[mnar_sensitivity] delta={delta}: {exc}", file=sys.stderr)
            score = None

        if delta == 0.0 or (baseline_score is None and delta == min(deltas, key=abs)):
            baseline_score = score

        results.append({
            "delta": round(delta, 3),
            f"{metric}": round(score, 4) if score is not None else None,
        })

    # Tipping point: smallest |δ| where score drops below prevalence baseline
    prevalence = float(np.mean(y_test))
    tipping_point = None
    for r in results:
        s = r.get(metric)
        if s is not None and s <= prevalence and r["delta"] != 0.0:
            if tipping_point is None or abs(r["delta"]) < abs(tipping_point):
                tipping_point = r["delta"]

    return {
        "delta_results": results,
        "baseline_score": round(baseline_score, 4) if baseline_score is not None else None,
        "tipping_point": tipping_point,
        "tipping_threshold": round(prevalence, 4),
        "metric": metric,
        "n_deltas_tested": len(deltas),
    }


# ---------------------------------------------------------------------------
# Module 2: Temporal Drift Detection (calibration drift + CUSUM)
# Ref: Davis SE et al. JAMIA 2020;27(9):1514-1521; doi:10.1093/jamia/ocaa004
# ---------------------------------------------------------------------------

def temporal_drift_analysis(
    y_true: Any,
    y_score: Any,
    time_values: Any,
    n_windows: int = 5,
    n_bins: int = 10,
    *,
    cusum_threshold: float = 4.0,
    cusum_allowance: float = 0.1,
) -> Dict[str, Any]:
    """Detect calibration drift across time windows.

    Splits data into n_windows by time quantiles, computes calibration
    slope/intercept per window, and applies CUSUM to detect drift points.

    Args:
        y_true: Binary labels.
        y_score: Predicted probabilities.
        time_values: Numeric time values (epoch, ordinal, etc.).
        n_windows: Number of time windows.
        n_bins: Bins for per-window ECE calculation.
        cusum_threshold: CUSUM decision interval *h*. Drift is flagged when
            the cumulative sum exceeds this value. Default 4.0 follows the
            Page (1954) CUSUM design for detecting ~1σ shift with ARL₀ ≈ 168.
            Previous default was 0.5 which was overly sensitive.
        cusum_allowance: CUSUM reference value *k* — the minimum per-step
            deviation from O:E = 1.0 before accumulating signal (default 0.1).

    Returns:
        Dict with per_window metrics, cusum values, drift_detected flag,
        and drift_point (first window where CUSUM exceeds threshold).

    References:
        Page ES. Biometrika. 1954;41(1-2):100-115 (original CUSUM).
        Davis SE et al. JAMIA. 2020;27(9):1514-1521 (PMC8627243).
    """
    import numpy as np

    y_t = np.asarray(y_true, dtype=float)
    y_s = np.asarray(y_score, dtype=float)
    t_v = np.asarray(time_values, dtype=float)

    # Sort by time
    order = np.argsort(t_v)
    y_t = y_t[order]
    y_s = y_s[order]
    t_v = t_v[order]

    # Split into windows by quantiles
    window_edges = np.linspace(0, len(y_t), n_windows + 1, dtype=int)
    windows = []

    for i in range(n_windows):
        start, end = window_edges[i], window_edges[i + 1]
        if end - start < 10:
            continue
        yt_w = y_t[start:end]
        ys_w = y_s[start:end]

        # O:E ratio
        observed = float(yt_w.sum())
        expected = float(ys_w.sum())
        oe = observed / expected if expected > 0 else float("nan")

        # ECE
        bin_edges = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        n_w = len(yt_w)
        for b in range(n_bins):
            mask = (ys_w >= bin_edges[b]) & (ys_w < bin_edges[b + 1])
            if b == n_bins - 1:
                mask = (ys_w >= bin_edges[b]) & (ys_w <= bin_edges[b + 1])
            nb = int(mask.sum())
            if nb > 0:
                ece += abs(float(yt_w[mask].mean()) - float(ys_w[mask].mean())) * (nb / n_w)

        # Prevalence
        prev = float(yt_w.mean())

        windows.append({
            "window": i,
            "n_samples": end - start,
            "time_min": round(float(t_v[start]), 2),
            "time_max": round(float(t_v[end - 1]), 2),
            "prevalence": round(prev, 4),
            "oe_ratio": round(oe, 4),
            "ece": round(ece, 4),
        })

    # CUSUM on O:E ratio deviations from 1.0
    if len(windows) >= 3:
        oe_values = [w["oe_ratio"] for w in windows if np.isfinite(w["oe_ratio"])]
        cusum = []
        s = 0.0
        drift_point = None
        for i, oe in enumerate(oe_values):
            s = max(0, s + abs(oe - 1.0) - cusum_allowance)
            cusum.append(round(s, 4))
            if s > cusum_threshold and drift_point is None:
                drift_point = i
    else:
        cusum = []
        drift_point = None

    return {
        "per_window": windows,
        "cusum_values": cusum,
        "drift_detected": drift_point is not None,
        "drift_point_window": drift_point,
        "n_windows": len(windows),
    }


# ---------------------------------------------------------------------------
# Module 3: Model Card Generator
# Ref: Mitchell et al. 2019 (FAT*)
# ---------------------------------------------------------------------------



# ═══════════════════════════════════════════════════════════════
# Model Card & Reporting
# ═══════════════════════════════════════════════════════════════

def generate_model_card(
    model_name: str,
    model_type: str,
    evaluation_report: Dict[str, Any],
    cohort_report: Optional[Dict[str, Any]] = None,
    fairness_report: Optional[Dict[str, Any]] = None,
    shap_report: Optional[Dict[str, Any]] = None,
    intended_use: str = "",
    limitations: Optional[list] = None,
    ethical_considerations: Optional[list] = None,
) -> str:
    """Generate a structured Model Card in Markdown format.

    Args:
        model_name: Human-readable model name.
        model_type: Model family (e.g., "LightGBM").
        evaluation_report: Gate evaluation report (metrics, CI).
        cohort_report: Cohort definition report (optional).
        fairness_report: Fairness gate report (optional).
        shap_report: SHAP interpretability report (optional).
        intended_use: Description of intended clinical use.
        limitations: List of known limitations.
        ethical_considerations: List of ethical considerations.

    Returns:
        Markdown string for model_card.md.

    References:
        Mitchell M et al. "Model Cards for Model Reporting." FAT* 2019.
    """
    lines = [
        f"# Model Card: {model_name}",
        "",
        "## Model Details",
        f"- **Model type**: {model_type}",
        f"- **Framework**: ML Governance Guard (MLGG) v1.0",
        f"- **Training framework**: scikit-learn Pipeline (imputer → scaler → classifier)",
    ]

    # Intended Use
    lines.extend([
        "",
        "## Intended Use",
        f"- **Primary use**: {intended_use or 'Clinical risk prediction (binary classification)'}",
        "- **Out-of-scope uses**: Not intended for individual clinical decisions without physician oversight.",
    ])

    # Training Data
    if cohort_report and isinstance(cohort_report.get("summary"), dict):
        s = cohort_report["summary"]
        target = s.get("target", {})
        lines.extend([
            "",
            "## Training Data",
            f"- **Total samples**: {s.get('n_rows', 'N/A')}",
            f"- **Features**: {s.get('n_features', 'N/A')}",
            f"- **Positive events**: {target.get('n_positive', 'N/A')}",
            f"- **Prevalence**: {target.get('prevalence', 'N/A')}",
            f"- **EPV**: {target.get('epv', 'N/A')}",
        ])
        riley = target.get("riley_sample_size", {})
        if riley and not riley.get("error"):
            lines.append(f"- **Riley minimum n**: {riley.get('n_minimum', 'N/A')} "
                         f"(binding: {riley.get('binding_criterion', '?')})")

    # Performance
    if isinstance(evaluation_report, dict):
        metrics = evaluation_report.get("summary", evaluation_report).get("metrics", {})
        if not metrics:
            metrics = evaluation_report.get("metrics", {})
        lines.extend([
            "",
            "## Performance (Test Set)",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                lines.append(f"| {k} | {v:.4f} |")

    # Fairness
    if fairness_report and isinstance(fairness_report.get("summary"), dict):
        lines.extend([
            "",
            "## Fairness Analysis",
        ])
        fs = fairness_report["summary"]
        for group_name, group_data in fs.items():
            if isinstance(group_data, dict) and "disparity" in str(group_data):
                lines.append(f"- **{group_name}**: {group_data}")

    # Interpretability
    if shap_report and isinstance(shap_report.get("summary"), dict):
        ss = shap_report["summary"]
        top_feats = ss.get("ensemble_top_features", [])[:5]
        if top_feats:
            lines.extend([
                "",
                "## Feature Importance (Top 5)",
                "| Rank | Feature | Ensemble Proportion |",
                "|------|---------|-------------------|",
            ])
            for f in top_feats:
                lines.append(f"| {f.get('rank', '')} | {f.get('feature', '')} | "
                             f"{f.get('ensemble_proportion', ''):.4f} |")

    # Limitations
    lines.extend([
        "",
        "## Limitations",
    ])
    if limitations:
        for lim in limitations:
            lines.append(f"- {lim}")
    else:
        lines.extend([
            "- Model trained on retrospective data; prospective validation not performed.",
            "- Performance may degrade with temporal population shift (calibration drift).",
            "- Not validated on external institutions.",
        ])

    # Ethical Considerations
    lines.extend([
        "",
        "## Ethical Considerations",
    ])
    if ethical_considerations:
        for ec in ethical_considerations:
            lines.append(f"- {ec}")
    else:
        lines.extend([
            "- Model should supplement, not replace, clinical judgment.",
            "- Subgroup performance should be monitored for health equity.",
            "- Patient consent and data privacy must be maintained.",
        ])

    lines.extend([
        "",
        "---",
        "*Generated by ML Governance Guard (MLGG) v1.0*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module 4: Imputation Sensitivity Analysis
# Ref: Madley-Dowd P et al. J Clin Epidemiol 2019;110:63-73
# ---------------------------------------------------------------------------

def imputation_sensitivity(
    X_raw: Any,
    y: Any,
    estimator: Any,
    feature_names: list,
    test_size: float = 0.2,
    seed: int = 42,
) -> list:
    """Compare model performance across imputation methods.

    Tests median, KNN, and iterative (MICE) imputation to assess
    whether conclusions are robust to imputation choice.

    Args:
        X_raw: Feature matrix with NaN values (pre-imputation).
        y: Binary target.
        estimator: sklearn estimator to clone and train per method.
        feature_names: Feature names.
        test_size: Test split fraction.
        seed: Random seed.

    Returns:
        List of dicts with method, auroc, pr_auc, brier, n_missing_cells.

    References:
        Madley-Dowd P et al. J Clin Epidemiol 2019;110:63-73.
    """
    import numpy as np
    from sklearn.base import clone
    from sklearn.impute import KNNImputer, SimpleImputer
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    from sklearn.model_selection import train_test_split

    X = np.asarray(X_raw, dtype=float)
    y_arr = np.asarray(y, dtype=int)
    n_missing = int(np.isnan(X).sum())

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y_arr, test_size=test_size, random_state=seed, stratify=y_arr,
    )

    methods = {
        "median": SimpleImputer(strategy="median"),
        "mean": SimpleImputer(strategy="mean"),
        "knn_5": KNNImputer(n_neighbors=5),
    }

    # Try MICE if available
    try:
        from sklearn.experimental import enable_iterative_imputer  # noqa: F401
        from sklearn.impute import IterativeImputer
        methods["mice"] = IterativeImputer(max_iter=10, random_state=seed, sample_posterior=False)
    except ImportError:
        pass

    results = []
    for name, imputer in methods.items():
        try:
            imp = clone(imputer)
            X_tr_imp = imp.fit_transform(X_tr)
            X_te_imp = imp.transform(X_te)

            est = clone(estimator)
            est.fit(X_tr_imp, y_tr)
            y_score = est.predict_proba(X_te_imp)[:, 1]

            results.append({
                "method": name,
                "roc_auc": round(float(roc_auc_score(y_te, y_score)), 4),
                "pr_auc": round(float(average_precision_score(y_te, y_score)), 4),
                "brier": round(float(brier_score_loss(y_te, y_score)), 4),
            })
        except Exception as exc:
            print(f"[imputation_sensitivity] method={name}: {exc}", file=sys.stderr)
            results.append({"method": name, "roc_auc": None, "pr_auc": None, "brier": None})

    # Assess robustness
    valid_roc_aucs = [r["roc_auc"] for r in results if r["roc_auc"] is not None]
    if len(valid_roc_aucs) >= 2:
        spread = max(valid_roc_aucs) - min(valid_roc_aucs)
        robust = spread < 0.01
    else:
        spread = None
        robust = None

    return {
        "methods": results,
        "n_missing_cells": n_missing,
        "missing_fraction": round(n_missing / max(X.size, 1), 4),
        "roc_auc_spread": round(spread, 4) if spread is not None else None,
        "robust": robust,
    }


# ---------------------------------------------------------------------------
# Module 5: Subgroup-specific DCA (Net Benefit by subgroup)
# Ref: Vickers AJ, Elkin EB. Med Decis Making 2006;26(6):565-574
# ---------------------------------------------------------------------------

def subgroup_dca(
    y_true: Any,
    y_score: Any,
    group_labels: Any,
    thresholds: Optional[list] = None,
) -> Dict[str, Any]:
    """Decision Curve Analysis stratified by subgroup.

    Computes net benefit per subgroup across threshold probabilities,
    revealing whether the model has clinical utility for ALL groups
    or only for majority populations.

    Args:
        y_true: Binary labels.
        y_score: Predicted probabilities.
        group_labels: Group assignment per sample (e.g., race, gender).
        thresholds: Probability thresholds to evaluate.

    Returns:
        Dict with per_group DCA curves and equity_gap (max disparity
        in net benefit at optimal threshold).

    References:
        Vickers AJ, Elkin EB. Med Decis Making. 2006;26:565-574.
    """
    import numpy as np

    y_t = np.asarray(y_true, dtype=float)
    y_s = np.asarray(y_score, dtype=float)
    g = np.asarray(group_labels)

    if thresholds is None:
        thresholds = [round(t, 2) for t in np.arange(0.01, 0.99, 0.02).tolist()]

    unique_groups = sorted(set(g.tolist()))
    group_curves: Dict[str, list] = {}
    group_optimal_nb: Dict[str, float] = {}

    for group in unique_groups:
        mask = g == group
        yt_g = y_t[mask]
        ys_g = y_s[mask]
        n_g = int(mask.sum())

        if n_g < 20:
            group_curves[str(group)] = []
            continue

        prevalence = float(yt_g.mean())
        curve = []

        best_nb = -999.0
        for pt in thresholds:
            tp = float(((ys_g >= pt) & (yt_g == 1)).sum())
            fp = float(((ys_g >= pt) & (yt_g == 0)).sum())
            nb = (tp / n_g) - (fp / n_g) * (pt / (1 - pt)) if pt < 1 else 0.0
            curve.append({
                "threshold": pt,
                "net_benefit": round(nb, 6),
                "treat_all_nb": round(prevalence - (1 - prevalence) * (pt / (1 - pt)), 6) if pt < 1 else 0.0,
            })
            if nb > best_nb:
                best_nb = nb

        group_curves[str(group)] = curve
        group_optimal_nb[str(group)] = round(best_nb, 4)

    # Equity gap: max disparity in optimal net benefit
    if len(group_optimal_nb) >= 2:
        nbs = list(group_optimal_nb.values())
        equity_gap = round(max(nbs) - min(nbs), 4)
        best_group = max(group_optimal_nb, key=group_optimal_nb.get)
        worst_group = min(group_optimal_nb, key=group_optimal_nb.get)
    else:
        equity_gap = None
        best_group = None
        worst_group = None

    return {
        "groups": unique_groups,
        "group_curves": group_curves,
        "group_optimal_net_benefit": group_optimal_nb,
        "equity_gap": equity_gap,
        "best_group": best_group,
        "worst_group": worst_group,
        "n_thresholds": len(thresholds),
    }


# ---------------------------------------------------------------------------
# Tamper-evident audit log for gate executions
# ---------------------------------------------------------------------------

_AUDIT_LOG_NAME = ".gate_audit.jsonl"


def _hmac_chain(prev_hash: str, entry_json: str) -> str:
    """Compute HMAC-SHA256 chain hash linking this entry to the previous."""
    import hashlib
    import hmac
    key = prev_hash.encode("utf-8")
    return hmac.new(key, entry_json.encode("utf-8"), hashlib.sha256).hexdigest()


def append_audit_entry(
    evidence_dir: Path,
    gate_name: str,
    status: str,
    failure_count: int = 0,
    warning_count: int = 0,
    execution_time: float = 0.0,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a tamper-evident audit log entry for a gate execution.

    Each entry contains:
      - timestamp, gate name, status, counts
      - chain_hash: HMAC-SHA256 linking to previous entry (tamper detection)
      - pid and hostname for forensic tracing

    Args:
        evidence_dir: Directory containing the audit log.
        gate_name: Name of the executed gate.
        status: Gate result status (pass/fail).
        failure_count: Number of failures.
        warning_count: Number of warnings.
        execution_time: Execution duration in seconds.
        extra: Optional additional metadata.
    """
    import datetime as _dt
    import platform

    log_path = evidence_dir / _AUDIT_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Read last chain hash — seek to end of file to avoid loading everything
    prev_hash = "0" * 64
    if log_path.exists():
        try:
            with log_path.open("rb") as fh:
                fh.seek(0, 2)  # seek to end
                pos = fh.tell()
                if pos > 0:
                    # Read progressively larger chunks until we find a
                    # complete JSON line (one that parses successfully).
                    for chunk_size in (8192, 65536, 524288, pos):
                        chunk_size = min(chunk_size, pos)
                        fh.seek(pos - chunk_size)
                        raw = fh.read(chunk_size)
                        try:
                            tail = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            continue
                        # Walk lines from end to find last parseable JSON
                        for candidate in reversed(tail.strip().splitlines()):
                            candidate = candidate.strip()
                            if not candidate:
                                continue
                            try:
                                last = json.loads(candidate)
                                prev_hash = last.get("chain_hash", prev_hash)
                                break
                            except json.JSONDecodeError:
                                continue  # Partial line, try next
                        else:
                            continue  # No valid line in this chunk
                        break  # Found a valid line
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    entry: Dict[str, Any] = {
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "gate_name": gate_name,
        "status": status,
        "failure_count": failure_count,
        "warning_count": warning_count,
        "execution_time_seconds": round(execution_time, 3),
        "pid": os.getpid(),
        "hostname": platform.node(),
    }
    if extra:
        entry["extra"] = extra

    entry_json = json.dumps(entry, ensure_ascii=True, sort_keys=True)
    entry["chain_hash"] = _hmac_chain(prev_hash, entry_json)
    # Re-serialize only once (entry now includes chain_hash)
    final_line = json.dumps(entry, ensure_ascii=True, sort_keys=True)

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(final_line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def verify_audit_chain(evidence_dir: Path) -> Dict[str, Any]:
    """Verify the integrity of the gate audit log chain.

    Streams line-by-line to avoid loading entire log into memory.

    Returns:
        Dict with 'valid' (bool), 'entries' (int), 'broken_at' (int or None).
    """
    import hmac as _hmac_mod

    log_path = evidence_dir / _AUDIT_LOG_NAME
    if not log_path.exists():
        return {"valid": True, "entries": 0, "broken_at": None, "reason": "no_log"}

    prev_hash = "0" * 64
    entry_count = 0
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return {"valid": False, "entries": entry_count, "broken_at": entry_count, "reason": "json_parse_error"}

                stored_hash = entry.pop("chain_hash", None)
                if stored_hash is None:
                    return {"valid": False, "entries": entry_count, "broken_at": entry_count, "reason": "missing_chain_hash"}

                entry_json = json.dumps(entry, ensure_ascii=True, sort_keys=True)
                expected = _hmac_chain(prev_hash, entry_json)
                if not _hmac_mod.compare_digest(stored_hash, expected):
                    return {"valid": False, "entries": entry_count, "broken_at": entry_count, "reason": "chain_hash_mismatch"}
                prev_hash = stored_hash
                entry_count += 1
    except (OSError, UnicodeDecodeError):
        return {"valid": False, "entries": entry_count, "broken_at": None, "reason": "read_error"}

    return {"valid": True, "entries": entry_count, "broken_at": None}


# ---------------------------------------------------------------------------
# Multiple comparison correction utilities
# ---------------------------------------------------------------------------

def fdr_bh_correction(
    pvalues: List[float],
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Benjamini-Hochberg FDR correction for multiple p-values.

    Args:
        pvalues: List of raw p-values (must be finite, in [0,1]).
        alpha: Family-wise significance level (default 0.05).

    Returns:
        Dict with keys:
            n_tests: number of tests
            alpha: original alpha
            pvalues_raw: input p-values
            pvalues_adjusted: BH-adjusted p-values
            rejected: list of booleans (True = significant after correction)
            n_rejected: number of rejected nulls
    """
    import math as _m

    n = len(pvalues)
    if n == 0:
        return {
            "n_tests": 0, "alpha": alpha, "pvalues_raw": [],
            "pvalues_adjusted": [], "rejected": [], "n_rejected": 0,
        }

    # Validate
    clean: List[float] = []
    for p in pvalues:
        try:
            pf = float(p)
        except (TypeError, ValueError):
            pf = 1.0
        if not _m.isfinite(pf):
            pf = 1.0
        clean.append(max(0.0, min(1.0, pf)))

    # BH procedure: sort, compute adjusted, enforce monotonicity
    indexed = sorted(enumerate(clean), key=lambda x: x[1])
    adjusted = [0.0] * n
    prev = 1.0
    for rank_from_end, (orig_idx, raw_p) in enumerate(reversed(indexed)):
        rank = n - rank_from_end  # 1-based rank from smallest
        adj = min(prev, raw_p * n / rank)
        adj = min(1.0, adj)
        adjusted[orig_idx] = adj
        prev = adj

    rejected = [adj <= alpha for adj in adjusted]

    return {
        "n_tests": n,
        "alpha": alpha,
        "pvalues_raw": clean,
        "pvalues_adjusted": adjusted,
        "rejected": rejected,
        "n_rejected": sum(rejected),
    }


def bonferroni_adjusted_threshold(
    threshold: float,
    n_comparisons: int,
) -> float:
    """Return Bonferroni-adjusted threshold (threshold / n).

    For effect-size thresholds (not p-values), this is a conservative
    heuristic — use when strict FDR is not applicable.
    """
    if n_comparisons <= 1:
        return threshold
    return threshold / n_comparisons
