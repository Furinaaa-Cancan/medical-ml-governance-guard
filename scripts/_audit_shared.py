"""
Shared constants and utilities for audit_external_project and generate_audit_report.

This module eliminates duplication between the two audit scripts by centralizing:
- Code anti-pattern regex definitions
- Pattern severity / description mappings
- Score interpretation logic
- Safe JSON loading
- File structure checks
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

# ---------------------------------------------------------------------------
# Code anti-pattern definitions (superset used by both audit tools)
# ---------------------------------------------------------------------------

CODE_PATTERNS: Dict[str, re.Pattern[str]] = {
    "fit_on_full_data": re.compile(
        r"\.fit\s*\([^)]*(?:X_all|X_full|df\b|data\b)", re.IGNORECASE
    ),
    "test_in_training_loop": re.compile(
        r"(?:X_test|y_test|test_data)\s*(?:\.fit|fit_transform)", re.IGNORECASE
    ),
    "smote_on_full": re.compile(
        r"SMOTE|ADASYN|BorderlineSMOTE", re.IGNORECASE
    ),
    "no_random_seed": re.compile(
        r"random_state\s*=\s*None", re.IGNORECASE
    ),
    "hardcoded_threshold": re.compile(
        r"threshold\s*=\s*0\.5\b"
    ),
    "missing_ci": re.compile(
        r"(?:accuracy|auc|roc_auc|f1|precision|recall)(?:_score)?\s*=",
        re.IGNORECASE
    ),
    "shell_true": re.compile(
        r"subprocess\.[^\n]*shell\s*=\s*True", re.IGNORECASE
    ),
    "pickle_load_unsafe": re.compile(
        r"pickle\.load\s*\(", re.IGNORECASE
    ),
    "eval_use": re.compile(
        r"\beval\s*\(", re.IGNORECASE
    ),
    "no_train_test_split": re.compile(
        r"train_test_split\s*\([^,)]+\)", re.IGNORECASE
    ),
    "global_scaler_leak": re.compile(
        r"StandardScaler|MinMaxScaler|RobustScaler", re.IGNORECASE
    ),
    "leakage_via_future": re.compile(
        r"(?:discharge_date|death_date|outcome_date)\s*[^=]", re.IGNORECASE
    ),
}

# The 6-pattern subset used by the quick audit (audit_external_project.py)
QUICK_PATTERN_KEYS = frozenset({
    "fit_on_full_data", "test_in_training_loop", "smote_on_full",
    "no_random_seed", "hardcoded_threshold", "missing_ci",
})

PATTERN_SEVERITY: Dict[str, str] = {
    "fit_on_full_data": "CRITICAL",
    "test_in_training_loop": "CRITICAL",
    "smote_on_full": "WARNING",
    "no_random_seed": "WARNING",
    "hardcoded_threshold": "INFO",
    "missing_ci": "INFO",
    "shell_true": "WARNING",
    "pickle_load_unsafe": "WARNING",
    "eval_use": "WARNING",
    "no_train_test_split": "INFO",
    "global_scaler_leak": "WARNING",
    "leakage_via_future": "CRITICAL",
}

PATTERN_DESCRIPTION: Dict[str, str] = {
    "fit_on_full_data": "Potential fit on full/combined data — preprocessor trained on test set (data leakage)",
    "test_in_training_loop": "Test data referenced in training loop — direct data leakage",
    "smote_on_full": "SMOTE/oversampling detected — must verify it's applied only to training fold",
    "no_random_seed": "random_state=None — results are non-reproducible across runs",
    "hardcoded_threshold": "Hardcoded decision threshold 0.5 — threshold should be optimized on validation set",
    "missing_ci": "Metric computed without confidence interval — violates TRIPOD+AI Item 17",
    "shell_true": "subprocess with shell=True — shell injection vulnerability",
    "pickle_load_unsafe": "pickle.load() without source verification — arbitrary code execution risk",
    "eval_use": "eval() usage — code injection risk",
    "no_train_test_split": "train_test_split used without stratify= — may produce imbalanced splits",
    "global_scaler_leak": "Scaler instantiation detected — verify it's fitted only on training data",
    "leakage_via_future": "Possible future-dated feature — verify it's not outcome-proximate",
}


# ---------------------------------------------------------------------------
# Score interpretation
# ---------------------------------------------------------------------------

def score_interpretation(score: float) -> Tuple[str, str]:
    """Return (label_en, label_zh) for a total score."""
    if score >= 90:
        return ("Publication-grade", "顶刊级")
    if score >= 75:
        return ("Solid but gaps remain", "需补充")
    if score >= 60:
        return ("Major issues", "重大缺陷")
    return ("Not publishable", "不可发表")


# ---------------------------------------------------------------------------
# Safe JSON loading
# ---------------------------------------------------------------------------

def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON without raising; return None on any error."""
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return cast(Dict[str, Any], json.load(f))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Code pattern scanning
# ---------------------------------------------------------------------------

_DEFAULT_FILE_LIMIT = 300


def scan_code_patterns(
    project_dir: Path,
    *,
    pattern_keys: Optional[frozenset[str]] = None,
    file_limit: int = _DEFAULT_FILE_LIMIT,
) -> Dict[str, List[str]]:
    """Scan Python files for code anti-patterns.

    Args:
        project_dir: Root directory to scan.
        pattern_keys: Subset of CODE_PATTERNS keys to use. None = all.
        file_limit: Max number of .py files to scan.

    Returns:
        Dict of {pattern_name: [relative file paths with matches]}.
    """
    patterns = CODE_PATTERNS
    if pattern_keys is not None:
        patterns = {k: v for k, v in patterns.items() if k in pattern_keys}
    results: Dict[str, List[str]] = {k: [] for k in patterns}

    for pf in itertools.islice(project_dir.rglob("*.py"), file_limit):
        try:
            content = pf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pat in patterns.items():
            if pat.search(content):
                results[name].append(str(pf.relative_to(project_dir)))

    return results


# ---------------------------------------------------------------------------
# File structure checks
# ---------------------------------------------------------------------------

def check_file_structure(project_dir: Path) -> Dict[str, bool]:
    """Check for expected project artifacts."""
    return {
        "has_train_csv": any(project_dir.rglob("*train*.csv")),
        "has_valid_csv": (
            any(project_dir.rglob("*val*.csv"))
            or any(project_dir.rglob("*valid*.csv"))
        ),
        "has_test_csv": any(project_dir.rglob("*test*.csv")),
        "has_request_json": any(project_dir.rglob("request*.json")),
        "has_evidence_dir": (project_dir / "evidence").is_dir(),
        "has_model_artifact": (
            any(project_dir.rglob("*.pkl"))
            or any(project_dir.rglob("*.joblib"))
        ),
        "has_requirements": (
            (project_dir / "requirements.txt").is_file()
            or (project_dir / "pyproject.toml").is_file()
        ),
        "has_git": (project_dir / ".git").is_dir(),
    }
