"""
Shared utility functions for ml-leakage-guard gate scripts.

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


def add_issue(
    bucket: List[Dict[str, Any]],
    code: str,
    message: str,
    details: Dict[str, Any],
) -> None:
    """Append a structured issue dict to a bucket list."""
    bucket.append({"code": code, "message": message, "details": details})


_MAX_JSON_FILE_SIZE = 100 * 1024 * 1024  # 100 MB safety limit


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


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write a JSON object to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1_000_000)}"
    )
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp_path.replace(path)


_FORBIDDEN_PATH_PREFIXES = [
    "/etc", "/private/etc", "/proc", "/sys", "/dev",
    "/var/run", "/boot", "/sbin",
]


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


def try_parse_time(value: str) -> Optional[float]:
    """Parse a time string to epoch float, trying multiple formats.

    Args:
        value: Raw time string (ISO-8601, date, or numeric epoch).

    Returns:
        Epoch timestamp as float, or None if unparseable.
    """
    import datetime as _dt

    s = value.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    iso = s.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(iso).timestamp()
    except ValueError:
        pass
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return _dt.datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


def epoch_to_iso(ts: Optional[float]) -> Optional[str]:
    """Convert epoch timestamp to UTC ISO-8601 string.

    Args:
        ts: Epoch timestamp, or None.

    Returns:
        ISO-8601 string with Z suffix, or None.
    """
    import datetime as _dt

    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")


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
    }
    return metrics, cm


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
        lr = LogisticRegression(C=1e10, solver="lbfgs", max_iter=1000)
    else:
        lr = LogisticRegression(penalty=None, solver="lbfgs", max_iter=1000)
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
        y_sub = y_train[idx] if hasattr(y_train, "__getitem__") else np.asarray(y_train)[idx]

        if len(np.unique(y_sub)) < 2:
            continue

        try:
            est = clone(estimator)
            est.fit(X_sub, y_sub)
            train_score = float(score_fn(y_sub, est.predict_proba(X_sub)[:, 1]))
            test_score = float(score_fn(y_test, est.predict_proba(X_test)[:, 1]))
        except Exception:
            continue  # Skip this fraction if clone/fit/predict fails

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

    # Continuous NRI
    cont_event_nri = float(((p_new > p_old) & events).mean() - ((p_new < p_old) & events).mean()) if n_events > 0 else 0.0
    cont_nonevent_nri = float(((p_new < p_old) & nonevents).mean() - ((p_new > p_old) & nonevents).mean()) if n_nonevents > 0 else 0.0
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
