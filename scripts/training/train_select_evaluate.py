#!/usr/bin/env python3
"""
Train, select, and evaluate binary models with leakage-safe model-selection evidence.

Pipeline stages:
    1. Load train/valid/test splits and performance policy.
    2. Feature engineering: filter by missingness/variance, group preselection,
       stability frequency analysis.
    3. Build candidate model pool with hyperparameter search (grid/random/optuna).
    4. Score candidates via stratified CV (PR-AUC) and select via one-SE rule.
    5. Fit calibration on leakage-safe split and choose clinical threshold.
    6. Evaluate on held-out test set with bootstrap CI.
    7. Optionally evaluate external cohorts and compute distribution/robustness reports.

Usage:
    python3 scripts/train_select_evaluate.py \\
        --train data/train.csv --valid data/valid.csv --test data/test.csv \\
        --model-selection-report-out evidence/model_selection_report.json \\
        --evaluation-report-out evidence/evaluation_report.json

Output files:
    - model_selection_report.json: candidate pool, CV scores, selection trace.
    - evaluation_report.json: test metrics, CI, thresholds, baselines.
    - prediction_trace.csv.gz: per-row predictions for replay gates.
    - model.pkl (optional): serialized trained model artifact.
    - feature_engineering_report.json (optional): feature provenance evidence.
    - distribution_report.json (optional): feature shift analysis.
    - ci_matrix_report.json (optional): per-metric CI across all splits.
    - external_validation_report.json (optional): external cohort metrics.
    - robustness_report.json (optional): subgroup robustness analysis.
    - seed_sensitivity_report.json (optional): multi-seed stability analysis.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import hashlib
import json
import math
import os
import sys
import warnings
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Keep loky from probing physical-core internals that print noisy traceback
# on some macOS/Python combinations. Use (logical_cores - 1) to stay below the
# logical-core ceiling while preserving parallelism.
_logical_cores = int(os.cpu_count() or 1)
_loky_cap = max(1, _logical_cores - 1)
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(_loky_cap))

import joblib
import numpy as np
import gc
import pandas as pd
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.base import BaseEstimator, clone
from sklearn.ensemble import (
    AdaBoostClassifier,
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import IterativeImputer, SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier, NearestNeighbors
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

try:
    from xgboost import XGBClassifier  # type: ignore
except (ImportError, OSError):
    XGBClassifier = None  # type: ignore

try:
    from catboost import CatBoostClassifier  # type: ignore
except (ImportError, OSError):
    CatBoostClassifier = None  # type: ignore

try:
    from lightgbm import LGBMClassifier  # type: ignore
except (ImportError, OSError):
    LGBMClassifier = None  # type: ignore

try:
    from tabpfn import TabPFNClassifier  # type: ignore
except (ImportError, OSError):
    TabPFNClassifier = None  # type: ignore

try:
    import optuna  # type: ignore
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except (ImportError, OSError):
    optuna = None  # type: ignore

# Ensemble imbalance classifiers (imblearn) — optional dependency
try:
    from imblearn.ensemble import (  # type: ignore
        BalancedRandomForestClassifier,
        EasyEnsembleClassifier,
        RUSBoostClassifier,
    )
except (ImportError, OSError):
    BalancedRandomForestClassifier = None  # type: ignore
    EasyEnsembleClassifier = None  # type: ignore
    RUSBoostClassifier = None  # type: ignore


SUPPORTED_MODEL_FAMILIES = {
    "logistic_l1",
    "logistic_l2",
    "logistic_elasticnet",
    "random_forest_balanced",
    "extra_trees_balanced",
    "hist_gradient_boosting_l2",
    "adaboost",
    "xgboost",
    "catboost",
    "lightgbm",
    "svm_linear",
    "svm_rbf",
    "knn",
    "gaussian_nb",
    "decision_tree",
    "mlp",
    "tabpfn",
    "balanced_random_forest",
    "easy_ensemble",
    "rusboost",
    "soft_voting",
    "weighted_voting",
    "stacking",
}

# Families that handle imbalance internally — do NOT apply external
# resampling (apply_imbalance_strategy_to_train) or class_weight to these.
# Calibration should be verified post-hoc (van den Goorbergh 2022).
INTERNAL_IMBALANCE_FAMILIES = {"balanced_random_forest", "easy_ensemble", "rusboost"}

ENSEMBLE_FAMILIES = {"soft_voting", "weighted_voting", "stacking"}
DEFAULT_ENSEMBLE_TOP_K = 3
_FOLD_IMBALANCE_SEED_STRIDE = 2027
SUPPORTED_IMBALANCE_STRATEGIES = {
    "auto",
    "none",
    "class_weight",
    "random_oversample",
    "random_undersample",
    "smote",
    "adasyn",
}

MODEL_ALIASES = {
    "lr": "logistic_l2",
    "lr_l1": "logistic_l1",
    "lr_l2": "logistic_l2",
    "lr_en": "logistic_elasticnet",
    "rf": "random_forest_balanced",
    "extra_trees": "extra_trees_balanced",
    "hgb": "hist_gradient_boosting_l2",
    "xgb": "xgboost",
    "lgbm": "lightgbm",
    "svm": "svm_rbf",
    "svm_lin": "svm_linear",
    "voting": "soft_voting",
    "stack": "stacking",
    "brf": "balanced_random_forest",
    "easy_ens": "easy_ensemble",
    "rusboost": "rusboost",
}


def resolve_device(requested: str) -> str:
    """Resolve compute device string to an available backend.

    Args:
        requested: Device preference ('auto', 'cpu', 'gpu', 'mps').

    Returns:
        Resolved device string ('cpu', 'gpu', or 'mps').
    """
    requested = str(requested).strip().lower()
    if requested == "auto":
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "gpu"
        except Exception:  # noqa: BLE001 — torch not installed; fall through to CPU
            pass
        return "cpu"
    if requested == "mps":
        try:
            import torch
            if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
                print("[WARN] MPS requested but not available. Falling back to CPU.")
                return "cpu"
        except Exception:
            print("[WARN] MPS requested but torch not installed. Falling back to CPU.")
            return "cpu"
        return "mps"
    if requested == "gpu":
        try:
            import torch
            if not torch.cuda.is_available():
                print("[WARN] GPU requested but CUDA not available. Falling back to CPU.")
                return "cpu"
        except Exception:
            print("[WARN] GPU requested but torch not installed. Falling back to CPU.")
            return "cpu"
        return "gpu"
    return "cpu"


def configure_runtime_warning_filters() -> None:
    """Suppress known third-party warnings that do not indicate gate failures."""
    # Reduce known third-party warning noise in terminal output without masking
    # gate failures or explicit script validation errors.
    warnings.filterwarnings(
        "ignore",
        message=r".*'penalty' was deprecated in version 1\.8.*",
        category=FutureWarning,
        module=r"sklearn\.linear_model\._logistic",
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Inconsistent values: penalty=.*l1_ratio=.*",
        category=UserWarning,
        module=r"sklearn\.linear_model\._logistic",
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*Could not find the number of physical cores.*",
        category=UserWarning,
        module=r"joblib\.externals\.loky\.backend\.context",
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*max_iter was reached which means the coef_ did not converge.*",
        category=ConvergenceWarning,
        module=r"sklearn\.linear_model\._sag",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the training pipeline.

    Returns:
        Parsed argument namespace with all CLI parameters.
    """
    parser = argparse.ArgumentParser(description="Train/select/evaluate leakage-safe medical binary models.")
    parser.add_argument("--train", required=True, help="Path to train CSV.")
    parser.add_argument("--valid", default="", help="Path to valid CSV (optional for two-way/CV-only split modes).")
    parser.add_argument("--test", default="", help="Path to test CSV (optional for CV-only mode; uses bootstrap internal validation).")
    parser.add_argument("--target-col", default="y", help="Target column.")
    parser.add_argument("--patient-id-col", default="patient_id", help="Patient ID column used for trace hashing.")
    parser.add_argument("--ignore-cols", default="patient_id,event_time", help="Comma-separated non-feature columns.")
    parser.add_argument("--definition-cols", default="", help="Comma-separated columns used to DEFINE the outcome (e.g., HbA1c,fasting_glucose). These are forcibly excluded from features to prevent target leakage.")
    parser.add_argument("--performance-policy", help="Optional performance policy JSON path.")
    parser.add_argument("--missingness-policy", help="Optional missingness policy JSON path.")
    parser.add_argument("--selection-data", default="cv_inner", help="Model selection source (valid/cv_inner/nested_cv).")
    parser.add_argument("--threshold-selection-split", default="valid", help="Split used for threshold selection.")
    parser.add_argument(
        "--calibration-method",
        default="none",
        choices=["sigmoid", "isotonic", "power", "beta", "none"],
        help="Probability calibration method fit on leakage-safe split.",
    )
    parser.add_argument("--cv-splits", type=int, default=5, help="CV folds for candidate scoring.")
    parser.add_argument("--temporal-cv", action="store_true",
                        help="Use TimeSeriesSplit instead of StratifiedKFold for CV. "
                             "Required when training data has temporal ordering to prevent "
                             "future-to-past leakage within CV folds.")
    parser.add_argument(
        "--model-pool",
        default="",
        help=(
            "Comma-separated model families. Supported: "
            "logistic_l1,logistic_l2,logistic_elasticnet,random_forest_balanced,"
            "extra_trees_balanced,hist_gradient_boosting_l2,adaboost,xgboost,catboost,"
            "lightgbm,svm_linear,svm_rbf,tabpfn,soft_voting,weighted_voting,stacking."
        ),
    )
    parser.add_argument(
        "--include-optional-models",
        action="store_true",
        help="Append optional backends (xgboost/catboost/lightgbm/tabpfn) when installed.",
    )
    parser.add_argument(
        "--ensemble-top-k",
        type=int,
        default=0,
        help="Build voting/stacking ensembles from top-K base models after CV (0=disabled). "
        "Requires soft_voting/weighted_voting/stacking in --model-pool.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "gpu", "mps", "auto"],
        help="Compute device. 'auto' selects MPS on Apple Silicon, CUDA GPU if available, else CPU. "
        "Affects XGBoost/LightGBM/CatBoost/TabPFN device placement.",
    )
    parser.add_argument(
        "--max-trials-per-family",
        type=int,
        default=1,
        help="Maximum hyperparameter candidates per model family.",
    )
    parser.add_argument(
        "--hyperparam-search",
        default="fixed_grid",
        choices=["random_subsample", "fixed_grid", "optuna"],
        help="Candidate search strategy within each family. "
        "'optuna' requires optuna package and uses Bayesian optimization.",
    )
    parser.add_argument(
        "--optuna-trials",
        type=int,
        default=50,
        help="Number of Optuna trials per family when --hyperparam-search=optuna (default: 50).",
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=-1,
        help="Parallel CPU workers for multi-core estimators (e.g., RF/XGBoost).",
    )
    parser.add_argument("--beta", type=float, default=2.0, help="Beta for F-beta threshold objective. Default 2.0 (F2: sensitivity-weighted, standard for medical screening).")
    parser.add_argument("--sensitivity-floor", type=float, default=0.70, help="Minimum sensitivity for threshold choice (default 0.70; performance-policy.example.json recommends 0.85 for publication-grade).")
    parser.add_argument("--npv-floor", type=float, default=0.70, help="Minimum NPV for threshold choice (default 0.70; performance-policy.example.json recommends 0.90 for publication-grade).")
    parser.add_argument("--specificity-floor", type=float, default=0.60, help="Minimum specificity for threshold choice (default 0.60; performance-policy.example.json uses 0.40).")
    parser.add_argument("--ppv-floor", type=float, default=0.50, help="Minimum PPV for threshold choice (default 0.50; performance-policy.example.json recommends 0.55).")
    parser.add_argument(
        "--class-weight-override",
        default="auto",
        choices=["auto", "none", "balanced"],
        help="Override class weight strategy. 'auto' uses balanced when imbalance ratio >= 1.5. "
        "'none' disables class weighting. 'balanced' always enables it.",
    )
    parser.add_argument(
        "--imbalance-strategy",
        default="",
        help=(
            "Explicit single imbalance strategy. Supported: "
            "auto,none,class_weight,random_oversample,random_undersample,smote,adasyn. "
            "If set, overrides --class-weight-override."
        ),
    )
    parser.add_argument(
        "--imbalance-strategy-candidates",
        default="",
        help=(
            "Comma-separated candidate imbalance strategies. Trainer probes each candidate and "
            "selects the best by --imbalance-selection-metric before model selection."
        ),
    )
    parser.add_argument(
        "--imbalance-selection-metric",
        default="pr_auc",
        choices=["pr_auc", "roc_auc"],
        help="Metric used to select the best imbalance strategy from candidates.",
    )
    parser.add_argument("--random-seed", type=int, default=20260225, help="Random seed.")
    parser.add_argument("--primary-metric", default="pr_auc", help="Primary optimization metric.")
    parser.add_argument("--bootstrap-resamples", type=int, default=500, help="Bootstrap samples for CI.")
    parser.add_argument("--ci-bootstrap-resamples", type=int, default=2000, help="Bootstrap samples for CI matrix report.")
    parser.add_argument("--permutation-resamples", type=int, default=300, help="Permutation samples for null metric.")
    parser.add_argument(
        "--fast-diagnostic-mode",
        action="store_true",
        help=(
            "Skip expensive publication-style summary computations (e.g., CI matrix) "
            "for fast seed-search diagnostics."
        ),
    )
    parser.add_argument(
        "--skip-preflight-check",
        action="store_true",
        help=argparse.SUPPRESS,  # Hidden: bypass pre-training gate verification (testing only)
    )
    parser.add_argument("--model-selection-report-out", required=True, help="Output model_selection_report.json.")
    parser.add_argument("--evaluation-report-out", required=True, help="Output evaluation_report.json.")
    parser.add_argument("--feature-group-spec", help="Optional feature_group_spec JSON path.")
    parser.add_argument("--feature-engineering-report-out", help="Optional feature_engineering_report JSON output path.")
    parser.add_argument(
        "--feature-engineering-mode",
        default="strict",
        choices=["strict", "moderate", "quick"],
        help="Feature engineering aggressiveness mode.",
    )
    parser.add_argument("--distribution-report-out", help="Optional distribution_report JSON output path.")
    parser.add_argument("--ci-matrix-report-out", help="Optional ci_matrix_report JSON output path.")
    parser.add_argument("--prediction-trace-out", help="Optional output prediction_trace CSV/CSV.GZ.")
    parser.add_argument("--external-cohort-spec", help="Optional external cohort spec JSON path.")
    parser.add_argument("--external-validation-report-out", help="Optional output external_validation_report.json.")
    parser.add_argument("--robustness-report-out", help="Optional output robustness_report.json.")
    parser.add_argument("--robustness-time-slices", type=int, default=4, help="Number of chronological slices for robustness report.")
    parser.add_argument("--robustness-group-count", type=int, default=4, help="Number of hash-based patient groups for robustness report.")
    parser.add_argument("--seed-sensitivity-out", help="Optional output seed_sensitivity_report.json.")
    parser.add_argument(
        "--seed-sensitivity-seeds",
        default="20260224,20260225,20260226,20260227,20260228",
        help="Comma-separated integer seeds for robustness sensitivity report.",
    )
    parser.add_argument("--model-out", help="Optional model artifact output path.")
    parser.add_argument("--model-pool-out", help="Optional multi-family model pool for SHAP interpretability gate.")
    parser.add_argument("--permutation-null-out", help="Optional null metric output file (one value per line).")
    parser.add_argument(
        "--low-memory",
        action="store_true",
        help="Enable low-memory mode: downcast numeric dtypes, release intermediate "
        "DataFrames early, and call gc.collect() at key pipeline stages.",
    )
    parser.add_argument(
        "--checkpoint-file",
        help="Path for saving/loading training checkpoint JSON.",
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        action="store_true",
        help="Resume training from an existing checkpoint file, "
        "skipping already-scored candidates.",
    )
    return parser.parse_args()


def ensure_parent(path: Path) -> None:
    """Create parent directories for a file path if they do not exist.

    Args:
        path: Target file path whose parents should be created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def load_policy(path: Optional[str]) -> Dict[str, Any]:
    """Load a performance policy JSON file.

    Args:
        path: Path to performance policy JSON, or None/empty for defaults.

    Returns:
        Parsed policy dictionary, or empty dict if path is falsy.

    Raises:
        ValueError: If JSON root is not an object.
    """
    if not path:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Performance policy not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in performance policy: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("performance policy JSON root must be object.")
    return payload


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file.

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hex digest string.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    """Compute SHA-256 hex digest of a UTF-8 string.

    Args:
        value: Input string.

    Returns:
        Lowercase hex digest string.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_ignore_cols(raw: str, target_col: str, definition_cols: str = "") -> List[str]:
    """Parse comma-separated ignore columns, always including the target.

    Args:
        raw: Comma-separated column names to ignore.
        target_col: Target column name (always included).
        definition_cols: Comma-separated outcome-definition columns (forcibly excluded).

    Returns:
        Sorted deduplicated list of columns to exclude from features.
    """
    out: List[str] = [target_col]
    for token in raw.split(","):
        key = token.strip()
        if key:
            out.append(key)
    # Forcibly exclude outcome-definition columns (prevents target leakage)
    excluded_definitions: List[str] = []
    for token in definition_cols.split(","):
        key = token.strip()
        if key:
            out.append(key)
            excluded_definitions.append(key)
    if excluded_definitions:
        print(
            f"[SAFE] definition_cols_excluded: {len(excluded_definitions)} outcome-definition "
            f"column(s) forcibly excluded from features: {excluded_definitions}",
            file=sys.stderr,
        )
    return sorted(set(out))


def parse_seed_list(raw: str, default_seed: int) -> List[int]:
    """Parse comma-separated integer seeds for multi-seed analysis.

    Args:
        raw: Comma-separated seed values.
        default_seed: Fallback seed if parsing yields nothing.

    Returns:
        Deduplicated list of integer seeds.
    """
    seeds: List[int] = []
    for token in str(raw).split(","):
        item = token.strip()
        if not item:
            continue
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value not in seeds:
            seeds.append(value)
    if not seeds:
        seeds = [int(default_seed)]
    return seeds


def _model_tokens_from_raw(raw: Any) -> List[str]:
    """Extract model family tokens from a string or list.

    Args:
        raw: Comma-separated string or list of model names.

    Returns:
        List of stripped non-empty model name tokens.
    """
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(part).strip() for part in raw]
    else:
        return []
    return [item for item in items if item]


def canonical_model_name(token: str) -> str:
    """Normalize a model name token to its canonical form.

    Args:
        token: Raw model name (may use aliases like 'rf', 'lr_l1').

    Returns:
        Canonical model family name.
    """
    key = str(token).strip().lower().replace("-", "_")
    return MODEL_ALIASES.get(key, key)


def parse_model_pool_config(policy: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Resolve model pool configuration from policy and CLI arguments.

    Args:
        policy: Performance policy dictionary (may contain model_pool block).
        args: Parsed CLI arguments.

    Returns:
        Resolved config dict with keys: model_pool, required_models,
        max_trials_per_family, search_strategy, n_jobs, etc.

    Raises:
        SystemExit: If an unsupported model family is requested.
    """
    default_models = [
        "logistic_l1",
        "logistic_l2",
        "logistic_elasticnet",
        "random_forest_balanced",
        "hist_gradient_boosting_l2",
    ]
    model_block = policy.get("model_pool") if isinstance(policy, dict) else None
    policy_models: List[str] = []
    policy_required_models: List[str] = []
    policy_include_optional = False
    policy_max_trials: Optional[int] = None
    policy_search: Optional[str] = None
    policy_n_jobs: Optional[int] = None

    if isinstance(model_block, dict):
        policy_models = _model_tokens_from_raw(model_block.get("models"))
        policy_required_models = _model_tokens_from_raw(model_block.get("required_models"))
        policy_include_optional = bool(model_block.get("include_optional_models", False))
        if isinstance(model_block.get("max_trials_per_family"), int):
            policy_max_trials = int(model_block["max_trials_per_family"])
        token = str(model_block.get("search_strategy", "")).strip().lower()
        if token in {"random_subsample", "fixed_grid", "optuna"}:
            policy_search = token
        if isinstance(model_block.get("n_jobs"), int):
            policy_n_jobs = int(model_block["n_jobs"])
    elif isinstance(model_block, list):
        policy_models = _model_tokens_from_raw(model_block)

    cli_models = _model_tokens_from_raw(args.model_pool)
    cli_model_pool_provided = bool(cli_models)
    policy_model_pool_provided = bool(policy_models)
    selected_tokens = cli_models or policy_models or list(default_models)
    explicit_model_pool_provided = bool(cli_model_pool_provided or policy_model_pool_provided)
    include_optional = bool(args.include_optional_models or policy_include_optional)
    if include_optional:
        # Fail-safe append: only add optional families that are actually available
        # in the current runtime. This keeps CLI semantics aligned with help text
        # ("append optional backends ... when installed") and avoids hard-fails
        # from implicitly adding unavailable families.
        optional_candidates = {
            "xgboost": XGBClassifier is not None,
            "catboost": CatBoostClassifier is not None,
            "lightgbm": LGBMClassifier is not None,
            "tabpfn": TabPFNClassifier is not None,
        }
        selected_tokens.extend([name for name, is_available in optional_candidates.items() if is_available])

    requested_normalized: List[str] = []
    for token in selected_tokens:
        name = canonical_model_name(token)
        if name not in SUPPORTED_MODEL_FAMILIES:
            raise SystemExit(f"Unsupported model family in model-pool: {token}")
        if name not in requested_normalized:
            requested_normalized.append(name)

    normalized = list(requested_normalized)
    required_tokens = policy_required_models or ([] if explicit_model_pool_provided else ["logistic_l2"])
    auto_added_required: List[str] = []
    for token in required_tokens:
        name = canonical_model_name(token)
        if name not in SUPPORTED_MODEL_FAMILIES:
            raise SystemExit(f"Unsupported required model family in performance policy: {token}")
        if name not in normalized:
            normalized.append(name)
            auto_added_required.append(name)

    search_strategy = (
        str(policy_search).strip().lower()
        if isinstance(policy_search, str) and policy_search
        else str(args.hyperparam_search).strip().lower()
    )
    if search_strategy not in {"random_subsample", "fixed_grid", "optuna"}:
        search_strategy = "random_subsample"

    max_trials_per_family = (
        int(policy_max_trials)
        if isinstance(policy_max_trials, int)
        else int(args.max_trials_per_family)
    )
    if max_trials_per_family < 1:
        max_trials_per_family = 1

    n_jobs = int(policy_n_jobs) if isinstance(policy_n_jobs, int) else int(args.n_jobs)
    if n_jobs == 0:
        n_jobs = 1

    return {
        "requested_models": list(requested_normalized),
        "model_pool": normalized,
        "required_models": [canonical_model_name(t) for t in required_tokens],
        "auto_added_required_models": auto_added_required,
        "include_optional_models": include_optional,
        "cli_model_pool_provided": cli_model_pool_provided,
        "policy_model_pool_provided": policy_model_pool_provided,
        "cli_models": [canonical_model_name(t) for t in cli_models],
        "policy_models": [canonical_model_name(t) for t in policy_models],
        "max_trials_per_family": int(max_trials_per_family),
        "search_strategy": search_strategy,
        "n_jobs": int(n_jobs),
        "optional_backends": {
            "xgboost_available": bool(XGBClassifier is not None),
            "catboost_available": bool(CatBoostClassifier is not None),
            "lightgbm_available": bool(LGBMClassifier is not None),
            "tabpfn_available": bool(TabPFNClassifier is not None),
        },
    }


def load_split(path: str) -> pd.DataFrame:
    """Load a CSV split file into a DataFrame.

    Args:
        path: Path to the CSV file.

    Returns:
        Loaded DataFrame.

    Raises:
        ValueError: If the split is empty.
    """
    p = Path(path).expanduser().resolve()
    # Security: file size check (max 2 GB)
    if p.exists():
        file_size = p.stat().st_size
        if file_size > 2 * 1024 * 1024 * 1024:
            raise ValueError(f"Split CSV too large: {file_size} bytes (limit 2 GB)")
    df = pd.read_csv(p)
    if df.empty:
        raise ValueError(f"Split is empty: {p}")
    return df


def load_external_cohort_spec(path: Optional[str]) -> Dict[str, Any]:
    """Load external cohort specification JSON.

    Args:
        path: Path to external cohort spec JSON, or None.

    Returns:
        Parsed spec dictionary, or empty dict if path is falsy.

    Raises:
        ValueError: If JSON root is not an object.
    """
    if not path:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"External cohort spec not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in external cohort spec: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("external cohort spec JSON root must be object.")
    return payload


def load_feature_group_spec(path: Optional[str]) -> Dict[str, Any]:
    """Load feature group specification JSON.

    Args:
        path: Path to feature_group_spec JSON, or None.

    Returns:
        Parsed spec dictionary, or empty dict if path is falsy.

    Raises:
        ValueError: If JSON root is not an object.
    """
    if not path:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Feature group spec not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in feature group spec: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("feature_group_spec JSON root must be object.")
    return payload


def normalize_feature_groups(payload: Dict[str, Any]) -> Tuple[Dict[str, List[str]], List[str]]:
    """Parse and normalize feature group spec into groups and forbidden features.

    Args:
        payload: Feature group spec dictionary.

    Returns:
        Tuple of (groups dict mapping group name to feature list,
        sorted list of forbidden feature names).
    """
    groups_raw = payload.get("groups")
    groups: Dict[str, List[str]] = {}
    if isinstance(groups_raw, dict):
        for key, values in groups_raw.items():
            if not isinstance(key, str) or not key.strip():
                continue
            # Support both old format (list) and new timing-aware format (dict with "features" key)
            if isinstance(values, dict) and "features" in values:
                values = values["features"]
            if not isinstance(values, list):
                continue
            clean = [str(x).strip() for x in values if isinstance(x, str) and str(x).strip()]
            if clean:
                groups[key.strip()] = clean
    forbidden_raw = payload.get("forbidden_features")
    forbidden = [str(x).strip() for x in forbidden_raw if isinstance(x, str) and str(x).strip()] if isinstance(forbidden_raw, list) else []
    return groups, sorted(set(forbidden))


def mode_config(mode: str) -> Dict[str, Any]:
    """Return feature engineering thresholds for a given mode.

    Args:
        mode: One of 'strict', 'moderate', 'quick'.

    Returns:
        Dict with max_missing_ratio, min_variance, group_keep_ratio,
        stability_repeats.
    """
    token = str(mode).strip().lower()
    if token == "quick":
        return {"max_missing_ratio": 0.80, "min_variance": 1e-10, "group_keep_ratio": 0.85, "stability_repeats": 15}
    if token == "moderate":
        return {"max_missing_ratio": 0.70, "min_variance": 1e-9, "group_keep_ratio": 0.70, "stability_repeats": 30}
    return {"max_missing_ratio": 0.60, "min_variance": 1e-8, "group_keep_ratio": 0.50, "stability_repeats": 50}


def select_features_by_filter(
    X_train: pd.DataFrame,
    features: Sequence[str],
    max_missing_ratio: float,
    min_variance: float,
) -> Tuple[List[str], Dict[str, Any]]:
    """Filter features by missingness ratio and variance thresholds.

    Args:
        X_train: Training feature DataFrame.
        features: Candidate feature names.
        max_missing_ratio: Drop features with missing ratio above this.
        min_variance: Drop features with variance at or below this.

    Returns:
        Tuple of (kept feature names, filter report dict).
    """
    kept: List[str] = []
    dropped_missing: List[str] = []
    dropped_low_variance: List[str] = []
    outlier_warnings: List[Dict[str, Any]] = []
    for feature in features:
        series = X_train[feature]
        missing_ratio = float(series.isna().mean())
        if not math.isfinite(missing_ratio) or missing_ratio > float(max_missing_ratio):
            dropped_missing.append(feature)
            continue
        # Skip variance check for non-numeric columns (they'll be encoded later)
        if series.dtype == object or str(series.dtype) == "category":
            kept.append(feature)
            continue
        numeric = pd.to_numeric(series, errors="coerce")
        variance = float(numeric.var(skipna=True)) if numeric.notna().any() else 0.0
        if not math.isfinite(variance) or variance <= float(min_variance):
            dropped_low_variance.append(feature)
            continue
        kept.append(feature)
        # Outlier detection (IQR method) — report only, no dropping
        valid = numeric.dropna()
        if len(valid) >= 20:
            q1 = float(valid.quantile(0.25))
            q3 = float(valid.quantile(0.75))
            if not (math.isfinite(q1) and math.isfinite(q3)):
                continue
            iqr = q3 - q1
            if iqr > 0:
                lower = q1 - 3.0 * iqr
                upper = q3 + 3.0 * iqr
                n_outliers = int(((valid < lower) | (valid > upper)).sum())
                outlier_pct = n_outliers / len(valid)
                if outlier_pct > 0.05:
                    outlier_warnings.append({
                        "feature": feature,
                        "outlier_count": n_outliers,
                        "outlier_pct": round(outlier_pct, 4),
                        "iqr_lower": round(lower, 4),
                        "iqr_upper": round(upper, 4),
                    })
    report = {
        "max_missing_ratio": float(max_missing_ratio),
        "min_variance": float(min_variance),
        "dropped_for_missingness": dropped_missing,
        "dropped_for_low_variance": dropped_low_variance,
        "kept_count": int(len(kept)),
        "outlier_warnings": outlier_warnings,
    }
    return kept, report


def detect_categorical_features(
    X: pd.DataFrame,
    features: Sequence[str],
    max_cardinality: int = 20,
) -> Dict[str, Any]:
    """Detect features that appear categorical based on cardinality and dtype.

    Args:
        X: Feature DataFrame (training set only).
        features: Feature names to analyze.
        max_cardinality: Features with unique values <= this are flagged.

    Returns:
        Dict with categorical feature report (feature names, cardinalities,
        coercion warnings for non-numeric categoricals).
    """
    categorical: List[Dict[str, Any]] = []
    coercion_warnings: List[str] = []
    high_cardinality_nominal: List[Dict[str, Any]] = []
    for feat in features:
        if feat not in X.columns:
            continue
        series = X[feat]
        nunique = int(series.nunique(dropna=True))
        is_numeric = pd.api.types.is_numeric_dtype(series)
        if nunique <= max_cardinality:
            # Keep numeric columns that look ordinal as numeric (not OneHot).
            # Two heuristics:
            #   a) Small consecutive integers (0,1,2,3 or 1,2,3,4,5) — Likert/severity
            #   b) Wide range with even gaps (0,10,20,...,100) — scores like scoma
            # Exclude sparse codes (1,2,50,100) where gaps vary wildly.
            if is_numeric and nunique >= 3:
                vals = sorted(series.dropna().unique())
                val_range = float(vals[-1] - vals[0])
                # (a) Small consecutive integers: range == nunique - 1
                if val_range <= nunique and all(float(v).is_integer() for v in vals):
                    continue  # ordinal integer scale (0-4, 1-5, etc.)
                # (b) Wide range with even gaps
                if val_range > nunique * 2 and len(vals) >= 3:
                    gaps = [float(vals[i+1] - vals[i]) for i in range(len(vals)-1)]
                    mean_gap = sum(gaps) / len(gaps)
                    std_gap = (sum((g - mean_gap)**2 for g in gaps) / len(gaps)) ** 0.5
                    if mean_gap > 0 and std_gap / mean_gap < 1.0:
                        continue  # evenly spaced ordinal (scoma 0-100)

            entry: Dict[str, Any] = {
                "feature": feat,
                "cardinality": nunique,
                "is_numeric": is_numeric,
            }
            if nunique <= 10:
                entry["values"] = sorted([str(v) for v in series.dropna().unique()])[:10]
            categorical.append(entry)
            if not is_numeric:
                coercion_warnings.append(feat)
        elif not is_numeric and nunique <= 100:
            # High-cardinality non-numeric: likely nominal but too many for OneHot
            high_cardinality_nominal.append({
                "feature": feat,
                "cardinality": nunique,
                "warning": f"Nominal feature with {nunique} categories (>max_onehot={max_cardinality}). "
                           f"Will be treated as numeric, which is WRONG for nominal data. "
                           f"Consider: (1) group rare categories, (2) increase max_onehot_cardinality, "
                           f"(3) use target encoding, (4) exclude this feature.",
            })
    return {
        "categorical_count": len(categorical),
        "categorical_features": categorical,
        "coercion_warnings": coercion_warnings,
        "high_cardinality_nominal": high_cardinality_nominal,
    }


def encode_categorical_features(
    X_train: pd.DataFrame,
    X_valid: pd.DataFrame,
    X_test: pd.DataFrame,
    categorical_report: Dict[str, Any],
    max_onehot_cardinality: int = 15,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, List[str]]:
    """OneHot-encode detected categorical features (fit on train only).

    Features with cardinality 2 are binary-encoded (single column, 0/1).
    Features with cardinality 3..max_onehot_cardinality are OneHot-encoded.
    Features with cardinality > max_onehot_cardinality are left as-is (ordinal).

    Args:
        X_train, X_valid, X_test: Feature DataFrames.
        categorical_report: Output of detect_categorical_features().
        max_onehot_cardinality: Maximum cardinality for OneHot encoding.

    Returns:
        Tuple of (X_train, X_valid, X_test, updated_feature_names).
    """
    cat_features = categorical_report.get("categorical_features", [])

    # Safety FIRST: force-encode ALL non-numeric columns to prevent Pipeline crash.
    # This runs BEFORE any other logic, catching string columns that escaped
    # detect_categorical_features() due to cardinality > max_cardinality.
    to_onehot: List[str] = []
    for feat in list(X_train.columns):
        if not pd.api.types.is_numeric_dtype(X_train[feat]):
            nunique = int(X_train[feat].nunique(dropna=True))
            if nunique <= max_onehot_cardinality * 2:  # up to 2x threshold: force OneHot
                if feat not in to_onehot:
                    to_onehot.append(feat)
            else:
                # Too many categories — convert to numeric codes as last resort.
                all_vals = sorted(str(v) for v in X_train[feat].dropna().unique())
                code_map = {v: float(i) for i, v in enumerate(all_vals)}
                for df in (X_train, X_valid, X_test):
                    if feat in df.columns and len(df) > 0:
                        df[feat] = df[feat].astype(str).map(code_map).fillna(-1.0).astype(float)
                print(f"  [WARN] Non-numeric '{feat}' ({nunique} cats) → numeric codes. "
                      f"Consider grouping or excluding.")

    if not cat_features and not to_onehot:
        return X_train, X_valid, X_test, list(X_train.columns)
    for entry in cat_features:
        feat = entry["feature"]
        card = entry["cardinality"]
        if feat not in X_train.columns:
            continue
        if card <= 1:
            continue
        if card == 2:
            # Binary: encode as 0/1 using the two train-observed values
            vals = sorted(X_train[feat].dropna().unique())
            if len(vals) == 2:
                mapping = {vals[0]: 0.0, vals[1]: 1.0}
                for df in (X_train, X_valid, X_test):
                    if df.empty or feat not in df.columns:
                        continue
                    mapped = df[feat].map(mapping)
                    ood_mask = mapped.isna() & df[feat].notna()
                    # OOD safety: fill with prevalence-neutral 0.5 (not 0.0)
                    # to avoid conflation with either binary class.
                    # Note: do NOT add _ood indicator columns here — they would
                    # pollute downstream feature selection and model training.
                    # OOD is handled via the 0.5 sentinel value only.
                    df[feat] = mapped.fillna(0.5).astype(float)
        elif card <= max_onehot_cardinality:
            to_onehot.append(feat)

    # Deduplicate to_onehot (a feature may be added by both the safety scan and cat_features)
    to_onehot = list(dict.fromkeys(to_onehot))

    if not to_onehot:
        return X_train, X_valid, X_test, list(X_train.columns)

    # Fit categories on train only
    train_categories: Dict[str, List[Any]] = {}
    for feat in to_onehot:
        cats = sorted(X_train[feat].dropna().unique())
        train_categories[feat] = cats

    def _apply_onehot(df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        for feat in to_onehot:
            cats = train_categories[feat]
            for cat in cats:
                col_name = f"{feat}_{cat}"
                result[col_name] = (result[feat] == cat).astype(float)
            # OOD safety: values not in train categories become all-zero dummies
            # (equivalent to "unknown" category — no signal, no leakage)
            result.drop(columns=[feat], inplace=True)
        return result

    X_train = _apply_onehot(X_train)
    X_valid = _apply_onehot(X_valid) if len(X_valid) > 0 else X_valid
    X_test = _apply_onehot(X_test) if len(X_test) > 0 else X_test

    return X_train, X_valid, X_test, list(X_train.columns)


def apply_categorical_encoding_to_external(
    df: pd.DataFrame,
    encoded_feature_names: List[str],
    original_feature_names: List[str],
) -> pd.DataFrame:
    """Apply train-fit categorical encoding to an external cohort DataFrame.

    If the external DataFrame has the original (pre-encoded) column names,
    this function detects OneHot patterns in encoded_feature_names and
    generates the corresponding dummy columns.

    Args:
        df: External cohort DataFrame (may have original or encoded columns).
        encoded_feature_names: Feature names after encoding (from train).
        original_feature_names: Feature names before encoding (raw).

    Returns:
        DataFrame with columns matching encoded_feature_names.
    """
    # If df already has the encoded columns, return as-is
    missing = set(encoded_feature_names) - set(df.columns)
    if not missing:
        return df[encoded_feature_names]

    # Detect OneHot groups: columns like "race_1", "race_2" → original "race"
    # Sort original names by length DESCENDING to match longest prefix first,
    # preventing "blood_pressure" from stealing "blood_pressure_systolic_high"
    onehot_groups: Dict[str, List[str]] = {}
    sorted_originals = sorted(
        [o for o in original_feature_names if o in df.columns],
        key=len, reverse=True,
    )
    for col in encoded_feature_names:
        if "_" in col:
            for orig in sorted_originals:
                prefix = f"{orig}_"
                if col.startswith(prefix) and col != orig:
                    # Verify the suffix is a category value, not another feature name
                    suffix = col[len(prefix):]
                    # Exclude if suffix itself is a known original feature name
                    if suffix not in set(original_feature_names):
                        onehot_groups.setdefault(orig, []).append(col)
                        break

    result = df.copy()
    for orig, dummy_cols in onehot_groups.items():
        if orig not in result.columns:
            continue
        for dcol in dummy_cols:
            # Extract category value from column name: "race_3" → "3"
            cat_val_str = dcol[len(orig) + 1:]
            # Compare as-is first; if column is numeric, also try numeric cast
            col_vals = result[orig]
            matched = col_vals == cat_val_str
            if not matched.any():
                try:
                    cat_val_num = float(cat_val_str)
                    matched = col_vals == cat_val_num
                except (ValueError, TypeError):
                    pass
            result[dcol] = matched.astype(float)
        result.drop(columns=[orig], errors="ignore", inplace=True)

    # Fill missing columns with NaN (not 0) so caller can fill with train medians.
    # Using 0 for physiological features (waist circumference, blood pressure)
    # creates impossible values that bias predictions.
    for col in encoded_feature_names:
        if col not in result.columns:
            result[col] = np.nan

    return result[encoded_feature_names]


def impute_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Impute all columns with median after coercing to numeric.

    Args:
        df: Input DataFrame.

    Returns:
        DataFrame with all columns coerced to numeric and median-imputed.
    """
    out = df.copy()
    for col in out.columns:
        series = pd.to_numeric(out[col], errors="coerce")
        median = float(series.median(skipna=True)) if series.notna().any() else 0.0
        out[col] = series.fillna(median)
    return out


def _class_counts(y: np.ndarray) -> Tuple[int, int, int, int]:
    """Return positive/negative/minority/majority counts for binary labels."""
    y_int = np.asarray(y, dtype=int)
    pos = int(np.sum(y_int == 1))
    neg = int(np.sum(y_int == 0))
    minority = int(min(pos, neg))
    majority = int(max(pos, neg))
    return pos, neg, minority, majority


def resolve_imbalance_strategy_candidates(
    candidates_arg: str,
    single_arg: str,
    class_weight_override: str,
    imbalance_ratio: float,
) -> List[str]:
    """Resolve requested imbalance strategy candidates to concrete supported tokens."""
    requested: List[str] = []
    if isinstance(candidates_arg, str) and candidates_arg.strip():
        requested.extend([token.strip().lower() for token in candidates_arg.split(",") if token.strip()])
    elif isinstance(single_arg, str) and single_arg.strip():
        requested.append(single_arg.strip().lower())
    else:
        legacy = str(class_weight_override).strip().lower()
        if legacy == "balanced":
            requested.append("class_weight")
        elif legacy == "none":
            requested.append("none")
        else:
            requested.append("auto")
    if not requested:
        requested = ["auto"]

    resolved: List[str] = []
    for token in requested:
        strategy = token
        if strategy == "balanced":
            strategy = "class_weight"
        if strategy == "auto":
            strategy = "class_weight" if float(imbalance_ratio) >= 1.5 else "none"
        if strategy not in SUPPORTED_IMBALANCE_STRATEGIES:
            raise SystemExit(
                f"unsupported_imbalance_strategy: '{token}'. "
                f"supported={sorted(SUPPORTED_IMBALANCE_STRATEGIES)}"
            )
        if strategy not in resolved:
            resolved.append(strategy)
    return resolved


def _random_oversample(
    X: pd.DataFrame,
    y: np.ndarray,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Randomly oversample minority class to match majority count."""
    y_int = np.asarray(y, dtype=int)
    unique = np.unique(y_int)
    if unique.shape[0] < 2:
        return X, y_int
    rng = np.random.default_rng(int(seed))
    counts = {int(label): int(np.sum(y_int == label)) for label in unique}
    minority_label = min(counts, key=counts.get)
    majority_label = max(counts, key=counts.get)
    minority_idx = np.where(y_int == minority_label)[0]
    majority_idx = np.where(y_int == majority_label)[0]
    need = int(majority_idx.shape[0] - minority_idx.shape[0])
    if need <= 0:
        return X, y_int
    sampled = rng.choice(minority_idx, size=need, replace=True)
    X_new = pd.concat([X, X.iloc[sampled].copy()], axis=0, ignore_index=True)
    y_new = np.concatenate([y_int, y_int[sampled]], axis=0).astype(int)
    return X_new, y_new


def _random_undersample(
    X: pd.DataFrame,
    y: np.ndarray,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Randomly undersample majority class to match minority count."""
    y_int = np.asarray(y, dtype=int)
    unique = np.unique(y_int)
    if unique.shape[0] < 2:
        return X, y_int
    rng = np.random.default_rng(int(seed))
    counts = {int(label): int(np.sum(y_int == label)) for label in unique}
    minority_label = min(counts, key=counts.get)
    majority_label = max(counts, key=counts.get)
    minority_idx = np.where(y_int == minority_label)[0]
    majority_idx = np.where(y_int == majority_label)[0]
    keep_majority = int(minority_idx.shape[0])
    if keep_majority <= 0 or majority_idx.shape[0] <= keep_majority:
        return X, y_int
    sampled_majority = rng.choice(majority_idx, size=keep_majority, replace=False)
    keep_idx = np.concatenate([minority_idx, sampled_majority], axis=0)
    rng.shuffle(keep_idx)
    X_new = X.iloc[keep_idx].reset_index(drop=True)
    y_new = y_int[keep_idx].astype(int)
    return X_new, y_new


def _smote_oversample(
    X: pd.DataFrame,
    y: np.ndarray,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Perform simple SMOTE-style oversampling on a numeric-imputed feature space."""
    y_int = np.asarray(y, dtype=int)
    unique = np.unique(y_int)
    if unique.shape[0] < 2:
        return X, y_int
    counts = {int(label): int(np.sum(y_int == label)) for label in unique}
    minority_label = min(counts, key=counts.get)
    majority_label = max(counts, key=counts.get)
    minority_idx = np.where(y_int == minority_label)[0]
    majority_idx = np.where(y_int == majority_label)[0]
    need = int(majority_idx.shape[0] - minority_idx.shape[0])
    if need <= 0:
        return X, y_int
    if minority_idx.shape[0] < 2:
        return _random_oversample(X, y_int, seed)

    X_num = impute_numeric_frame(X)
    X_min = X_num.iloc[minority_idx].to_numpy(dtype=float)
    k = int(min(5, X_min.shape[0] - 1))
    if k < 1:
        return _random_oversample(X_num, y_int, seed)
    rng = np.random.default_rng(int(seed))
    nn = NearestNeighbors(n_neighbors=k + 1)
    nn.fit(X_min)
    neighbors = nn.kneighbors(X_min, return_distance=False)
    synth_rows: List[np.ndarray] = []
    for _ in range(need):
        base_local = int(rng.integers(0, X_min.shape[0]))
        neigh_local_pool = [idx for idx in neighbors[base_local].tolist() if idx != base_local]
        if not neigh_local_pool:
            neigh_local = base_local
        else:
            neigh_local = int(rng.choice(neigh_local_pool))
        lam = float(rng.random())
        x_base = X_min[base_local]
        x_neigh = X_min[neigh_local]
        synth_rows.append(x_base + lam * (x_neigh - x_base))
    X_syn = pd.DataFrame(np.vstack(synth_rows), columns=X_num.columns)
    X_new = pd.concat([X_num.reset_index(drop=True), X_syn], axis=0, ignore_index=True)
    y_new = np.concatenate(
        [y_int, np.full(shape=len(synth_rows), fill_value=int(minority_label), dtype=int)],
        axis=0,
    )
    return X_new, y_new


def _adasyn_oversample(
    X: pd.DataFrame,
    y: np.ndarray,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Perform ADASYN-style adaptive oversampling on numeric-imputed features."""
    y_int = np.asarray(y, dtype=int)
    unique = np.unique(y_int)
    if unique.shape[0] < 2:
        return X, y_int
    counts = {int(label): int(np.sum(y_int == label)) for label in unique}
    minority_label = min(counts, key=counts.get)
    majority_label = max(counts, key=counts.get)
    minority_idx = np.where(y_int == minority_label)[0]
    majority_idx = np.where(y_int == majority_label)[0]
    need = int(majority_idx.shape[0] - minority_idx.shape[0])
    if need <= 0:
        return X, y_int
    if minority_idx.shape[0] < 2:
        return _random_oversample(X, y_int, seed)

    X_num = impute_numeric_frame(X)
    X_arr = X_num.to_numpy(dtype=float)
    rng = np.random.default_rng(int(seed))

    k_all = int(min(5, max(1, X_arr.shape[0] - 1)))
    nn_all = NearestNeighbors(n_neighbors=k_all + 1)
    nn_all.fit(X_arr)

    r_vals: List[float] = []
    for idx in minority_idx:
        neigh = nn_all.kneighbors(X_arr[idx].reshape(1, -1), return_distance=False)[0].tolist()
        neigh = [n for n in neigh if int(n) != int(idx)]
        if not neigh:
            r_vals.append(1.0)
            continue
        majority_neigh = sum(1 for n in neigh if int(y_int[n]) == int(majority_label))
        r_vals.append(float(majority_neigh) / float(len(neigh)))
    r = np.asarray(r_vals, dtype=float)
    if not np.any(np.isfinite(r)) or float(np.sum(r)) <= 0.0:
        return _smote_oversample(X_num, y_int, seed)
    r = np.clip(r, a_min=0.0, a_max=None)
    if float(np.sum(r)) <= 0.0:
        return _smote_oversample(X_num, y_int, seed)
    r_norm = r / float(np.sum(r))
    raw_g = r_norm * float(need)
    g = np.floor(raw_g).astype(int)
    remaining = int(need - int(np.sum(g)))
    if remaining > 0:
        order = np.argsort(raw_g - g)[::-1]
        for idx in order[:remaining]:
            g[int(idx)] += 1

    X_min = X_arr[minority_idx]
    k_min = int(min(5, max(1, X_min.shape[0] - 1)))
    if k_min < 1:
        return _random_oversample(X_num, y_int, seed)
    nn_min = NearestNeighbors(n_neighbors=k_min + 1)
    nn_min.fit(X_min)
    neigh_min = nn_min.kneighbors(X_min, return_distance=False)

    synth_rows: List[np.ndarray] = []
    for local_idx, gen_count in enumerate(g.tolist()):
        if int(gen_count) <= 0:
            continue
        pool = [j for j in neigh_min[local_idx].tolist() if j != local_idx]
        for _ in range(int(gen_count)):
            if pool:
                neigh_local = int(rng.choice(pool))
            else:
                neigh_local = int(local_idx)
            lam = float(rng.random())
            x_base = X_min[local_idx]
            x_neigh = X_min[neigh_local]
            synth_rows.append(x_base + lam * (x_neigh - x_base))

    if len(synth_rows) < need:
        extra_need = int(need - len(synth_rows))
        extra_idx = rng.choice(minority_idx, size=extra_need, replace=True)
        extra = X_num.iloc[extra_idx].to_numpy(dtype=float)
        synth_rows.extend(list(extra))

    X_syn = pd.DataFrame(np.vstack(synth_rows[:need]), columns=X_num.columns)
    X_new = pd.concat([X_num.reset_index(drop=True), X_syn], axis=0, ignore_index=True)
    y_new = np.concatenate(
        [y_int, np.full(shape=int(X_syn.shape[0]), fill_value=int(minority_label), dtype=int)],
        axis=0,
    )
    return X_new, y_new


def apply_imbalance_strategy_to_train(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    strategy: str,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray, Dict[str, Any]]:
    """Apply a leakage-safe imbalance strategy on training data only."""
    token = str(strategy).strip().lower()
    if token not in SUPPORTED_IMBALANCE_STRATEGIES:
        raise ValueError(f"Unsupported imbalance strategy: {token}")
    y_int = np.asarray(y_train, dtype=int)
    pos, neg, minority, majority = _class_counts(y_int)
    meta: Dict[str, Any] = {
        "strategy": token,
        "input_rows": int(X_train.shape[0]),
        "input_positive": int(pos),
        "input_negative": int(neg),
    }
    if token in {"none", "class_weight"}:
        meta["resampled"] = False
        meta["output_rows"] = int(X_train.shape[0])
        return X_train, y_int, meta
    if minority <= 0 or majority <= 0 or minority == majority:
        meta["resampled"] = False
        meta["output_rows"] = int(X_train.shape[0])
        meta["fallback_reason"] = "class_counts_not_resamplable"
        return X_train, y_int, meta
    if token == "random_oversample":
        X_fit, y_fit = _random_oversample(X_train, y_int, seed)
    elif token == "random_undersample":
        X_fit, y_fit = _random_undersample(X_train, y_int, seed)
    elif token == "smote":
        X_fit, y_fit = _smote_oversample(X_train, y_int, seed)
    elif token == "adasyn":
        X_fit, y_fit = _adasyn_oversample(X_train, y_int, seed)
    else:
        X_fit, y_fit = X_train, y_int
    pos_out, neg_out, _, _ = _class_counts(y_fit)
    meta["resampled"] = bool(int(X_fit.shape[0]) != int(X_train.shape[0]))
    meta["output_rows"] = int(X_fit.shape[0])
    meta["output_positive"] = int(pos_out)
    meta["output_negative"] = int(neg_out)
    return X_fit, y_fit, meta


def fit_estimator_with_imbalance(
    estimator: BaseEstimator,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    strategy: str,
    seed: int,
) -> Tuple[BaseEstimator, Dict[str, Any]]:
    """Fit an estimator on a training set after applying imbalance strategy.

    For class_weight strategy with XGBoost (which doesn't accept
    class_weight="balanced"), computes scale_pos_weight from the
    actual class distribution and sets it before fitting.
    """
    X_fit, y_fit, meta = apply_imbalance_strategy_to_train(X_train, y_train, strategy=strategy, seed=int(seed))
    # XGBoost class_weight fix: set scale_pos_weight from actual data
    if str(strategy).strip().lower() == "class_weight":
        _apply_xgb_scale_pos_weight(estimator, y_fit)
    estimator.fit(X_fit, y_fit)
    return estimator, meta


def _apply_xgb_scale_pos_weight(estimator: BaseEstimator, y: np.ndarray) -> None:
    """Set scale_pos_weight on XGBoost classifiers inside Pipelines.

    XGBoost does not accept class_weight='balanced' like sklearn estimators.
    This function computes n_negative/n_positive and applies it.
    """
    from sklearn.pipeline import Pipeline
    if isinstance(estimator, Pipeline):
        clf = estimator.named_steps.get("clf", estimator)
    else:
        clf = estimator
    if XGBClassifier is not None and isinstance(clf, XGBClassifier):
        y_int = np.asarray(y, dtype=int)
        n_pos = int(np.sum(y_int == 1))
        n_neg = int(np.sum(y_int == 0))
        if n_pos > 0:
            clf.set_params(scale_pos_weight=float(n_neg) / float(n_pos))


def feature_stability_frequency(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    features: Sequence[str],
    repeats: int,
    seed: int,
) -> Dict[str, float]:
    """Estimate feature selection frequency via L1 bootstrap stability.

    Args:
        X_train: Training feature DataFrame.
        y_train: Binary target array.
        features: Feature names to evaluate.
        repeats: Number of bootstrap repetitions.
        seed: Random seed for reproducibility.

    Returns:
        Dict mapping feature name to selection frequency in [0, 1].
    """
    if not features:
        return {}
    rng = np.random.default_rng(seed)
    counts = {feature: 0 for feature in features}
    effective = 0
    y = np.asarray(y_train, dtype=int)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    if pos_idx.size == 0 or neg_idx.size == 0:
        return {feature: 0.0 for feature in features}

    # Precompute global train medians to avoid leaking bootstrap-local statistics.
    _global_medians: Dict[str, float] = {}
    for col in features:
        series = pd.to_numeric(X_train[col], errors="coerce")
        _global_medians[col] = float(series.median(skipna=True)) if series.notna().any() else 0.0

    def _impute_with_global_medians(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            series = pd.to_numeric(out[col], errors="coerce")
            out[col] = series.fillna(_global_medians.get(col, 0.0))
        return out

    for repeat_idx in range(int(repeats)):
        sample_pos = rng.choice(pos_idx, size=max(1, int(0.8 * pos_idx.size)), replace=True)
        sample_neg = rng.choice(neg_idx, size=max(1, int(0.8 * neg_idx.size)), replace=True)
        idx = np.concatenate([sample_pos, sample_neg], axis=0)
        rng.shuffle(idx)
        X_sub = _impute_with_global_medians(X_train.iloc[idx][list(features)])
        y_sub = y[idx]
        try:
            model = LogisticRegression(
                penalty="l1",
                solver="liblinear",
                C=0.3,
                class_weight="balanced",
                max_iter=3000,
                random_state=seed + repeat_idx,
            )
            model.fit(X_sub, y_sub)
            coef = np.asarray(model.coef_).reshape(-1)
            for feature, value in zip(features, coef):
                if math.isfinite(float(value)) and abs(float(value)) > 1e-10:
                    counts[feature] += 1
            effective += 1
        except Exception as exc:
            print(f"[WARN] feature stability fit failed (repeat {repeat_idx}): {exc}", file=sys.stderr)
            continue
    if effective <= 0:
        return {feature: 0.0 for feature in features}
    return {feature: float(counts[feature]) / float(effective) for feature in features}


def group_preselect_features(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    features: Sequence[str],
    groups: Dict[str, List[str]],
    keep_ratio: float,
    stability_frequency: Dict[str, float],
) -> Tuple[List[str], Dict[str, Any]]:
    """Select top features per group using correlation and stability scores.

    Args:
        X_train: Training feature DataFrame.
        y_train: Binary target array.
        features: Candidate feature names (post-filter).
        groups: Feature group spec mapping group name to feature list.
        keep_ratio: Fraction of features to keep per group.
        stability_frequency: Per-feature selection frequency from bootstrap.

    Returns:
        Tuple of (selected feature names, group selection report dict).
    """
    if not groups:
        return list(features), {"groups": {}, "fallback": "no_groups_provided"}

    y = np.asarray(y_train, dtype=float)
    report_groups: Dict[str, Any] = {}
    selected: List[str] = []
    feature_set = set(features)

    for group_name, group_features in groups.items():
        available = [f for f in group_features if f in feature_set]
        if not available:
            report_groups[group_name] = {
                "declared_count": len(group_features),
                "available_count": 0,
                "selected_count": 0,
                "selected_features": [],
            }
            continue

        # Always keep string/categorical columns — they'll be encoded later.
        # Only rank numeric columns by correlation + stability.
        auto_keep = [f for f in available if not pd.api.types.is_numeric_dtype(X_train[f])]
        rankable = [f for f in available if pd.api.types.is_numeric_dtype(X_train[f])]

        scored: List[Tuple[str, float, float, float]] = []
        for feature in rankable:
            series = pd.to_numeric(X_train[feature], errors="coerce")
            if series.notna().any():
                corr = abs(float(series.fillna(series.median(skipna=True)).corr(pd.Series(y))))
                if not math.isfinite(corr):
                    corr = 0.0
            else:
                corr = 0.0
            freq = float(stability_frequency.get(feature, 0.0))
            combined = 0.70 * corr + 0.30 * freq
            scored.append((feature, combined, corr, freq))

        scored = sorted(scored, key=lambda x: (x[1], x[2], x[3], x[0]), reverse=True)
        keep_n = max(1, int(math.ceil(float(keep_ratio) * float(len(scored)))))
        keep_n = min(keep_n, len(scored))
        chosen = auto_keep + [item[0] for item in scored[:keep_n]]
        selected.extend(chosen)
        report_groups[group_name] = {
            "declared_count": len(group_features),
            "available_count": len(available),
            "auto_kept_categorical": auto_keep,
            "selected_count": len(chosen),
            "selected_features": chosen,
            "ranked_features": [
                {
                    "feature": feature,
                    "combined_score": float(combined),
                    "corr_abs": float(corr),
                    "selection_frequency": float(freq),
                }
                for feature, combined, corr, freq in scored
            ],
        }

    dedup_selected = sorted(dict.fromkeys(selected))
    if not dedup_selected:
        dedup_selected = sorted(features)
    report = {"groups": report_groups, "selected_feature_count": len(dedup_selected)}
    return dedup_selected, report


def select_feature_columns(train_df: pd.DataFrame, ignore_cols: Sequence[str]) -> List[str]:
    """Select feature columns by excluding ignore columns.

    Args:
        train_df: Training DataFrame.
        ignore_cols: Column names to exclude.

    Returns:
        List of feature column names.

    Raises:
        ValueError: If no feature columns remain.
    """
    ignore = set(ignore_cols)
    out = [c for c in train_df.columns if c not in ignore]
    if not out:
        raise ValueError("No feature columns remain after ignore-cols exclusion.")
    return out


def prepare_xy(df: pd.DataFrame, feature_cols: Sequence[str], target_col: str) -> Tuple[pd.DataFrame, np.ndarray]:
    """Extract feature matrix X and binary target array y from a DataFrame.

    Args:
        df: Source DataFrame.
        feature_cols: Feature column names.
        target_col: Binary target column name.

    Returns:
        Tuple of (X DataFrame, y int array).

    Raises:
        ValueError: If target or feature columns are missing, target
            contains non-finite values, or target is not binary (0/1).
    """
    if target_col not in df.columns:
        raise ValueError(f"Missing target column: {target_col}")
    missing_features = [c for c in feature_cols if c not in df.columns]
    if missing_features:
        raise ValueError(f"Missing feature columns: {missing_features[:10]}")
    X = df[list(feature_cols)].copy()
    y = pd.to_numeric(df[target_col], errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(y)):
        raise ValueError("Target contains non-finite values.")
    if not np.all(np.isin(y, [0.0, 1.0])):
        raise ValueError("Target must be binary (0/1).")
    return X, y.astype(int)


def build_imputer(
    imputation_strategy: str,
    seed: int,
    native_missing_support: bool = False,
) -> BaseEstimator:
    """Build an imputer estimator based on the resolved strategy.

    Args:
        imputation_strategy: 'mice' for IterativeImputer, 'passthrough' to
            skip imputation (for models with native missing support),
            otherwise SimpleImputer with median strategy and missing indicator.
        seed: Random seed for MICE.
        native_missing_support: If True and strategy is not 'mice', use
            SimpleImputer without add_indicator (tree models handle NaN
            natively via XGBoost/LightGBM/HistGBM split direction).

    Returns:
        Configured imputer estimator.
    """
    if imputation_strategy == "mice":
        # MICE (Multiple Imputation by Chained Equations) via IterativeImputer.
        # Ref: van Buuren 2018, Flexible Imputation of Missing Data 2nd ed.,
        #      Ch.4 (Multivariate Missing Data), §4.5.6 (Number of iterations);
        #      White IR, Royston P, Wood AM. Stat Med 2011;30:377-399.
        #
        # max_iter=50: van Buuren recommends 50-100 for convergence with >10%
        #   missing. sklearn default (10) and our previous 20 produced
        #   ConvergenceWarnings on NHANES BP data (17.5% missing).
        # tol=1e-3: early stopping when imputed values stabilize.
        # sample_posterior=False: deterministic single imputation. For multiple
        #   imputation with Rubin's Rules, set True and run m=5-20 times.
        # initial_strategy="median": safe initialization for skewed medical data.
        # imputation_order="ascending": fill low-missing features first so
        #   high-missing features benefit from more complete covariates.
        return IterativeImputer(
            random_state=seed,
            max_iter=50,
            tol=1e-3,
            initial_strategy="median",
            sample_posterior=False,
            imputation_order="ascending",
            # Biological floor: prevent physiologically impossible imputed values.
            # Conservative bounds (wider than clinical normal ranges).
            min_value=0.0,
        )
    if native_missing_support:
        # Tree-based models (XGB, LGBM, HistGBM, CatBoost) handle NaN natively.
        # Use SimpleImputer only as safety net (no add_indicator — the model
        # already learns from missingness through its split mechanism).
        return SimpleImputer(strategy="median", add_indicator=False)
    return SimpleImputer(strategy="median", add_indicator=True)


def _deterministic_family_rng_seed(base_seed: int, family: str) -> int:
    """Derive a deterministic per-family RNG seed from a base seed.

    Args:
        base_seed: Global random seed.
        family: Model family name.

    Returns:
        Integer seed derived via SHA-256.
    """
    digest = hashlib.sha256(f"{family}|{int(base_seed)}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _sample_family_params(
    family: str,
    grid: List[Dict[str, Any]],
    max_trials: int,
    strategy: str,
    sampling_seed: int,
) -> List[Dict[str, Any]]:
    """Sample hyperparameter configurations from a family grid.

    Args:
        family: Model family name (used for deterministic seed).
        grid: Full hyperparameter grid.
        max_trials: Maximum configurations to return.
        strategy: 'fixed_grid' (prefix) or 'random_subsample'.
        sampling_seed: Base seed for random subsampling.

    Returns:
        List of selected hyperparameter dicts.
    """
    if not grid:
        return []
    if len(grid) <= max_trials:
        return list(grid)
    if strategy == "fixed_grid":
        return list(grid[:max_trials])
    rng = np.random.default_rng(_deterministic_family_rng_seed(sampling_seed, family))
    chosen_idx = rng.choice(np.arange(len(grid)), size=int(max_trials), replace=False)
    selected = [grid[int(idx)] for idx in sorted(chosen_idx.tolist())]
    return selected


def _optuna_search_family(
    family: str,
    X_train: "pd.DataFrame",
    y_train: "np.ndarray",
    n_trials: int,
    seed: int,
    imputation_strategy: str,
    class_weight: Optional[str],
    n_jobs: int,
    cv_splits: int,
    device: str = "cpu",
    temporal_cv: bool = False,
) -> List[Dict[str, Any]]:
    """Run Optuna Bayesian search for a single model family.

    Args:
        family: Model family name.
        X_train: Training feature DataFrame.
        y_train: Binary target array.
        n_trials: Number of Optuna trials.
        seed: Random seed.
        imputation_strategy: Imputation method for pipeline.
        class_weight: 'balanced' or None.
        n_jobs: Parallel workers for estimator.
        cv_splits: Number of CV folds for scoring.
        device: Compute device string.

    Returns:
        List of top hyperparameter dicts from the study.

    Raises:
        RuntimeError: If optuna is not installed.
    """
    if optuna is None:
        raise RuntimeError("optuna is not installed. Install with `pip install optuna`.")

    def _suggest_params(trial: "optuna.Trial") -> Dict[str, Any]:
        """Suggest hyperparameters for the current family via Optuna trial.

        Args:
            trial: Optuna trial object for parameter suggestion.

        Returns:
            Hyperparameter dict for the current family.
        """
        if family in {"logistic_l1", "logistic_l2"}:
            return {"C": trial.suggest_float("C", 0.001, 10.0, log=True)}
        if family == "logistic_elasticnet":
            return {"C": trial.suggest_float("C", 0.01, 5.0, log=True), "l1_ratio": trial.suggest_float("l1_ratio", 0.1, 0.9)}
        if family in {"random_forest_balanced", "extra_trees_balanced"}:
            return {
                "n_estimators": trial.suggest_int("n_estimators", 100, 800, step=50),
                "max_depth": trial.suggest_int("max_depth", 3, 12),
                "min_samples_split": trial.suggest_int("min_samples_split", 2, 20),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 3, 20),
                "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", 0.5]),
            }
        if family == "hist_gradient_boosting_l2":
            return {
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "max_depth": trial.suggest_int("max_depth", 2, 8),
                "max_iter": trial.suggest_int("max_iter", 100, 800, step=50),
                "l2_regularization": trial.suggest_float("l2_regularization", 0.1, 30.0, log=True),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 5, 40),
            }
        if family == "adaboost":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 50, 500, step=50),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 1.0, log=True),
                "max_depth": trial.suggest_int("max_depth", 1, 4),
            }
        if family == "xgboost":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 100, 800, step=50),
                "max_depth": trial.suggest_int("max_depth", 2, 8),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            }
        if family == "catboost":
            return {
                "iterations": trial.suggest_int("iterations", 100, 800, step=50),
                "depth": trial.suggest_int("depth", 3, 8),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 30.0, log=True),
                "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
            }
        if family == "lightgbm":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 100, 800, step=50),
                "max_depth": -1,
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "num_leaves": trial.suggest_int("num_leaves", 8, 128),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            }
        if family in {"svm_linear", "svm_rbf"}:
            params: Dict[str, Any] = {"C": trial.suggest_float("C", 0.001, 100.0, log=True)}
            if family == "svm_rbf":
                params["gamma"] = trial.suggest_categorical("gamma", ["scale", "auto", 0.01, 0.001, 0.0001])
            return params
        return {}

    def objective(trial: "optuna.Trial") -> float:
        """Optuna objective: return mean CV PR-AUC for trial params.

        Args:
            trial: Optuna trial object.

        Returns:
            Mean CV PR-AUC score, or 0.0 on failure.
        """
        params = _suggest_params(trial)
        if not params:
            return 0.0
        try:
            est = _build_estimator_for_family(
                family=family, params=params, seed=seed,
                imputation_strategy=imputation_strategy,
                class_weight=class_weight, n_jobs=n_jobs, device=device,
            )
            mean_score, _, _, _ = cv_score_pr_auc(est, X_train, y_train, n_splits=cv_splits, seed=seed, temporal_cv=temporal_cv)
            return float(mean_score)
        except Exception as exc:
            print(f"[WARN] optuna trial failed for {family}: {exc}", file=sys.stderr)
            return 0.0

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best_trials = sorted(study.trials, key=lambda t: t.value if t.value is not None else 0.0, reverse=True)
    results: List[Dict[str, Any]] = []
    for t in best_trials[:max(1, n_trials // 5)]:
        if t.params:
            results.append(dict(t.params))
    return results if results else [dict(study.best_trial.params)]


def _family_grid(family: str) -> List[Dict[str, Any]]:
    """Return the full hyperparameter grid for a model family.

    Args:
        family: Canonical model family name.

    Returns:
        List of hyperparameter dicts for grid/random search.

    Raises:
        ValueError: If the family is unsupported.
    """
    if family == "logistic_l1":
        return [{"C": c} for c in [0.3, 0.1, 0.03, 1.0, 3.0]]
    if family == "logistic_l2":
        return [{"C": c} for c in [1.0, 0.3, 0.1, 0.03, 3.0]]
    if family == "logistic_elasticnet":
        seed_first = [{"C": 0.8, "l1_ratio": 0.5}]
        rest = [
            {"C": c, "l1_ratio": l1_ratio}
            for c, l1_ratio in product([0.1, 0.3, 1.5, 0.05], [0.2, 0.5, 0.8])
        ]
        return seed_first + rest
    if family == "random_forest_balanced":
        seed_first = [
            {
                "n_estimators": 200,
                "max_depth": 4,
                "min_samples_split": 20,
                "min_samples_leaf": 10,
                "max_features": "sqrt",
            }
        ]
        rest = [
            {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "min_samples_split": min_samples_split,
                "min_samples_leaf": min_samples_leaf,
                "max_features": max_features,
            }
            for n_estimators, max_depth, min_samples_split, min_samples_leaf, max_features in product(
                [200, 400, 700],
                [4, 6, 9],
                [10, 20],
                [5, 10, 20],
                ["sqrt", 0.6],
            )
            if not (
                int(n_estimators) == 200
                and int(max_depth) == 4
                and int(min_samples_split) == 20
                and int(min_samples_leaf) == 10
                and str(max_features) == "sqrt"
            )
        ]
        return seed_first + rest
    if family == "extra_trees_balanced":
        return [
            {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "min_samples_split": min_samples_split,
                "min_samples_leaf": min_samples_leaf,
                "max_features": max_features,
            }
            for n_estimators, max_depth, min_samples_split, min_samples_leaf, max_features in product(
                [200, 400, 700],
                [5, 8, None],
                [8, 16],
                [4, 8, 16],
                ["sqrt", 0.7],
            )
        ]
    if family == "hist_gradient_boosting_l2":
        seed_first = [
            {
                "learning_rate": 0.03,
                "max_depth": 3,
                "max_iter": 180,
                "l2_regularization": 5.0,
                "min_samples_leaf": 20,
            }
        ]
        rest = [
            {
                "learning_rate": learning_rate,
                "max_depth": max_depth,
                "max_iter": max_iter,
                "l2_regularization": l2_regularization,
                "min_samples_leaf": min_samples_leaf,
            }
            for learning_rate, max_depth, max_iter, l2_regularization, min_samples_leaf in product(
                [0.02, 0.03, 0.05, 0.08],
                [2, 3, 4],
                [120, 180, 260, 360],
                [1.0, 5.0, 10.0],
                [20, 40],
            )
            if not (
                abs(float(learning_rate) - 0.03) <= 1e-12
                and int(max_depth) == 3
                and int(max_iter) == 180
                and abs(float(l2_regularization) - 5.0) <= 1e-12
                and int(min_samples_leaf) == 20
            )
        ]
        return seed_first + rest
    if family == "adaboost":
        return [
            {"n_estimators": n_estimators, "learning_rate": learning_rate, "max_depth": max_depth}
            for n_estimators, learning_rate, max_depth in product(
                [80, 150, 250, 400],
                [0.03, 0.1, 0.3, 0.6],
                [1, 2],
            )
        ]
    if family == "xgboost":
        return [
            {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "learning_rate": learning_rate,
                "subsample": subsample,
                "colsample_bytree": colsample_bytree,
                "reg_alpha": reg_alpha,
                "reg_lambda": reg_lambda,
            }
            for n_estimators, max_depth, learning_rate, subsample, colsample_bytree, reg_alpha, reg_lambda in product(
                [200, 400, 700],
                [3, 4, 5],
                [0.03, 0.05, 0.1],
                [0.8, 1.0],
                [0.7, 1.0],
                [0.0, 0.5],
                [1.0, 5.0],
            )
        ]
    if family == "catboost":
        return [
            {
                "iterations": iterations,
                "depth": depth,
                "learning_rate": learning_rate,
                "l2_leaf_reg": l2_leaf_reg,
                "border_count": border_count,
            }
            for iterations, depth, learning_rate, l2_leaf_reg, border_count in product(
                [200, 400, 700],
                [3, 4, 5],
                [0.03, 0.05, 0.1],
                [3.0, 8.0, 15.0],
                [64, 128],
            )
        ]
    if family == "lightgbm":
        return [
            {
                "n_estimators": n_estimators,
                "max_depth": -1,
                "learning_rate": learning_rate,
                "num_leaves": num_leaves,
                "min_child_samples": min_child,
                "reg_alpha": reg_alpha,
                "reg_lambda": reg_lambda,
                "subsample": subsample,
            }
            for n_estimators, learning_rate, num_leaves, min_child, reg_alpha, reg_lambda, subsample in product(
                [200, 400, 700],
                [0.03, 0.05, 0.1],
                [15, 31, 63],
                [10, 20],
                [0.0, 0.5],
                [1.0, 5.0],
                [0.8, 1.0],
            )
        ]
    if family == "svm_linear":
        return [{"C": c} for c in [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]]
    if family == "svm_rbf":
        return [
            {"C": c, "gamma": gamma}
            for c, gamma in product(
                [0.1, 1.0, 10.0, 100.0],
                ["scale", "auto", 0.01, 0.001],
            )
        ]
    if family == "knn":
        return [
            {"n_neighbors": k, "weights": w, "metric": m}
            for k, w, m in product(
                [3, 5, 7, 11, 15],
                ["uniform", "distance"],
                ["euclidean", "manhattan"],
            )
        ]
    if family == "gaussian_nb":
        return [{"var_smoothing": vs} for vs in [1e-9, 1e-8, 1e-7, 1e-6, 1e-5]]
    if family == "decision_tree":
        return [
            {"max_depth": md, "min_samples_split": mss, "min_samples_leaf": msl}
            for md, mss, msl in product(
                [3, 5, 7, 10, None],
                [10, 20, 40],
                [5, 10, 20],
            )
        ]
    if family == "mlp":
        return [
            {"hidden_layer_sizes": hls, "alpha": alpha, "learning_rate_init": lr}
            for hls, alpha, lr in product(
                [(64,), (128,), (64, 32), (128, 64)],
                [0.001, 0.01, 0.1],
                [0.001, 0.01],
            )
        ]
    if family == "tabpfn":
        return [{"n_estimators": 16}]
    # ── Ensemble imbalance families (imblearn) ────────────────────────
    # These handle class imbalance internally via balanced bootstrap or
    # undersampling within the ensemble. Calibration should be verified
    # post-hoc (van den Goorbergh 2022 warns resampling harms calibration).
    if family == "balanced_random_forest":
        return [
            {
                "n_estimators": n_est,
                "max_depth": md,
                "min_samples_split": mss,
                "min_samples_leaf": msl,
                "max_features": mf,
            }
            for n_est, md, mss, msl, mf in product(
                [200, 400],
                [4, 6, 9],
                [10, 20],
                [5, 10],
                ["sqrt", 0.6],
            )
        ]
    if family == "easy_ensemble":
        return [
            {"n_estimators": n_est}
            for n_est in [10, 20, 30, 50]
        ]
    if family == "rusboost":
        return [
            {"n_estimators": n_est, "learning_rate": lr}
            for n_est, lr in product(
                [50, 100, 200],
                [0.1, 0.5, 1.0],
            )
        ]
    raise ValueError(f"Unsupported family: {family}")


def _family_base_complexity(family: str) -> int:
    """Return base complexity order for a model family.

    Args:
        family: Canonical model family name.

    Returns:
        Integer complexity rank (lower = simpler).
    """
    order = {
        "gaussian_nb": 1,
        "logistic_l1": 2,
        "logistic_l2": 3,
        "logistic_elasticnet": 4,
        "knn": 5,
        "decision_tree": 6,
        "svm_linear": 7,
        "svm_rbf": 8,
        "adaboost": 9,
        "random_forest_balanced": 10,
        "extra_trees_balanced": 11,
        "hist_gradient_boosting_l2": 12,
        "mlp": 13,
        "xgboost": 14,
        "catboost": 15,
        "lightgbm": 16,
        "tabpfn": 17,
        "balanced_random_forest": 11,
        "easy_ensemble": 12,
        "rusboost": 13,
    }
    return int(order.get(family, 99))


def _family_friendly_name(family: str) -> str:
    """Map a model family to a human-friendly algorithm name.

    Args:
        family: Canonical model family name.

    Returns:
        Friendly display name string.
    """
    names = {
        "logistic_l1": "logistic_regression",
        "logistic_l2": "logistic_regression",
        "logistic_elasticnet": "logistic_regression",
        "random_forest_balanced": "random_forest",
        "extra_trees_balanced": "extra_trees",
        "hist_gradient_boosting_l2": "hist_gradient_boosting",
        "adaboost": "adaboost",
        "xgboost": "xgboost",
        "catboost": "catboost",
        "lightgbm": "lightgbm",
        "svm_linear": "svm",
        "svm_rbf": "svm",
        "knn": "k_nearest_neighbors",
        "gaussian_nb": "gaussian_naive_bayes",
        "decision_tree": "decision_tree",
        "mlp": "multilayer_perceptron",
        "tabpfn": "tabpfn",
        "balanced_random_forest": "balanced_random_forest",
        "easy_ensemble": "easy_ensemble",
        "rusboost": "rusboost",
    }
    return names.get(family, family)


def _candidate_complexity_rank(family: str, params: Dict[str, Any]) -> int:
    """Compute a numeric complexity rank for a candidate model.

    Args:
        family: Canonical model family name.
        params: Hyperparameter dict.

    Returns:
        Integer rank combining family base and parameter complexity.
    """
    base = 1000 * _family_base_complexity(family)
    if family in {"logistic_l1", "logistic_l2"}:
        return int(base + round(float(params.get("C", 1.0)) * 100))
    if family == "logistic_elasticnet":
        c = float(params.get("C", 1.0))
        l1_ratio = float(params.get("l1_ratio", 0.5))
        return int(base + round(100 * c + 50 * (1.0 - l1_ratio)))
    if family in {"random_forest_balanced", "extra_trees_balanced"}:
        max_depth = params.get("max_depth")
        depth = 12 if max_depth is None else int(max_depth)
        n_estimators = int(params.get("n_estimators", 200))
        min_leaf = int(params.get("min_samples_leaf", 5))
        return int(base + depth * 20 + (n_estimators // 20) - min_leaf)
    if family == "hist_gradient_boosting_l2":
        return int(
            base
            + int(params.get("max_depth", 3)) * 30
            + int(params.get("max_iter", 180)) // 8
            + int(50 * float(params.get("learning_rate", 0.05)))
            - int(3 * float(params.get("l2_regularization", 5.0)))
        )
    if family == "adaboost":
        return int(
            base
            + int(params.get("max_depth", 1)) * 35
            + int(params.get("n_estimators", 200)) // 6
            + int(120 * float(params.get("learning_rate", 0.1)))
        )
    if family == "xgboost":
        return int(
            base
            + int(params.get("max_depth", 4)) * 35
            + int(params.get("n_estimators", 200)) // 8
            + int(150 * float(params.get("learning_rate", 0.05)))
            - int(8 * float(params.get("reg_lambda", 1.0)))
        )
    if family == "catboost":
        return int(
            base
            + int(params.get("depth", 4)) * 35
            + int(params.get("iterations", 200)) // 8
            + int(150 * float(params.get("learning_rate", 0.05)))
            - int(6 * float(params.get("l2_leaf_reg", 3.0)))
        )
    if family == "lightgbm":
        return int(
            base
            + int(params.get("max_depth", 5)) * 30
            + int(params.get("n_estimators", 200)) // 8
            + int(params.get("num_leaves", 31))
            + int(100 * float(params.get("learning_rate", 0.05)))
            - int(5 * float(params.get("reg_lambda", 1.0)))
        )
    if family == "svm_linear":
        return int(base + round(float(params.get("C", 1.0)) * 100))
    if family == "svm_rbf":
        gamma = params.get("gamma", "scale")
        gamma_penalty = 50 if isinstance(gamma, (int, float)) else 20
        return int(base + round(float(params.get("C", 1.0)) * 30) + gamma_penalty)
    if family == "tabpfn":
        return int(base + int(params.get("n_estimators", 16)))
    return int(base + 999)


def _regularization_profile(family: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Build a regularization profile descriptor for a candidate.

    Args:
        family: Canonical model family name.
        params: Hyperparameter dict.

    Returns:
        Dict describing regularization type, strength, and strategy.
    """
    if family == "logistic_l1":
        return {"type": "l1", "C": float(params["C"]), "target": "sparsity"}
    if family == "logistic_l2":
        return {"type": "l2", "C": float(params["C"]), "target": "coefficient_shrinkage"}
    if family == "logistic_elasticnet":
        return {
            "type": "elasticnet",
            "C": float(params["C"]),
            "l1_ratio": float(params["l1_ratio"]),
            "target": "sparsity_plus_shrinkage",
        }
    if family in {"random_forest_balanced", "extra_trees_balanced"}:
        return {
            "type": "tree_complexity",
            "max_depth": params.get("max_depth"),
            "min_samples_leaf": int(params["min_samples_leaf"]),
            "min_samples_split": int(params["min_samples_split"]),
        }
    if family == "hist_gradient_boosting_l2":
        return {
            "type": "boosting_l2",
            "l2_regularization": float(params["l2_regularization"]),
            "max_depth": int(params["max_depth"]),
            "learning_rate": float(params["learning_rate"]),
        }
    if family == "adaboost":
        return {
            "type": "boosting_shrinkage",
            "learning_rate": float(params["learning_rate"]),
            "weak_learner_max_depth": int(params["max_depth"]),
        }
    if family == "xgboost":
        return {
            "type": "xgboost_regularization",
            "reg_alpha": float(params["reg_alpha"]),
            "reg_lambda": float(params["reg_lambda"]),
            "max_depth": int(params["max_depth"]),
        }
    if family == "catboost":
        return {
            "type": "catboost_regularization",
            "l2_leaf_reg": float(params["l2_leaf_reg"]),
            "depth": int(params["depth"]),
        }
    if family == "lightgbm":
        return {
            "type": "lightgbm_regularization",
            "reg_alpha": float(params.get("reg_alpha", 0.0)),
            "reg_lambda": float(params.get("reg_lambda", 1.0)),
            "max_depth": int(params.get("max_depth", 5)),
            "num_leaves": int(params.get("num_leaves", 31)),
        }
    if family == "svm_linear":
        return {"type": "svm_margin", "C": float(params["C"]), "kernel": "linear"}
    if family == "svm_rbf":
        return {"type": "svm_margin", "C": float(params["C"]), "kernel": "rbf", "gamma": params.get("gamma", "scale")}
    if family == "tabpfn":
        return {"type": "pretrained_foundation", "n_estimators": int(params.get("n_estimators", 16))}
    if family == "balanced_random_forest":
        return {
            "type": "tree_complexity_balanced_bootstrap",
            "max_depth": params.get("max_depth"),
            "min_samples_leaf": int(params["min_samples_leaf"]),
            "imbalance_handling": "internal_balanced_bootstrap",
        }
    if family == "easy_ensemble":
        return {
            "type": "ensemble_undersampling",
            "n_estimators": int(params["n_estimators"]),
            "imbalance_handling": "internal_random_undersampling_per_learner",
        }
    if family == "rusboost":
        return {
            "type": "boosting_undersampling",
            "n_estimators": int(params["n_estimators"]),
            "learning_rate": float(params["learning_rate"]),
            "imbalance_handling": "internal_random_undersampling_per_iteration",
        }
    return {"type": "unknown"}


def _build_adaboost_classifier(
    seed: int,
    class_weight: Optional[str],
    n_estimators: int,
    learning_rate: float,
    max_depth: int,
) -> AdaBoostClassifier:
    """Build an AdaBoost classifier with a depth-limited decision tree base.

    Args:
        seed: Random seed.
        class_weight: 'balanced' or None for the base tree.
        n_estimators: Number of boosting rounds.
        learning_rate: Shrinkage rate.
        max_depth: Maximum depth of the base decision tree.

    Returns:
        Configured AdaBoostClassifier.
    """
    weak_learner = DecisionTreeClassifier(
        max_depth=int(max_depth),
        min_samples_leaf=10,
        class_weight=class_weight,
        random_state=seed,
    )
    try:
        return AdaBoostClassifier(
            estimator=weak_learner,
            n_estimators=int(n_estimators),
            learning_rate=float(learning_rate),
            random_state=seed,
        )
    except TypeError:
        return AdaBoostClassifier(
            base_estimator=weak_learner,  # type: ignore[arg-type]
            n_estimators=int(n_estimators),
            learning_rate=float(learning_rate),
            random_state=seed,
        )


def _build_estimator_for_family(
    family: str,
    params: Dict[str, Any],
    seed: int,
    imputation_strategy: str,
    class_weight: Optional[str],
    n_jobs: int,
    device: str = "cpu",
) -> BaseEstimator:
    """Build a scikit-learn Pipeline for a model family and hyperparameters.

    Args:
        family: Canonical model family name.
        params: Hyperparameter dict.
        seed: Random seed.
        imputation_strategy: Imputation method for pipeline.
        class_weight: 'balanced' or None.
        n_jobs: Parallel workers.
        device: Compute device string.

    Returns:
        Configured Pipeline (imputer + scaler + classifier).

    Raises:
        ValueError: If the family is unsupported.
        RuntimeError: If tabpfn backend is requested but not installed.
    """
    # Tree-based models handle missing values natively via split direction.
    # Don't add missing indicators for them (avoid redundant features).
    _TREE_FAMILIES = {
        "random_forest_balanced", "extra_trees_balanced",
        "hist_gradient_boosting_l2", "adaboost",
        "xgboost", "catboost", "lightgbm", "decision_tree",
        "balanced_random_forest", "easy_ensemble", "rusboost",
    }
    native_missing = family in _TREE_FAMILIES
    imputer = build_imputer(imputation_strategy, seed, native_missing_support=native_missing)
    if family == "logistic_l1":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        penalty="l1",
                        solver="liblinear",
                        C=float(params["C"]),
                        max_iter=6000,
                        class_weight=class_weight,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "logistic_l2":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        penalty="l2",
                        solver="liblinear",
                        C=float(params["C"]),
                        max_iter=6000,
                        class_weight=class_weight,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "logistic_elasticnet":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        penalty="elasticnet",
                        solver="saga",
                        C=float(params["C"]),
                        l1_ratio=float(params["l1_ratio"]),
                        max_iter=8000,
                        class_weight=class_weight,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "random_forest_balanced":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=int(params["n_estimators"]),
                        max_depth=params["max_depth"],
                        min_samples_split=int(params["min_samples_split"]),
                        min_samples_leaf=int(params["min_samples_leaf"]),
                        max_features=params["max_features"],
                        class_weight=class_weight,
                        random_state=seed,
                        n_jobs=n_jobs,
                    ),
                ),
            ]
        )
    if family == "extra_trees_balanced":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    ExtraTreesClassifier(
                        n_estimators=int(params["n_estimators"]),
                        max_depth=params["max_depth"],
                        min_samples_split=int(params["min_samples_split"]),
                        min_samples_leaf=int(params["min_samples_leaf"]),
                        max_features=params["max_features"],
                        class_weight=class_weight,
                        random_state=seed,
                        n_jobs=n_jobs,
                    ),
                ),
            ]
        )
    if family == "hist_gradient_boosting_l2":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        learning_rate=float(params["learning_rate"]),
                        max_depth=int(params["max_depth"]),
                        max_iter=int(params["max_iter"]),
                        l2_regularization=float(params["l2_regularization"]),
                        min_samples_leaf=int(params["min_samples_leaf"]),
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "adaboost":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    _build_adaboost_classifier(
                        seed=seed,
                        class_weight=class_weight,
                        n_estimators=int(params["n_estimators"]),
                        learning_rate=float(params["learning_rate"]),
                        max_depth=int(params["max_depth"]),
                    ),
                ),
            ]
        )
    if family == "xgboost":
        if XGBClassifier is None:
            raise RuntimeError("xgboost backend is not installed.")
        xgb_device = "cuda" if device == "gpu" else "cpu"
        clf = XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            n_estimators=int(params["n_estimators"]),
            max_depth=int(params["max_depth"]),
            learning_rate=float(params["learning_rate"]),
            subsample=float(params["subsample"]),
            colsample_bytree=float(params["colsample_bytree"]),
            reg_alpha=float(params["reg_alpha"]),
            reg_lambda=float(params["reg_lambda"]),
            random_state=seed,
            n_jobs=n_jobs,
            tree_method="hist",
            device=xgb_device,
            verbosity=0,
        )
        # Note: XGBoost class_weight="balanced" is handled at fit time
        # via scale_pos_weight in fit_estimator_with_imbalance().
        return Pipeline(steps=[("imputer", imputer), ("clf", clf)])
    if family == "catboost":
        if CatBoostClassifier is None:
            raise RuntimeError("catboost backend is not installed.")
        kwargs: Dict[str, Any] = {
            "loss_function": "Logloss",
            "eval_metric": "AUC",
            "iterations": int(params["iterations"]),
            "depth": int(params["depth"]),
            "learning_rate": float(params["learning_rate"]),
            "l2_leaf_reg": float(params["l2_leaf_reg"]),
            "border_count": int(params["border_count"]),
            "random_seed": seed,
            "verbose": False,
            "allow_writing_files": False,
            "thread_count": int(n_jobs),
        }
        if device == "gpu":
            kwargs["task_type"] = "GPU"
        if class_weight == "balanced":
            kwargs["auto_class_weights"] = "Balanced"
        clf = CatBoostClassifier(**kwargs)
        return Pipeline(steps=[("imputer", imputer), ("clf", clf)])
    if family == "lightgbm":
        if LGBMClassifier is None:
            raise RuntimeError("lightgbm backend is not installed.")
        lgbm_kwargs: Dict[str, Any] = {
            "objective": "binary",
            "n_estimators": int(params["n_estimators"]),
            "max_depth": int(params.get("max_depth", -1)),
            "learning_rate": float(params["learning_rate"]),
            "num_leaves": int(params["num_leaves"]),
            "min_child_samples": int(params.get("min_child_samples", 20)),
            "reg_alpha": float(params["reg_alpha"]),
            "reg_lambda": float(params["reg_lambda"]),
            "subsample": float(params["subsample"]),
            "random_state": seed,
            "n_jobs": n_jobs,
            "verbose": -1,
        }
        if device == "gpu":
            lgbm_kwargs["device"] = "gpu"
        if class_weight == "balanced":
            lgbm_kwargs["is_unbalance"] = True
        clf = LGBMClassifier(**lgbm_kwargs)
        return Pipeline(steps=[("imputer", imputer), ("clf", clf)])
    if family == "svm_linear":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    SVC(
                        kernel="linear",
                        C=float(params["C"]),
                        probability=True,
                        class_weight=class_weight,
                        random_state=seed,
                        max_iter=10000,
                    ),
                ),
            ]
        )
    if family == "svm_rbf":
        gamma = params.get("gamma", "scale")
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    SVC(
                        kernel="rbf",
                        C=float(params["C"]),
                        gamma=gamma,
                        probability=True,
                        class_weight=class_weight,
                        random_state=seed,
                        max_iter=10000,
                    ),
                ),
            ]
        )
    if family == "knn":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    KNeighborsClassifier(
                        n_neighbors=int(params["n_neighbors"]),
                        weights=str(params.get("weights", "uniform")),
                        metric=str(params.get("metric", "euclidean")),
                        n_jobs=n_jobs,
                    ),
                ),
            ]
        )
    if family == "gaussian_nb":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    GaussianNB(
                        var_smoothing=float(params.get("var_smoothing", 1e-9)),
                    ),
                ),
            ]
        )
    if family == "decision_tree":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    DecisionTreeClassifier(
                        max_depth=params.get("max_depth"),
                        min_samples_split=int(params.get("min_samples_split", 10)),
                        min_samples_leaf=int(params.get("min_samples_leaf", 5)),
                        class_weight=class_weight,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "mlp":
        return Pipeline(
            steps=[
                ("imputer", imputer),
                ("scaler", StandardScaler()),
                (
                    "clf",
                    MLPClassifier(
                        hidden_layer_sizes=params.get("hidden_layer_sizes", (64,)),
                        alpha=float(params.get("alpha", 0.001)),
                        learning_rate_init=float(params.get("learning_rate_init", 0.001)),
                        max_iter=2000,
                        early_stopping=True,
                        validation_fraction=0.15,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if family == "tabpfn":
        if TabPFNClassifier is None:
            raise RuntimeError("tabpfn backend is not installed.")
        n_ensemble = int(params.get("n_estimators", 16))
        tabpfn_device = str(params.get("device", device))
        clf = TabPFNClassifier(n_estimators=n_ensemble, device=tabpfn_device)
        return Pipeline(steps=[("imputer", imputer), ("clf", clf)])
    # ── Ensemble imbalance families (imblearn) ────────────────────────
    # These classifiers handle imbalance internally — do NOT pass
    # class_weight to them (they use balanced bootstrap / undersampling).
    # Calibration warning: resampling-based methods can shift predicted
    # probabilities. Always verify calibration post-hoc (calibration gate).
    if family == "balanced_random_forest":
        if BalancedRandomForestClassifier is None:
            raise RuntimeError(
                "balanced_random_forest requires imbalanced-learn. "
                "Install with: pip install imbalanced-learn>=0.12"
            )
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    BalancedRandomForestClassifier(
                        n_estimators=int(params["n_estimators"]),
                        max_depth=params.get("max_depth"),
                        min_samples_split=int(params.get("min_samples_split", 10)),
                        min_samples_leaf=int(params.get("min_samples_leaf", 5)),
                        max_features=params.get("max_features", "sqrt"),
                        random_state=seed,
                        n_jobs=n_jobs,
                    ),
                ),
            ]
        )
    if family == "easy_ensemble":
        if EasyEnsembleClassifier is None:
            raise RuntimeError(
                "easy_ensemble requires imbalanced-learn. "
                "Install with: pip install imbalanced-learn>=0.12"
            )
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    EasyEnsembleClassifier(
                        n_estimators=int(params["n_estimators"]),
                        random_state=seed,
                        n_jobs=n_jobs,
                    ),
                ),
            ]
        )
    if family == "rusboost":
        if RUSBoostClassifier is None:
            raise RuntimeError(
                "rusboost requires imbalanced-learn. "
                "Install with: pip install imbalanced-learn>=0.12"
            )
        return Pipeline(
            steps=[
                ("imputer", imputer),
                (
                    "clf",
                    RUSBoostClassifier(
                        n_estimators=int(params["n_estimators"]),
                        learning_rate=float(params.get("learning_rate", 1.0)),
                        random_state=seed,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unsupported family: {family}")


def build_candidates(
    seed: int,
    sampling_seed: int,
    imputation_strategy: str,
    class_weight: Optional[str],
    model_pool_config: Dict[str, Any],
    device: str = "cpu",
    temporal_cv: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build the full candidate model pool for selection.

    Args:
        seed: Random seed.
        sampling_seed: Seed for hyperparameter sampling.
        imputation_strategy: Resolved imputation method.
        class_weight: 'balanced' or None.
        model_pool_config: Resolved model pool configuration dict.
        device: Compute device string.

    Returns:
        Tuple of (list of candidate dicts with estimator/metadata,
        candidate space metadata dict).

    Raises:
        SystemExit: If optuna is requested but not installed.
    """
    requested_pool = [str(x) for x in model_pool_config.get("model_pool", []) if str(x).strip()]
    explicit_requested_pool = [str(x) for x in model_pool_config.get("requested_models", []) if str(x).strip()]
    max_trials = int(model_pool_config.get("max_trials_per_family", 1))
    search_strategy = str(model_pool_config.get("search_strategy", "random_subsample")).strip().lower()
    n_jobs = int(model_pool_config.get("n_jobs", -1))
    optuna_trials = int(model_pool_config.get("optuna_trials", 50))
    optuna_X_train = model_pool_config.get("optuna_X_train")
    optuna_y_train = model_pool_config.get("optuna_y_train")
    optuna_cv_splits = int(model_pool_config.get("optuna_cv_splits", 5))

    if search_strategy == "optuna" and optuna is None:
        raise SystemExit("optuna requested but package is not installed. Install with `pip install optuna`.")

    unavailable: List[str] = []
    candidates: List[Dict[str, Any]] = []
    family_search_space: Dict[str, Any] = {}
    explicit_cli_models = {str(x) for x in model_pool_config.get("cli_models", [])}

    for family in requested_pool:
        if family in ENSEMBLE_FAMILIES:
            continue
        if family == "xgboost" and XGBClassifier is None:
            unavailable.append(family)
            if family in explicit_cli_models:
                raise SystemExit(
                    "model_backend_unavailable: xgboost requested but package is not installed. "
                    "Install with `pip install xgboost` or run `python3 scripts/env_doctor.py` for diagnostics."
                )
            continue
        if family == "catboost" and CatBoostClassifier is None:
            unavailable.append(family)
            if family in explicit_cli_models:
                raise SystemExit(
                    "model_backend_unavailable: catboost requested but package is not installed. "
                    "Install with `pip install catboost` or run `python3 scripts/env_doctor.py` for diagnostics."
                )
            continue
        if family == "lightgbm" and LGBMClassifier is None:
            unavailable.append(family)
            if family in explicit_cli_models:
                raise SystemExit(
                    "model_backend_unavailable: lightgbm requested but package is not installed. "
                    "Install with `pip install lightgbm` or run `python3 scripts/env_doctor.py` for diagnostics."
                )
            continue
        if family == "tabpfn" and TabPFNClassifier is None:
            unavailable.append(family)
            if family in explicit_cli_models:
                raise SystemExit(
                    "model_backend_unavailable: tabpfn requested but package is not installed. "
                    "Install with `pip install tabpfn` or run `python3 scripts/env_doctor.py` for diagnostics."
                )
            continue
        if family == "tabpfn":
            train_rows = int(model_pool_config.get("train_rows", 0))
            feature_count = int(model_pool_config.get("feature_count", 0))
            if train_rows > 1000 or feature_count > 100:
                unavailable.append(family)
                if family in explicit_cli_models:
                    raise SystemExit(
                        f"tabpfn_limits_exceeded: TabPFN supports ≤1000 training samples and ≤100 features. "
                        f"Current: {train_rows} samples, {feature_count} features. "
                        f"Remove 'tabpfn' from model pool or reduce dataset dimensions."
                    )
                continue
        # imblearn ensemble families — optional dependency
        _IMBLEARN_FAMILIES = {
            "balanced_random_forest": BalancedRandomForestClassifier,
            "easy_ensemble": EasyEnsembleClassifier,
            "rusboost": RUSBoostClassifier,
        }
        if family in _IMBLEARN_FAMILIES and _IMBLEARN_FAMILIES[family] is None:
            unavailable.append(family)
            if family in explicit_cli_models:
                raise SystemExit(
                    f"model_backend_unavailable: {family} requires imbalanced-learn. "
                    f"Install with `pip install imbalanced-learn>=0.12`."
                )
            continue

        if search_strategy == "optuna" and family not in {"tabpfn"} and optuna_X_train is not None:
            chosen_grid = _optuna_search_family(
                family=family,
                X_train=optuna_X_train,
                y_train=optuna_y_train,
                n_trials=optuna_trials,
                seed=seed,
                imputation_strategy=imputation_strategy,
                class_weight=class_weight,
                n_jobs=n_jobs,
                cv_splits=optuna_cv_splits,
                device=device,
                temporal_cv=temporal_cv,
            )
            family_search_space[family] = {
                "total_configurations": optuna_trials,
                "sampled_trials": int(len(chosen_grid)),
                "max_trials_per_family": int(len(chosen_grid)),
                "search_strategy": "optuna",
            }
        else:
            full_grid = _family_grid(family)
            chosen_grid = _sample_family_params(
                family=family,
                grid=full_grid,
                max_trials=max_trials,
                strategy=search_strategy if search_strategy != "optuna" else "random_subsample",
                sampling_seed=sampling_seed,
            )
            family_search_space[family] = {
                "total_configurations": int(len(full_grid)),
                "sampled_trials": int(len(chosen_grid)),
                "max_trials_per_family": int(max_trials),
                "search_strategy": search_strategy if search_strategy != "optuna" else "random_subsample",
            }
        family_total_configs = int(family_search_space[family]["total_configurations"])
        # Internal-imbalance families handle class imbalance inside the
        # estimator (balanced bootstrap / undersampling) — do NOT pass
        # class_weight or apply external resampling on top.
        is_internal_imbalance = family in INTERNAL_IMBALANCE_FAMILIES
        effective_cw = None if is_internal_imbalance else class_weight

        for trial_idx, params in enumerate(chosen_grid, start=1):
            estimator = _build_estimator_for_family(
                family=family,
                params=params,
                seed=seed,
                imputation_strategy=imputation_strategy,
                class_weight=effective_cw,
                n_jobs=n_jobs,
                device=device,
            )
            signature = json.dumps(params, sort_keys=True, separators=(",", ":"))
            model_id = f"{family}__t{trial_idx:02d}_{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:8]}"
            candidates.append(
                {
                    "model_id": model_id,
                    "base_model_id": family,
                    "family": _family_friendly_name(family),
                    "complexity_rank": _candidate_complexity_rank(family, params),
                    "hyperparameters": params,
                    "regularization_profile": _regularization_profile(family, params),
                    "estimator": estimator,
                    "_internal_imbalance": is_internal_imbalance,
                    "search_meta": {
                        "trial_index": int(trial_idx),
                        "family_total_configurations": family_total_configs,
                        "family_sampled_trials": int(len(chosen_grid)),
                        "search_strategy": search_strategy,
                    },
                }
            )

    metadata = {
        "requested_model_pool": explicit_requested_pool or requested_pool,
        "effective_model_pool": requested_pool,
        "unavailable_models": unavailable,
        "family_search_space": family_search_space,
        "n_jobs": int(n_jobs),
        "max_trials_per_family": int(max_trials),
        "search_strategy": search_strategy,
    }
    return candidates, metadata


def build_ensemble_candidates(
    candidate_rows: List[Dict[str, Any]],
    estimator_map: Dict[str, BaseEstimator],
    requested_ensembles: List[str],
    top_k: int,
    seed: int,
) -> List[Dict[str, Any]]:
    """Build ensemble candidates from top-K base models.

    Args:
        candidate_rows: Scored candidate row dicts.
        estimator_map: Mapping of model_id to fitted estimator.
        requested_ensembles: Ensemble strategies ('soft_voting', etc.).
        top_k: Number of top base models to include.
        seed: Random seed.

    Returns:
        List of ensemble candidate dicts with estimator/metadata.
    """
    from sklearn.ensemble import StackingClassifier, VotingClassifier

    sorted_rows = sorted(
        candidate_rows,
        key=lambda r: float(r.get("selection_metrics", {}).get("pr_auc", {}).get("mean", 0.0)),
        reverse=True,
    )
    top_rows = sorted_rows[:top_k]
    base_ids = [r["model_id"] for r in top_rows]
    base_estimators = [(mid, clone(estimator_map[mid])) for mid in base_ids if mid in estimator_map]
    if len(base_estimators) < 2:
        return []

    ensemble_candidates: List[Dict[str, Any]] = []
    base_meta = {
        "base_model_ids": [mid for mid, _ in base_estimators],
        "top_k": top_k,
    }

    if "soft_voting" in requested_ensembles:
        voter = VotingClassifier(
            estimators=list(base_estimators),
            voting="soft",
            n_jobs=-1,
        )
        ensemble_candidates.append({
            "model_id": f"soft_voting__top{top_k}",
            "base_model_id": "soft_voting",
            "family": "ensemble_voting",
            "complexity_rank": 15000 + top_k,
            "hyperparameters": {"voting": "soft", "top_k": top_k, **base_meta},
            "regularization_profile": {"type": "ensemble_averaging", "strategy": "soft_voting", **base_meta},
            "estimator": voter,
            "search_meta": {"ensemble": True, "strategy": "soft_voting", **base_meta},
        })

    if "weighted_voting" in requested_ensembles:
        cv_means = [
            float(r.get("selection_metrics", {}).get("pr_auc", {}).get("mean", 0.0))
            for r in top_rows
        ]
        total = sum(cv_means) or 1.0
        weights = [m / total for m in cv_means]
        voter = VotingClassifier(
            estimators=list(base_estimators),
            voting="soft",
            weights=weights,
            n_jobs=-1,
        )
        ensemble_candidates.append({
            "model_id": f"weighted_voting__top{top_k}",
            "base_model_id": "weighted_voting",
            "family": "ensemble_voting",
            "complexity_rank": 15000 + top_k + 1,
            "hyperparameters": {"voting": "soft_weighted", "weights": [round(w, 4) for w in weights], "top_k": top_k, **base_meta},
            "regularization_profile": {"type": "ensemble_weighted_averaging", "strategy": "weighted_voting", **base_meta},
            "estimator": voter,
            "search_meta": {"ensemble": True, "strategy": "weighted_voting", **base_meta},
        })

    if "stacking" in requested_ensembles:
        meta_learner = LogisticRegression(
            penalty="l2",
            C=1.0,
            solver="lbfgs",
            max_iter=3000,
            random_state=seed,
        )
        stacker = StackingClassifier(
            estimators=list(base_estimators),
            final_estimator=meta_learner,
            cv=5,
            stack_method="predict_proba",
            passthrough=False,
            n_jobs=-1,
        )
        ensemble_candidates.append({
            "model_id": f"stacking__top{top_k}",
            "base_model_id": "stacking",
            "family": "ensemble_stacking",
            "complexity_rank": 16000 + top_k,
            "hyperparameters": {"meta_learner": "logistic_l2", "cv_folds": 5, "top_k": top_k, **base_meta},
            "regularization_profile": {
                "type": "stacking_meta_learner",
                "meta_learner": "logistic_l2_C1.0",
                "internal_cv": 5,
                "passthrough": False,
                **base_meta,
            },
            "estimator": stacker,
            "search_meta": {"ensemble": True, "strategy": "stacking", **base_meta},
        })

    return ensemble_candidates


def predict_proba_1(estimator: BaseEstimator, X: pd.DataFrame) -> np.ndarray:
    """Extract class-1 probability from an estimator.

    Falls back to sigmoid of decision_function if predict_proba is absent.

    Args:
        estimator: Fitted estimator.
        X: Feature DataFrame.

    Returns:
        1-D float array of positive-class probabilities.

    Raises:
        ValueError: If estimator exposes neither probabilities nor scores.
    """
    if hasattr(estimator, "predict_proba"):
        proba = estimator.predict_proba(X)
        if isinstance(proba, np.ndarray) and proba.ndim == 2 and proba.shape[1] >= 2:
            return np.asarray(proba[:, 1], dtype=float)
    if hasattr(estimator, "decision_function"):
        scores = np.asarray(estimator.decision_function(X), dtype=float)
        # Clip to prevent overflow in exp() (|score| > 500 causes inf/nan)
        scores = np.clip(scores, -500.0, 500.0)
        return 1.0 / (1.0 + np.exp(-scores))
    raise ValueError("Estimator does not expose probability-like outputs.")


def fit_probability_calibrator(
    y_true: np.ndarray,
    proba_raw: np.ndarray,
    method: str,
    seed: int,
) -> Optional[Any]:
    """Fit a probability calibrator on raw scores.

    Args:
        y_true: Binary ground-truth labels.
        proba_raw: Uncalibrated probability scores.
        method: Calibration method ('sigmoid', 'isotonic', 'power',
            'beta', or 'none').
        seed: Random seed for logistic-based calibrators.

    Returns:
        Fitted calibrator object/dict, or None if method is 'none'
        or data is insufficient (<20 samples or single class).

    Raises:
        ValueError: If method is unsupported or arrays are misaligned.
    """
    token = str(method).strip().lower()
    if token in {"", "none"}:
        return None
    if token not in {"sigmoid", "isotonic", "power", "beta"}:
        raise ValueError(f"Unsupported calibration method: {method}")
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(proba_raw, dtype=float)
    if y.ndim != 1 or s.ndim != 1 or y.shape[0] != s.shape[0]:
        raise ValueError("Calibration arrays must be 1D and aligned.")
    if y.shape[0] < 20:
        return None
    if len(np.unique(y)) < 2:
        return None
    s = np.clip(s, 1e-6, 1.0 - 1e-6)
    if token == "isotonic":
        calibrator = IsotonicRegression(y_min=1e-6, y_max=1.0 - 1e-6, out_of_bounds="clip")
        calibrator.fit(s, y.astype(float))
        return calibrator
    if token == "power":
        # Smooth monotonic calibration that preserves ranking while controlling over/under-confidence.
        def calibration_ece_local(
            labels: np.ndarray,
            scores: np.ndarray,
            n_bins: int = 10,
            min_bin_size: int = 15,
        ) -> float:
            """Compute local expected calibration error.

            Args:
                labels: Binary ground-truth labels.
                scores: Predicted probability scores.
                n_bins: Number of calibration bins.
                min_bin_size: Minimum samples per bin.

            Returns:
                ECE value in [0, 1].
            """
            n = int(labels.shape[0])
            if n <= 0:
                return 1.0
            requested_bins = max(2, int(n_bins))
            effective_bins = max(2, n // max(1, int(min_bin_size)))
            bin_count = min(requested_bins, effective_bins)
            order = np.argsort(scores.astype(float))
            blocks = np.array_split(order, bin_count)
            total = 0.0
            for idx in blocks:
                count = int(idx.shape[0])
                if count == 0:
                    continue
                avg_score = float(np.mean(scores[idx]))
                avg_true = float(np.mean(labels[idx]))
                total += (count / n) * abs(avg_true - avg_score)
            return float(total)

        best: Optional[Tuple[float, float, float]] = None
        grid = np.linspace(0.70, 1.60, 181)
        for alpha in grid.tolist():
            calibrated = np.clip(np.power(s, float(alpha)), 1e-6, 1.0 - 1e-6)
            ece = calibration_ece_local(y, calibrated, n_bins=10)
            brier = float(brier_score_loss(y, calibrated))
            candidate = (float(ece), float(brier), float(alpha))
            if best is None or candidate < best:
                best = candidate
        if best is None:
            return None
        return {
            "kind": "power",
            "alpha": float(best[2]),
            "valid_ece": float(best[0]),
            "valid_brier": float(best[1]),
        }
    if token == "beta":
        beta_features = np.column_stack([np.log(s), np.log(1.0 - s)])
        beta_model = LogisticRegression(
            max_iter=4000,
            solver="lbfgs",
            random_state=int(seed),
        )
        beta_model.fit(beta_features, y)
        coef = np.asarray(beta_model.coef_, dtype=float).reshape(-1)
        intercept = float(np.asarray(beta_model.intercept_, dtype=float).reshape(-1)[0])
        return {
            "kind": "beta",
            "coef_log_p": float(coef[0]) if coef.shape[0] >= 1 else 0.0,
            "coef_log_one_minus_p": float(coef[1]) if coef.shape[0] >= 2 else 0.0,
            "intercept": intercept,
        }
    calibrator = LogisticRegression(
        max_iter=2000,
        solver="lbfgs",
        random_state=int(seed),
    )
    calibrator.fit(s.reshape(-1, 1), y)
    return calibrator


def apply_probability_calibrator(calibrator: Optional[Any], proba_raw: np.ndarray) -> np.ndarray:
    """Apply a fitted calibrator to raw probability scores.

    Args:
        calibrator: Calibrator returned by fit_probability_calibrator,
            or None for identity pass-through.
        proba_raw: Uncalibrated probability scores.

    Returns:
        Calibrated probability array clipped to [1e-6, 1-1e-6].

    Raises:
        ValueError: If the calibrator dict kind is unsupported, or if
            the calibrator object exposes neither predict_proba nor predict.
    """
    s = np.asarray(proba_raw, dtype=float)
    s = np.clip(s, 1e-6, 1.0 - 1e-6)
    if calibrator is None:
        return s
    if isinstance(calibrator, dict):
        kind = str(calibrator.get("kind", "")).strip().lower()
        if kind == "power":
            alpha = float(calibrator.get("alpha", 1.0))
            return np.clip(np.power(s, alpha), 1e-6, 1.0 - 1e-6)
        if kind == "beta":
            coef_log_p = float(calibrator.get("coef_log_p", 0.0))
            coef_log_one_minus_p = float(calibrator.get("coef_log_one_minus_p", 0.0))
            intercept = float(calibrator.get("intercept", 0.0))
            logits = (coef_log_p * np.log(s)) + (coef_log_one_minus_p * np.log(1.0 - s)) + intercept
            return np.clip(1.0 / (1.0 + np.exp(-logits)), 1e-6, 1.0 - 1e-6)
        raise ValueError(f"Unsupported calibrator kind: {kind}")
    if hasattr(calibrator, "predict_proba"):
        out = calibrator.predict_proba(s.reshape(-1, 1))
        if isinstance(out, np.ndarray) and out.ndim == 2 and out.shape[1] >= 2:
            return np.clip(np.asarray(out[:, 1], dtype=float), 1e-6, 1.0 - 1e-6)
    if hasattr(calibrator, "predict"):
        out = calibrator.predict(s)
        return np.clip(np.asarray(out, dtype=float), 1e-6, 1.0 - 1e-6)
    raise ValueError("Calibrator does not expose calibrated probabilities.")


def cv_score_pr_auc(
    estimator: BaseEstimator,
    X: pd.DataFrame,
    y: np.ndarray,
    n_splits: int,
    seed: int,
    imbalance_strategy: str = "none",
    score_metric: str = "pr_auc",
    temporal_cv: bool = False,
) -> Tuple[float, float, int, List[float]]:
    """Score an estimator by stratified CV PR-AUC.

    Args:
        estimator: Unfitted estimator (cloned per fold).
        X: Feature DataFrame.
        y: Binary target array.
        n_splits: Number of CV folds.
        seed: Random seed for fold splitting.
        temporal_cv: If True, use TimeSeriesSplit (respects temporal order)
            instead of StratifiedKFold (shuffles). Required when training
            data has temporal ordering.

    Returns:
        Tuple of (mean PR-AUC, std PR-AUC, number of valid folds,
        list of per-fold scores).

    Raises:
        ValueError: If fewer than 2 valid folds are produced.
    """
    metric_token = str(score_metric).strip().lower()
    if metric_token not in {"pr_auc", "roc_auc"}:
        raise ValueError(f"Unsupported score metric for CV: {score_metric}")
    if temporal_cv:
        from sklearn.model_selection import TimeSeriesSplit
        splitter = TimeSeriesSplit(n_splits=n_splits)
    else:
        splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    fold_scores: List[float] = []
    for fold_idx, (tr_idx, va_idx) in enumerate(splitter.split(X, y), start=1):
        y_val = y[va_idx]
        if len(np.unique(y_val)) < 2:
            continue
        model = clone(estimator)
        model, _ = fit_estimator_with_imbalance(
            estimator=model,
            X_train=X.iloc[tr_idx],
            y_train=y[tr_idx],
            strategy=str(imbalance_strategy),
            seed=int(seed) + int(fold_idx) * _FOLD_IMBALANCE_SEED_STRIDE,
        )
        proba = predict_proba_1(model, X.iloc[va_idx])
        if metric_token == "roc_auc":
            score = float(roc_auc_score(y_val, proba))
        else:
            score = float(average_precision_score(y_val, proba))
        fold_scores.append(clip01(score))
    if len(fold_scores) < 2:
        raise ValueError("Insufficient valid CV folds for PR-AUC scoring.")
    arr = np.asarray(fold_scores, dtype=float)
    return clip01(float(arr.mean())), clip01(float(arr.std(ddof=1))), int(arr.shape[0]), [clip01(float(x)) for x in fold_scores]


def choose_model_one_se(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select a model using the one-standard-error rule.

    Picks the simplest model whose mean score is within one SE of
    the best model's mean score.  When ``n_folds < 2`` (e.g.
    ``selection_data="valid"``), SE is undefined so **all** candidates
    are eligible and the simplest one wins (complexity-rank tie-breaking).

    Args:
        rows: List of dicts with keys 'model_id', 'mean', 'std',
            'n_folds', 'complexity_rank'.

    Returns:
        Selection trace dict with best/chosen model IDs, threshold,
        and eligible models.
    """
    best = max(rows, key=lambda r: float(r["mean"]))
    n_folds = int(best["n_folds"])
    if n_folds < 2:
        # Single validation split — SE is undefined.  All candidates whose
        # mean equals the best mean are eligible; break ties by simplicity.
        best_se = 0.0
        threshold = float(best["mean"])
    else:
        best_se = float(best["std"]) / math.sqrt(float(n_folds))
        threshold = float(best["mean"]) - best_se
    eligible = [r for r in rows if float(r["mean"]) >= threshold - 1e-12]
    chosen = sorted(
        eligible,
        key=lambda r: (int(r["complexity_rank"]), -float(r["mean"]), str(r["model_id"])),
    )[0]
    return {
        "best_model_id": str(best["model_id"]),
        "best_mean": float(best["mean"]),
        "best_se": best_se,
        "one_se_threshold": threshold,
        "eligible_model_ids": [str(r["model_id"]) for r in eligible],
        "chosen_model_id": str(chosen["model_id"]),
    }


def confusion_counts(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, int]:
    """Compute binary confusion matrix counts.

    Args:
        y_true: Ground-truth binary labels.
        y_pred: Predicted binary labels.

    Returns:
        Dict with keys 'tp', 'fp', 'tn', 'fn'.
    """
    y_true_i = y_true.astype(int)
    y_pred_i = y_pred.astype(int)
    tp = int(np.sum((y_true_i == 1) & (y_pred_i == 1)))
    fp = int(np.sum((y_true_i == 0) & (y_pred_i == 1)))
    tn = int(np.sum((y_true_i == 0) & (y_pred_i == 0)))
    fn = int(np.sum((y_true_i == 1) & (y_pred_i == 0)))
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def safe_ratio(num: float, den: float) -> float:
    """Compute a ratio, returning 0.0 if the denominator is non-positive.

    Args:
        num: Numerator.
        den: Denominator.

    Returns:
        num / den, or 0.0 if den <= 0.
    """
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def clip01(value: float) -> float:
    """Clip a value to [0, 1], mapping non-finite to 0.

    Args:
        value: Input value.

    Returns:
        Clipped float in [0.0, 1.0].
    """
    if not math.isfinite(float(value)):
        return 0.0
    return float(min(1.0, max(0.0, float(value))))


def metric_panel(y_true: np.ndarray, proba: np.ndarray, threshold: float, beta: float) -> Tuple[Dict[str, float], Dict[str, int]]:
    """Compute a full panel of binary classification metrics.

    Args:
        y_true: Ground-truth binary labels.
        proba: Predicted probabilities.
        threshold: Decision threshold for binarization.
        beta: Beta parameter for F-beta score.

    Returns:
        Tuple of (metrics dict with accuracy/precision/sensitivity/
        specificity/npv/f1/f2_beta/roc_auc/pr_auc/brier,
        confusion matrix dict).

    Raises:
        ValueError: If proba contains NaN or Inf values.
    """
    if np.any(~np.isfinite(proba)):
        raise ValueError("proba contains NaN or Inf values; cannot compute metrics.")
    y_pred = (proba >= threshold).astype(int)
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
    f1 = 0.0 if (precision + sensitivity) <= 0 else (2.0 * precision * sensitivity) / (precision + sensitivity)
    beta_sq = beta * beta
    f2 = 0.0 if ((beta_sq * precision) + sensitivity) <= 0 else ((1.0 + beta_sq) * precision * sensitivity) / (
        (beta_sq * precision) + sensitivity
    )
    roc_auc = float(roc_auc_score(y_true, proba))
    pr_auc = float(average_precision_score(y_true, proba))
    brier = float(brier_score_loss(y_true, proba))
    # Matthews Correlation Coefficient (Chicco & Jurman, BMC Genomics 2020)
    mcc_denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn) - (fp * fn)) / mcc_denom if mcc_denom > 0 else 0.0

    # Likelihood ratios (clinical decision-making gold standard)
    # Capped at 1000 to avoid JSON serialization issues and CI computation
    # failures.  LR+ > 1000 or LR- < 0.001 are clinically indistinguishable
    # from "perfect" and should not be reported as Infinity.
    _LR_CAP = 1000.0
    lr_positive = sensitivity / (1.0 - specificity) if specificity < 1.0 else _LR_CAP
    lr_negative = (1.0 - sensitivity) / specificity if specificity > 0 else _LR_CAP
    lr_positive = min(float(lr_positive), _LR_CAP)
    lr_negative = min(float(lr_negative), _LR_CAP)

    metrics = {
        "accuracy": clip01(accuracy),
        "precision": clip01(precision),
        "ppv": clip01(precision),
        "npv": clip01(npv),
        "sensitivity": clip01(sensitivity),
        "specificity": clip01(specificity),
        "f1": clip01(f1),
        "f2_beta": clip01(f2),
        "roc_auc": clip01(roc_auc),
        "pr_auc": clip01(pr_auc),
        "brier": clip01(brier),
        "mcc": max(-1.0, min(1.0, mcc)),
        "lr_positive": lr_positive,
        "lr_negative": lr_negative,
    }
    return metrics, cm


def choose_threshold(
    y_valid: np.ndarray,
    proba_valid: np.ndarray,
    beta: float,
    sensitivity_floor: float,
    npv_floor: float,
    specificity_floor: float,
    ppv_floor: float,
    guard_y: Optional[np.ndarray] = None,
    guard_proba: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Choose an operating threshold subject to clinical floor constraints.

    Searches 299 quantile-based thresholds (plus 0.5) and selects
    the one maximizing F-beta while satisfying sensitivity, NPV,
    specificity, and PPV floors. If a guard split is provided,
    joint feasibility is checked.

    Args:
        y_valid: Labels on the selection split.
        proba_valid: Calibrated probabilities on the selection split.
        beta: Beta for F-beta objective.
        sensitivity_floor: Minimum required sensitivity.
        npv_floor: Minimum required NPV.
        specificity_floor: Minimum required specificity.
        ppv_floor: Minimum required PPV.
        guard_y: Optional guard split labels.
        guard_proba: Optional guard split probabilities.

    Returns:
        Dict with selected_threshold, constraint satisfaction flags,
        and selected metrics on both splits.

    Raises:
        ValueError: If no threshold can be chosen.
    """
    quantiles = np.linspace(0.01, 0.99, 299)
    thresholds = sorted(set(float(np.quantile(proba_valid, q)) for q in quantiles) | {0.5})
    candidates: List[Dict[str, Any]] = []

    def floor_margin(metrics: Dict[str, float]) -> Dict[str, float]:
        """Compute margin above each clinical floor constraint.

        Args:
            metrics: Metric panel dict with sensitivity/npv/specificity/ppv.

        Returns:
            Dict with per-constraint margins and feasibility flags.
        """
        sens_margin = float(metrics["sensitivity"]) - float(sensitivity_floor)
        npv_margin = float(metrics["npv"]) - float(npv_floor)
        spec_margin = float(metrics["specificity"]) - float(specificity_floor)
        ppv_margin = float(metrics["ppv"]) - float(ppv_floor)
        all_margins = [sens_margin, npv_margin, spec_margin, ppv_margin]
        return {
            "sensitivity": sens_margin,
            "npv": npv_margin,
            "specificity": spec_margin,
            "ppv": ppv_margin,
            "min": float(min(all_margins)),
            "primary_sum": float(sens_margin + npv_margin),
            "secondary_sum": float(spec_margin + ppv_margin),
        }

    for threshold in thresholds:
        metrics, cm = metric_panel(y_valid, proba_valid, threshold, beta=beta)
        margin = floor_margin(metrics)
        candidate = {
            "threshold": float(threshold),
            "metrics": metrics,
            "confusion_matrix": cm,
            "floor_margin": margin,
            "feasible": bool(
                metrics["sensitivity"] >= sensitivity_floor
                and metrics["npv"] >= npv_floor
                and metrics["specificity"] >= specificity_floor
                and metrics["ppv"] >= ppv_floor
            ),
        }
        candidates.append(candidate)

    selected: Optional[Dict[str, Any]] = None
    feasible = [c for c in candidates if bool(c.get("feasible"))]
    if feasible:
        threshold_pool = feasible
        if (
            guard_y is not None
            and guard_proba is not None
            and int(np.asarray(guard_y).shape[0]) == int(np.asarray(guard_proba).shape[0])
        ):
            for candidate in threshold_pool:
                guard_metrics, _ = metric_panel(
                    np.asarray(guard_y, dtype=int),
                    np.asarray(guard_proba, dtype=float),
                    float(candidate["threshold"]),
                    beta=beta,
                )
                candidate["guard_metrics"] = guard_metrics
                candidate["guard_floor_margin"] = floor_margin(guard_metrics)
                candidate["guard_feasible"] = bool(
                    guard_metrics["sensitivity"] >= sensitivity_floor
                    and guard_metrics["npv"] >= npv_floor
                    and guard_metrics["specificity"] >= specificity_floor
                    and guard_metrics["ppv"] >= ppv_floor
                )
            guard_feasible = [c for c in threshold_pool if bool(c.get("guard_feasible"))]
            if guard_feasible:
                selected = sorted(
                    guard_feasible,
                    key=lambda c: (
                        -float(c["guard_floor_margin"]["min"]),
                        -float(c["guard_floor_margin"]["primary_sum"]),
                        -float(c["guard_metrics"]["f2_beta"]),
                        -float(c["floor_margin"]["min"]),
                        -float(c["floor_margin"]["primary_sum"]),
                        -float(c["guard_floor_margin"]["secondary_sum"]),
                        -float(c["floor_margin"]["secondary_sum"]),
                        -float(c["guard_metrics"]["sensitivity"]),
                        -float(c["guard_metrics"]["npv"]),
                        -float(c["guard_metrics"]["specificity"]),
                        -float(c["guard_metrics"]["ppv"]),
                        float(c["threshold"]),
                    ),
                )[0]
            else:
                spec_target = min(1.0, float(specificity_floor) + 0.05)
                ppv_target = min(1.0, float(ppv_floor) + 0.03)
                guard_min_sensitivity = max(0.0, float(sensitivity_floor) - 0.05)
                guard_min_npv = max(0.0, float(npv_floor) - 0.15)
                stability_pool = [
                    c
                    for c in threshold_pool
                    if float(c["guard_metrics"]["sensitivity"]) >= guard_min_sensitivity
                    and float(c["guard_metrics"]["npv"]) >= guard_min_npv
                ]
                ranked_candidates = stability_pool if stability_pool else threshold_pool
                for candidate in ranked_candidates:
                    gm = candidate["guard_metrics"]
                    deficit_sens = max(0.0, float(sensitivity_floor) - float(gm["sensitivity"]))
                    deficit_npv = max(0.0, float(npv_floor) - float(gm["npv"]))
                    deficit_spec = max(0.0, float(specificity_floor) - float(gm["specificity"]))
                    deficit_ppv = max(0.0, float(ppv_floor) - float(gm["ppv"]))
                    deficits = [deficit_sens, deficit_npv, deficit_spec, deficit_ppv]
                    candidate["guard_deficit"] = {
                        "total": float(sum(deficits)),
                        "max": float(max(deficits)),
                        "sensitivity": float(deficit_sens),
                        "npv": float(deficit_npv),
                        "specificity": float(deficit_spec),
                        "ppv": float(deficit_ppv),
                    }
                    candidate["guard_target_gap"] = {
                        "specificity": abs(float(gm["specificity"]) - float(spec_target)),
                        "ppv": abs(float(gm["ppv"]) - float(ppv_target)),
                    }
                selected = sorted(
                    ranked_candidates,
                    key=lambda c: (
                        float(c["guard_deficit"]["sensitivity"]) + float(c["guard_deficit"]["npv"]),
                        float(c["guard_target_gap"]["specificity"]) + float(c["guard_target_gap"]["ppv"]),
                        -float(c["guard_metrics"]["f2_beta"]),
                        -float(c["guard_metrics"]["specificity"]),
                        -float(c["guard_metrics"]["ppv"]),
                        -float(c["guard_metrics"]["sensitivity"]),
                        -float(c["guard_metrics"]["npv"]),
                        float(c["threshold"]),
                    ),
                )[0]
        else:
            selected = sorted(
                threshold_pool,
                key=lambda c: (
                    -float(c["floor_margin"]["min"]),
                    -float(c["floor_margin"]["primary_sum"]),
                    -float(c["metrics"]["f2_beta"]),
                    -float(c["floor_margin"]["secondary_sum"]),
                    -float(c["metrics"]["sensitivity"]),
                    -float(c["metrics"]["npv"]),
                    -float(c["metrics"]["specificity"]),
                    -float(c["metrics"]["ppv"]),
                    float(c["threshold"]),
                ),
            )[0]
    elif candidates:
        # If no threshold fully satisfies floors on the selection split, pick the
        # clinically closest operating point instead of blindly maximizing F2.
        for candidate in candidates:
            m = candidate["metrics"]
            deficit_sens = max(0.0, float(sensitivity_floor) - float(m["sensitivity"]))
            deficit_npv = max(0.0, float(npv_floor) - float(m["npv"]))
            deficit_spec = max(0.0, float(specificity_floor) - float(m["specificity"]))
            deficit_ppv = max(0.0, float(ppv_floor) - float(m["ppv"]))
            deficits = [deficit_sens, deficit_npv, deficit_spec, deficit_ppv]
            candidate["constraint_deficit"] = {
                "total": float(sum(deficits)),
                "max": float(max(deficits)),
                "sensitivity": float(deficit_sens),
                "npv": float(deficit_npv),
                "specificity": float(deficit_spec),
                "ppv": float(deficit_ppv),
            }
        selected = sorted(
            candidates,
            key=lambda c: (
                float(c["constraint_deficit"]["total"]),
                float(c["constraint_deficit"]["max"]),
                float(c["constraint_deficit"]["specificity"]) + float(c["constraint_deficit"]["ppv"]),
                -float(c["metrics"]["specificity"]),
                -float(c["metrics"]["ppv"]),
                -float(c["metrics"]["sensitivity"]),
                -float(c["metrics"]["npv"]),
                -float(c["metrics"]["f2_beta"]),
                float(c["threshold"]),
            ),
        )[0]
    if selected is None:
        raise ValueError("Unable to choose threshold.")
    selection_ok = bool(selected["feasible"])
    guard_ok: Optional[bool] = None
    if "guard_feasible" in selected:
        guard_ok = bool(selected.get("guard_feasible"))
    overall_ok = bool(selection_ok and (guard_ok if guard_ok is not None else True))
    return {
        "selected_threshold": float(selected["threshold"]),
        "constraints_satisfied_selection_split": selection_ok,
        "constraints_satisfied_guard_split": guard_ok,
        "constraints_satisfied_overall": overall_ok,
        # Backward-compatible legacy field; explicitly aligned to overall status.
        "constraints_satisfied": overall_ok,
        "selected_metrics_on_valid": selected["metrics"],
        "selected_confusion_on_valid": selected["confusion_matrix"],
        "guard_metrics": selected.get("guard_metrics"),
        "sensitivity_floor": float(sensitivity_floor),
        "npv_floor": float(npv_floor),
        "specificity_floor": float(specificity_floor),
        "ppv_floor": float(ppv_floor),
    }


def metric_panel_robust(y_true: np.ndarray, proba: np.ndarray, threshold: float, beta: float) -> Dict[str, float]:
    """Compute a reduced metric panel with fallback for edge cases.

    Unlike metric_panel, catches exceptions in PR-AUC and Brier
    computation and returns fallback values instead of raising.

    Args:
        y_true: Ground-truth binary labels.
        proba: Predicted probabilities.
        threshold: Decision threshold.
        beta: Beta for F-beta score.

    Returns:
        Dict with pr_auc, f2_beta, and brier.
    """
    y_pred = (proba >= threshold).astype(int)
    cm = confusion_counts(y_true, y_pred)
    tp = float(cm["tp"])
    fp = float(cm["fp"])
    fn = float(cm["fn"])
    precision = safe_ratio(tp, tp + fp)
    sensitivity = safe_ratio(tp, tp + fn)
    beta_sq = beta * beta
    f2 = 0.0 if ((beta_sq * precision) + sensitivity) <= 0 else ((1.0 + beta_sq) * precision * sensitivity) / (
        (beta_sq * precision) + sensitivity
    )
    try:
        pr_auc = float(average_precision_score(y_true, proba))
    except Exception as exc:
        print(f"[WARN] pr_auc fallback in metric_panel_robust: {exc}", file=sys.stderr)
        pr_auc = safe_ratio(float(np.sum(y_true.astype(int) == 1)), float(y_true.shape[0]))
    try:
        brier = float(brier_score_loss(y_true, proba))
    except Exception as exc:
        print(f"[WARN] brier fallback in metric_panel_robust: {exc}", file=sys.stderr)
        brier = 1.0
    pr_auc = min(1.0, max(0.0, float(pr_auc)))
    f2 = min(1.0, max(0.0, float(f2)))
    brier = min(1.0, max(0.0, float(brier)))
    return {
        "pr_auc": pr_auc,
        "f2_beta": f2,
        "brier": brier,
    }


def stable_group_index(value: str, n_groups: int) -> int:
    """Map a string to a deterministic group index via SHA-256.

    Args:
        value: Input string (e.g., patient ID).
        n_groups: Number of groups.

    Returns:
        Integer group index in [0, n_groups).
    """
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % n_groups


def cv_oof_proba(
    estimator: BaseEstimator,
    X: pd.DataFrame,
    y: np.ndarray,
    n_splits: int,
    seed: int,
    imbalance_strategy: str = "none",
) -> np.ndarray:
    """Compute out-of-fold probabilities via stratified CV.

    Args:
        estimator: Estimator to clone and fit per fold.
        X: Feature DataFrame.
        y: Binary target array.
        n_splits: Number of CV folds.
        seed: Random seed for fold splitting.

    Returns:
        Array of OOF probabilities aligned with y.

    Raises:
        ValueError: If any OOF values are non-finite.
    """
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    out = np.full(shape=y.shape[0], fill_value=np.nan, dtype=float)
    for fold_idx, (tr_idx, va_idx) in enumerate(splitter.split(X, y), start=1):
        model = clone(estimator)
        model, _ = fit_estimator_with_imbalance(
            estimator=model,
            X_train=X.iloc[tr_idx],
            y_train=y[tr_idx],
            strategy=str(imbalance_strategy),
            seed=int(seed) + int(fold_idx) * _FOLD_IMBALANCE_SEED_STRIDE,
        )
        out[va_idx] = predict_proba_1(model, X.iloc[va_idx])
    if np.any(~np.isfinite(out)):
        raise ValueError("Failed to compute finite OOF probabilities for threshold selection.")
    return out


def load_missingness_policy(path: Optional[str]) -> Dict[str, Any]:
    """Load a missingness policy JSON file.

    Args:
        path: Path to missingness policy JSON, or None.

    Returns:
        Parsed policy dict, or empty dict if path is falsy.

    Raises:
        ValueError: If JSON root is not an object.
    """
    if not path:
        return {}
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Missingness policy not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in missingness policy: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("missingness policy JSON root must be object.")
    return payload


def resolve_imputation_plan(
    policy: Dict[str, Any],
    train_rows: int,
    feature_count: int,
) -> Dict[str, Any]:
    """Resolve an imputation execution plan from missingness policy.

    Applies scale-guard logic for MICE to fall back to simple
    imputation when data dimensions exceed configured thresholds.

    Args:
        policy: Missingness policy dict.
        train_rows: Number of training rows.
        feature_count: Number of features.

    Returns:
        Plan dict with policy_strategy, executed_strategy,
        fit_scope, and scale_guard details.
    """
    strategy = str(policy.get("strategy", "simple_with_indicator")).strip().lower()
    if not strategy:
        strategy = "simple_with_indicator"
    if strategy not in {"simple_with_indicator", "mice", "mice_with_scale_guard"}:
        strategy = "simple_with_indicator"

    plan: Dict[str, Any] = {
        "policy_strategy": strategy,
        "executed_strategy": "simple_with_indicator",
        "fit_scope": str(policy.get("imputer_fit_scope", "train_only")).strip().lower() or "train_only",
        "scale_guard": {
            "checked": strategy == "mice_with_scale_guard",
            "triggered": False,
            "fallback_strategy": None,
            "mice_max_rows": None,
            "mice_max_cols": None,
            "large_data_row_threshold": None,
            "large_data_col_threshold": None,
        },
    }

    if strategy == "mice":
        plan["executed_strategy"] = "mice"
        return plan

    if strategy != "mice_with_scale_guard":
        return plan

    mice_max_rows = policy.get("mice_max_rows", 200000)
    mice_max_cols = policy.get("mice_max_cols", 200)
    large_rows = policy.get("large_data_row_threshold", 1_000_000)
    large_cols = policy.get("large_data_col_threshold", 300)
    try:
        mice_max_rows_i = int(mice_max_rows)
        mice_max_cols_i = int(mice_max_cols)
        large_rows_i = int(large_rows)
        large_cols_i = int(large_cols)
    except Exception as exc:
        print(f"[WARN] imputation scale guard parse error, using defaults: {exc}", file=sys.stderr)
        mice_max_rows_i = 200000
        mice_max_cols_i = 200
        large_rows_i = 1_000_000
        large_cols_i = 300

    should_trigger = (
        train_rows > mice_max_rows_i
        or feature_count > mice_max_cols_i
        or (train_rows >= large_rows_i and feature_count >= large_cols_i)
    )
    plan["executed_strategy"] = "simple_with_indicator" if should_trigger else "mice"
    plan["scale_guard"] = {
        "checked": True,
        "triggered": bool(should_trigger),
        "fallback_strategy": "simple_with_indicator" if should_trigger else None,
        "mice_max_rows": mice_max_rows_i,
        "mice_max_cols": mice_max_cols_i,
        "large_data_row_threshold": large_rows_i,
        "large_data_col_threshold": large_cols_i,
    }
    return plan


def resolve_external_cohorts(
    external_spec: Dict[str, Any],
    external_spec_path: Optional[str],
    feature_cols: Sequence[str],
    default_target_col: str,
    default_patient_id_col: str,
    train_fill_values: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Load and validate external cohort datasets from a spec.

    Args:
        external_spec: Parsed external cohort spec dict.
        external_spec_path: Path to the spec file (for relative paths).
        feature_cols: Feature columns to extract from cohort CSVs.
        default_target_col: Fallback target column name.
        default_patient_id_col: Fallback patient ID column name.
        train_fill_values: Per-feature fill values for missing columns
            (typically train medians). If None, falls back to 0.0.

    Returns:
        List of cohort dicts with X, y, patient_ids, metadata.

    Raises:
        ValueError: If cohort entries are malformed or duplicated.
        FileNotFoundError: If a cohort data file is missing.
    """
    cohorts = external_spec.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        return []

    base = Path(external_spec_path).expanduser().resolve().parent if external_spec_path else Path.cwd()
    out: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(cohorts):
        if not isinstance(entry, dict):
            raise ValueError(f"external cohort entry #{idx} must be object.")

        cohort_id = str(entry.get("cohort_id", "")).strip()
        if not cohort_id:
            raise ValueError(f"external cohort entry #{idx} missing cohort_id.")
        if cohort_id in seen_ids:
            raise ValueError(f"external cohort entry has duplicate cohort_id: {cohort_id}")
        seen_ids.add(cohort_id)

        cohort_type = str(entry.get("cohort_type", "")).strip().lower()
        if cohort_type not in {"cross_period", "cross_institution"}:
            raise ValueError(
                f"external cohort '{cohort_id}' must set cohort_type to cross_period or cross_institution."
            )

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"external cohort '{cohort_id}' missing path.")
        data_path = Path(raw_path.strip()).expanduser()
        if not data_path.is_absolute():
            data_path = (base / data_path).resolve()
        else:
            data_path = data_path.resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"external cohort '{cohort_id}' path not found: {data_path}")

        target_col = str(entry.get("label_col", default_target_col)).strip() or default_target_col
        patient_id_col = str(entry.get("patient_id_col", default_patient_id_col)).strip() or default_patient_id_col

        cohort_df = load_split(str(data_path))
        # If external CSV has original (pre-encoded) columns, apply encoding
        missing_encoded = set(feature_cols) - set(cohort_df.columns)
        if missing_encoded:
            # Attempt to auto-encode: external CSV likely has raw categorical columns
            all_raw_cols = [c for c in cohort_df.columns if c != target_col and c != patient_id_col]
            cohort_encoded = apply_categorical_encoding_to_external(
                cohort_df, list(feature_cols), all_raw_cols,
            )
            # Check for genuinely absent features (all-NaN after encoding).
            # If any features are missing from the external data, skip the
            # cohort entirely — filling with constants invalidates external
            # validation because the model receives fabricated inputs.
            absent_features = [
                col for col in feature_cols
                if col in cohort_encoded.columns and cohort_encoded[col].isna().all()
            ]
            if absent_features:
                warnings.warn(
                    f"Skipping external cohort '{cohort_id}': {len(absent_features)} "
                    f"feature(s) absent from external data and cannot be "
                    f"reconstructed: {absent_features}. External validation "
                    f"requires feature-consistent datasets.",
                    stacklevel=2,
                )
                continue
            cohort_df = pd.concat([cohort_df[[c for c in [target_col, patient_id_col] if c in cohort_df.columns]], cohort_encoded], axis=1)
        X_ext, y_ext = prepare_xy(cohort_df, feature_cols=feature_cols, target_col=target_col)
        if patient_id_col in cohort_df.columns:
            patient_ids = cohort_df[patient_id_col].astype(str).tolist()
        else:
            patient_ids = [f"{cohort_id}_{i}" for i in range(int(cohort_df.shape[0]))]

        out.append(
            {
                "cohort_id": cohort_id,
                "cohort_type": cohort_type,
                "data_path": str(data_path),
                "frame": cohort_df,
                "target_col": target_col,
                "patient_id_col": patient_id_col,
                "X": X_ext,
                "y": y_ext,
                "patient_ids": patient_ids,
                "row_count": int(cohort_df.shape[0]),
            }
        )
    return out


def build_prediction_trace_rows(
    scope: str,
    cohort_id: str,
    cohort_type: str,
    patient_ids: Sequence[str],
    y_true: np.ndarray,
    y_score: np.ndarray,
    threshold: float,
    model_id: str,
) -> pd.DataFrame:
    """Build a prediction trace DataFrame for one split/cohort.

    Args:
        scope: Split scope ('train', 'valid', 'test', 'external').
        cohort_id: Cohort identifier string.
        cohort_type: Cohort type ('' for internal, or cross_period/cross_institution).
        patient_ids: Per-row patient identifiers.
        y_true: Ground-truth binary labels.
        y_score: Calibrated predicted probabilities.
        threshold: Selected decision threshold.
        model_id: Selected model identifier.

    Returns:
        DataFrame with columns: scope, cohort_id, cohort_type,
        hashed_patient_id, y_true, y_score, y_pred,
        selected_threshold, model_id.

    Raises:
        ValueError: If patient_ids length mismatches y_true.
    """
    y_pred = (y_score >= threshold).astype(int)
    if len(patient_ids) != int(y_true.shape[0]):
        raise ValueError(f"prediction trace patient ID length mismatch for {scope}/{cohort_id}.")
    payload = {
        "scope": [scope] * int(y_true.shape[0]),
        "cohort_id": [cohort_id] * int(y_true.shape[0]),
        "cohort_type": [cohort_type] * int(y_true.shape[0]),
        "hashed_patient_id": [sha256_text(str(pid)) for pid in patient_ids],
        "y_true": y_true.astype(int),
        "y_score": y_score.astype(float),
        "y_pred": y_pred.astype(int),
        "selected_threshold": [float(threshold)] * int(y_true.shape[0]),
        "model_id": [model_id] * int(y_true.shape[0]),
    }
    return pd.DataFrame(payload)


def _bca_ci(boot_stats: np.ndarray, original_stat: float, jackknife_stats: np.ndarray, alpha: float = 0.05) -> Tuple[float, float]:
    """Compute BCa (Bias-Corrected and Accelerated) confidence interval.

    Falls back to percentile method if BCa computation fails (e.g., zero
    acceleration due to identical jackknife values).

    References:
        Efron & Tibshirani 1993, Chapter 14.
    """
    from scipy import stats as _sp_stats

    n_boot = len(boot_stats)
    if n_boot < 50:
        lo, hi = np.percentile(boot_stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        return float(lo), float(hi)

    # Bias correction factor z0
    proportion_below = np.mean(boot_stats < original_stat)
    proportion_below = np.clip(proportion_below, 1e-10, 1.0 - 1e-10)
    z0 = float(_sp_stats.norm.ppf(proportion_below))

    # Acceleration factor a (from jackknife)
    jk_mean = np.mean(jackknife_stats)
    diffs = jk_mean - jackknife_stats
    denom = np.sum(diffs ** 2)
    if denom < 1e-30:
        # No variation in jackknife → fallback to percentile
        lo, hi = np.percentile(boot_stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        return float(lo), float(hi)
    a = float(np.sum(diffs ** 3) / (6.0 * denom ** 1.5))

    # Adjusted quantiles
    z_alpha_lo = float(_sp_stats.norm.ppf(alpha / 2))
    z_alpha_hi = float(_sp_stats.norm.ppf(1 - alpha / 2))

    def _adj(z_a: float) -> float:
        num = z0 + z_a
        denom_val = 1.0 - a * num
        if abs(denom_val) < 1e-10:
            return z_a  # fallback
        return float(_sp_stats.norm.cdf(z0 + num / denom_val))

    q_lo = max(0.0, min(1.0, _adj(z_alpha_lo)))
    q_hi = max(0.0, min(1.0, _adj(z_alpha_hi)))

    lo = float(np.percentile(boot_stats, 100 * q_lo))
    hi = float(np.percentile(boot_stats, 100 * q_hi))
    return lo, hi


def bootstrap_ci_pr_auc(y_true: np.ndarray, proba: np.ndarray, n_resamples: int, seed: int) -> Tuple[float, float, int]:
    """Compute 95% bootstrap CI for PR-AUC.

    Args:
        y_true: Ground-truth binary labels.
        proba: Predicted probabilities.
        n_resamples: Target number of valid bootstrap samples.
        seed: Random seed.

    Returns:
        Tuple of (CI lower bound, CI upper bound, actual resample count).

    Raises:
        ValueError: If fewer than 200 valid resamples are obtained.
    """
    y_arr = np.asarray(y_true)
    if y_arr.size == 0 or len(np.unique(y_arr)) < 2:
        return float("nan"), float("nan"), 0
    rng = np.random.default_rng(seed)
    hits: List[float] = []
    max_attempts = max(5 * n_resamples, 2000)
    attempts = 0
    while len(hits) < n_resamples and attempts < max_attempts:
        attempts += 1
        idx = stratified_bootstrap_indices(y_true, rng)
        if idx is None:
            break
        yb = y_true[idx]
        pb = proba[idx]
        hits.append(float(average_precision_score(yb, pb)))
    if len(hits) < 200:
        raise ValueError(f"Insufficient bootstrap resamples for CI: {len(hits)}")
    arr = np.asarray(hits, dtype=float)
    # BCa CI: compute original statistic + jackknife for acceleration.
    # For large n (>2000), use subsampled jackknife (m random leave-one-out
    # folds) to avoid O(n^2 log n) cost while preserving BCa properties.
    original_stat = float(average_precision_score(y_true, proba))
    n = len(y_true)
    max_jk = 2000  # cap jackknife iterations for performance
    if n <= max_jk:
        jk_indices = range(n)
    else:
        jk_rng = np.random.RandomState(seed + 99)
        jk_indices = jk_rng.choice(n, size=max_jk, replace=False)
    jk_stats = np.empty(len(jk_indices), dtype=float)
    for j, i in enumerate(jk_indices):
        mask = np.concatenate([np.arange(i), np.arange(i + 1, n)])
        y_jk = y_true[mask]
        if len(np.unique(y_jk)) < 2:
            jk_stats[j] = original_stat
        else:
            jk_stats[j] = float(average_precision_score(y_jk, proba[mask]))
    lo, hi = _bca_ci(arr, original_stat, jk_stats, alpha=0.05)
    return float(lo), float(hi), int(len(hits))


def bootstrap_optimism_correction(
    estimator: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    threshold: float,
    beta: float,
    n_resamples: int,
    seed: int,
    metrics_of_interest: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """Estimate optimism via bootstrap internal validation (Steyerberg 2019).

    For each bootstrap resample:
      1. Clone and fit estimator on bootstrap sample.
      2. Score on bootstrap sample (apparent performance).
      3. Score on original training set (test performance).
      4. optimism_i = apparent_i - test_i
    Final: optimism = mean(optimism_i)
           corrected = apparent_original - optimism

    Args:
        estimator: Fitted sklearn estimator (will be cloned, not mutated).
        X_train: Original training features.
        y_train: Original training labels.
        threshold: Decision threshold for metric_panel.
        beta: Beta for F-beta score.
        n_resamples: Number of bootstrap iterations.
        seed: Random seed.
        metrics_of_interest: Subset of metrics to correct (default: pr_auc, roc_auc, brier).

    Returns:
        Dict mapping metric name to {apparent, optimism, corrected, n_resamples}.
    """
    from sklearn.base import clone as sklearn_clone

    if metrics_of_interest is None:
        metrics_of_interest = ["pr_auc", "roc_auc", "brier"]

    rng = np.random.default_rng(seed)
    optimisms: Dict[str, List[float]] = {m: [] for m in metrics_of_interest}

    # Apparent performance on original training data
    try:
        train_proba = estimator.predict_proba(X_train)[:, 1]
    except Exception as exc:
        print(f"[WARN] bootstrap_optimism: predict_proba failed: {exc}", file=sys.stderr)
        return {}
    apparent_panel, _ = metric_panel(y_train, train_proba, threshold, beta=beta)

    lower_is_better = {"brier"}
    max_attempts = max(3 * n_resamples, 1000)
    attempts = 0
    completed = 0

    while completed < n_resamples and attempts < max_attempts:
        attempts += 1
        idx = stratified_bootstrap_indices(y_train, rng)
        if idx is None:
            break
        X_boot = X_train.iloc[idx] if hasattr(X_train, "iloc") else X_train[idx]
        y_boot = y_train[idx] if not hasattr(y_train, "iloc") else y_train.iloc[idx]

        try:
            boot_est = sklearn_clone(estimator)
            boot_est.fit(X_boot, y_boot)
            # Apparent: score on bootstrap sample
            boot_proba_apparent = boot_est.predict_proba(X_boot)[:, 1]
            panel_apparent, _ = metric_panel(y_boot, boot_proba_apparent, threshold, beta=beta)
            # Test: score on original full training set
            boot_proba_test = boot_est.predict_proba(X_train)[:, 1]
            panel_test, _ = metric_panel(y_train, boot_proba_test, threshold, beta=beta)
        except Exception as exc:
            print(f"[WARN] bootstrap_optimism iteration skipped: {exc}", file=sys.stderr)
            continue

        valid = True
        for m in metrics_of_interest:
            va = panel_apparent.get(m)
            vt = panel_test.get(m)
            if va is None or vt is None or not math.isfinite(float(va)) or not math.isfinite(float(vt)):
                valid = False
                break
        if not valid:
            continue

        for m in metrics_of_interest:
            optimisms[m].append(float(panel_apparent[m]) - float(panel_test[m]))
        completed += 1

    result: Dict[str, Dict[str, float]] = {}
    for m in metrics_of_interest:
        arr = optimisms[m]
        if not arr:
            continue
        mean_optimism = float(np.mean(arr))
        apparent_val = float(apparent_panel.get(m, 0.0))
        corrected = apparent_val - mean_optimism
        result[m] = {
            "apparent": apparent_val,
            "optimism": mean_optimism,
            "corrected": corrected,
            "n_resamples": len(arr),
        }
    return result


def learning_curve_data(
    estimator: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    threshold: float,
    beta: float,
    seed: int,
    n_points: int = 8,
    metric: str = "pr_auc",
) -> Dict[str, Any]:
    """Compute learning curve: performance vs. training set size.

    Trains on increasing fractions of the training data and evaluates on
    the held-out validation set to assess whether the model has converged.

    Convergence criterion: the last 3 points have relative std < 2% of
    the mean, indicating marginal returns from additional data.

    Args:
        estimator: Sklearn estimator (will be cloned per fraction).
        X_train: Full training features.
        y_train: Full training labels.
        X_valid: Validation features (held constant).
        y_valid: Validation labels (held constant).
        threshold: Decision threshold for metric_panel.
        beta: Beta for F-beta score.
        seed: Random seed.
        n_points: Number of fractions to evaluate (default 8).
        metric: Primary metric for convergence check (default pr_auc).

    Returns:
        Dict with fractions, train_sizes, train_scores, valid_scores,
        converged flag, and convergence details.
    """
    from sklearn.base import clone as sklearn_clone
    from sklearn.model_selection import StratifiedShuffleSplit

    n_total = X_train.shape[0]
    min_fraction = max(50 / n_total, 0.1) if n_total > 50 else 0.5
    fractions = np.linspace(min_fraction, 1.0, n_points).tolist()

    curve: List[Dict[str, Any]] = []
    rng = np.random.default_rng(seed)

    for frac in fractions:
        n_samples = max(int(round(frac * n_total)), 20)
        n_samples = min(n_samples, n_total)

        if n_samples == n_total:
            idx = np.arange(n_total)
        else:
            # Stratified subsample
            try:
                splitter = StratifiedShuffleSplit(
                    n_splits=1, train_size=n_samples, random_state=int(rng.integers(0, 2**31)),
                )
                idx, _ = next(splitter.split(X_train, y_train))
            except ValueError:
                idx = rng.choice(n_total, size=n_samples, replace=False)

        X_sub = X_train.iloc[idx] if hasattr(X_train, "iloc") else X_train[idx]
        y_sub = y_train[idx] if not hasattr(y_train, "iloc") else y_train.iloc[idx]

        try:
            est = sklearn_clone(estimator)
            est.fit(X_sub, y_sub)
            train_proba = est.predict_proba(X_sub)[:, 1]
            valid_proba = est.predict_proba(X_valid)[:, 1]
            train_panel, _ = metric_panel(y_sub, train_proba, threshold, beta=beta)
            valid_panel, _ = metric_panel(y_valid, valid_proba, threshold, beta=beta)

            curve.append({
                "fraction": round(frac, 4),
                "train_size": n_samples,
                "train_score": float(train_panel.get(metric, 0.0)),
                "valid_score": float(valid_panel.get(metric, 0.0)),
            })
        except Exception as exc:
            curve.append({
                "fraction": round(frac, 4),
                "train_size": n_samples,
                "train_score": None,
                "valid_score": None,
                "error": str(exc),
            })

    # Convergence check: last 3 valid scores have relative std < 2%
    valid_scores = [p["valid_score"] for p in curve if p.get("valid_score") is not None]
    converged = False
    convergence_detail = {}
    if len(valid_scores) >= 3:
        tail = valid_scores[-3:]
        tail_mean = float(np.mean(tail))
        tail_std = float(np.std(tail))
        relative_std = tail_std / tail_mean if tail_mean > 0 else None
        converged = relative_std is not None and relative_std < 0.02
        convergence_detail = {
            "tail_mean": round(tail_mean, 6),
            "tail_std": round(tail_std, 6),
            "relative_std": round(relative_std, 6),
            "threshold": 0.02,
        }

    return {
        "metric": metric,
        "curve": curve,
        "converged": converged,
        "convergence_detail": convergence_detail,
    }


def stratified_bootstrap_indices(y_true: np.ndarray, rng: np.random.Generator) -> Optional[np.ndarray]:
    """Generate stratified bootstrap sample indices.

    Args:
        y_true: Binary labels array.
        rng: NumPy random Generator.

    Returns:
        Shuffled index array preserving class ratio, or None if
        either class is absent.
    """
    pos = np.where(y_true == 1)[0]
    neg = np.where(y_true == 0)[0]
    if pos.size == 0 or neg.size == 0:
        return None
    sample_pos = rng.choice(pos, size=pos.size, replace=True)
    sample_neg = rng.choice(neg, size=neg.size, replace=True)
    idx = np.concatenate([sample_pos, sample_neg], axis=0)
    rng.shuffle(idx)
    return idx


def bootstrap_metric_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    threshold: float,
    beta: float,
    n_resamples: int,
    seed: int,
) -> Tuple[Dict[str, Dict[str, float]], int]:
    """Compute 95% bootstrap CIs for all metric_panel metrics.

    Args:
        y_true: Ground-truth binary labels.
        y_score: Predicted probabilities.
        threshold: Decision threshold.
        beta: Beta for F-beta score.
        n_resamples: Target number of valid bootstrap iterations.
        seed: Random seed.

    Returns:
        Tuple of (dict mapping metric name to ci_lower/ci_upper/ci_width,
        effective number of resamples).
    """
    rng = np.random.default_rng(seed)
    hits: Dict[str, List[float]] = {metric: [] for metric in ("accuracy", "precision", "ppv", "npv", "sensitivity", "specificity", "f1", "f2_beta", "roc_auc", "pr_auc", "brier", "mcc", "lr_positive", "lr_negative")}
    attempts = 0
    max_attempts = max(5 * int(n_resamples), 8000)
    while len(hits["pr_auc"]) < int(n_resamples) and attempts < max_attempts:
        attempts += 1
        idx = stratified_bootstrap_indices(y_true, rng)
        if idx is None:
            break
        yb = y_true[idx]
        sb = y_score[idx]
        try:
            panel, _ = metric_panel(yb, sb, threshold, beta=beta)
        except Exception as exc:
            print(f"[WARN] bootstrap_ci iteration skipped: {exc}", file=sys.stderr)
            continue
        _finite_required = {"accuracy", "precision", "ppv", "npv", "sensitivity", "specificity", "f1", "f2_beta", "roc_auc", "pr_auc", "brier", "mcc"}
        if not all(isinstance(panel.get(k), (int, float)) and math.isfinite(float(panel.get(k))) for k in _finite_required):
            continue
        for metric in hits:
            val = float(panel[metric])
            if math.isfinite(val):
                hits[metric].append(val)
    effective = min((len(v) for v in hits.values()), default=0)
    summary: Dict[str, Dict[str, float]] = {}
    for metric, values in hits.items():
        arr = np.asarray(values[:effective], dtype=float)
        if arr.size == 0:
            summary[metric] = {"ci_lower": None, "ci_upper": None, "ci_width": None}
            continue
        # Percentile CI for supplementary metrics (BCa used for primary
        # PR-AUC in bootstrap_ci_pr_auc; jackknife per-metric here would
        # be O(n * n_metrics) and is not justified for 14 supplementary metrics).
        lo, hi = np.percentile(arr, [2.5, 97.5]).tolist()
        summary[metric] = {
            "ci_lower": float(lo),
            "ci_upper": float(hi),
            "ci_width": float(hi - lo),
            "ci_method": "percentile",
        }
    return summary, int(effective)


def js_divergence_from_probs(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Jensen-Shannon divergence between two probability arrays.

    Args:
        a: First probability/count array.
        b: Second probability/count array.

    Returns:
        JSD value in bits (base-2 log).
    """
    eps = 1e-12
    a = np.asarray(a, dtype=float) + eps
    b = np.asarray(b, dtype=float) + eps
    a = a / float(np.sum(a))
    b = b / float(np.sum(b))
    m = 0.5 * (a + b)
    return float(0.5 * (np.sum(a * np.log(a / m)) + np.sum(b * np.log(b / m))) / math.log(2.0))


def feature_jsd(train: pd.Series, other: pd.Series) -> Optional[float]:
    """Compute Jensen-Shannon divergence between two feature distributions.

    Uses histogram binning for numeric features and value counts for
    categorical features.

    Args:
        train: Training split feature series.
        other: Comparison split feature series.

    Returns:
        JSD value, or None if either series is empty or bins are
        insufficient.
    """
    tr = train.dropna()
    ot = other.dropna()
    if tr.empty or ot.empty:
        return None
    tr_num = pd.to_numeric(tr, errors="coerce")
    ot_num = pd.to_numeric(ot, errors="coerce")
    if tr_num.notna().sum() >= max(10, int(0.5 * len(tr))) and ot_num.notna().sum() >= max(10, int(0.5 * len(ot))):
        tr_arr = tr_num.dropna().to_numpy(dtype=float)
        ot_arr = ot_num.dropna().to_numpy(dtype=float)
        bins = np.unique(np.quantile(tr_arr, np.linspace(0.0, 1.0, 11)))
        if bins.size < 3:
            return None
        tr_hist, _ = np.histogram(tr_arr, bins=bins)
        ot_hist, _ = np.histogram(ot_arr, bins=bins)
        return js_divergence_from_probs(tr_hist, ot_hist)
    tr_cat = tr.astype(str)
    ot_cat = ot.astype(str)
    keys = sorted(set(tr_cat.unique().tolist()) | set(ot_cat.unique().tolist()))
    if not keys:
        return None
    tr_counts = tr_cat.value_counts(normalize=True)
    ot_counts = ot_cat.value_counts(normalize=True)
    a = np.asarray([float(tr_counts.get(k, 0.0)) for k in keys], dtype=float)
    b = np.asarray([float(ot_counts.get(k, 0.0)) for k in keys], dtype=float)
    return js_divergence_from_probs(a, b)


from _gate_utils import write_json  # noqa: E402 — atomic JSON write with NaN sanitization


def summarize_seed_metric(values: Sequence[float]) -> Dict[str, float]:
    """Compute summary statistics for a list of metric values.

    Args:
        values: Sequence of float metric values.

    Returns:
        Dict with mean, std, min, max, range, and n.

    Raises:
        ValueError: If values is empty.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError("Cannot summarize empty metric list.")
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "range": float(arr.max() - arr.min()),
        "n": int(arr.size),
    }


def build_distribution_report(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    test_df: pd.DataFrame,
    external_frames: List[Dict[str, Any]],
    target_col: str,
    feature_cols: Sequence[str],
) -> Dict[str, Any]:
    """Build a feature distribution shift report across splits.

    Computes per-feature JSD, missingness delta, and prevalence delta
    between training and each comparison split.

    Args:
        train_df: Training DataFrame.
        valid_df: Validation DataFrame.
        test_df: Test DataFrame.
        external_frames: List of dicts with 'cohort_id' and 'frame'.
        target_col: Target column name.
        feature_cols: Feature column names.

    Returns:
        Distribution report dict with schema_version, distribution_matrix,
        and metadata.
    """
    rows: List[Dict[str, Any]] = []
    comparisons: List[Tuple[str, pd.DataFrame]] = []
    if len(valid_df) > 0:
        comparisons.append(("valid", valid_df))
    if len(test_df) > 0:
        comparisons.append(("test", test_df))
    for ext in external_frames:
        split_name = f"external:{ext['cohort_id']}"
        comparisons.append((split_name, ext["frame"]))

    for split_name, frame in comparisons:
        jsd_values: List[float] = []
        missing_deltas: List[float] = []
        for feature in feature_cols:
            if feature not in frame.columns:
                continue
            jsd = feature_jsd(train_df[feature], frame[feature])
            if jsd is not None and math.isfinite(jsd):
                jsd_values.append(float(jsd))
            tr_missing = float(train_df[feature].isna().mean())
            ot_missing = float(frame[feature].isna().mean())
            missing_deltas.append(abs(ot_missing - tr_missing))

        y_train = pd.to_numeric(train_df[target_col], errors="coerce")
        y_other = pd.to_numeric(frame[target_col], errors="coerce")
        prev_train = float(y_train.mean()) if y_train.notna().any() else None
        prev_other = float(y_other.mean()) if y_other.notna().any() else None
        prevalence_delta = abs(prev_other - prev_train) if prev_train is not None and prev_other is not None else None
        rows.append(
            {
                "split": split_name,
                "feature_count": int(len(feature_cols)),
                "top_feature_jsd": float(max(jsd_values)) if jsd_values else 0.0,
                "mean_feature_jsd": float(np.mean(jsd_values)) if jsd_values else 0.0,
                "max_missing_ratio_delta": float(max(missing_deltas)) if missing_deltas else 0.0,
                "prevalence_delta": float(prevalence_delta) if prevalence_delta is not None else None,
            }
        )

    return {
        "schema_version": "v4.0",
        "distribution_matrix": rows,
        "metadata": {
            "train_rows": int(train_df.shape[0]),
            "valid_rows": int(valid_df.shape[0]),
            "test_rows": int(test_df.shape[0]),
            "external_cohort_count": int(len(external_frames)),
        },
    }


def build_ci_matrix_report(
    split_payloads: Dict[str, Dict[str, Any]],
    external_payloads: List[Dict[str, Any]],
    beta: float,
    n_resamples: int,
    seed: int,
) -> Dict[str, Any]:
    """Build a CI matrix report across all splits and external cohorts.

    Args:
        split_payloads: Dict mapping split name to dict with
            y_true, y_score, threshold.
        external_payloads: List of dicts with cohort_id, cohort_type,
            y_true, y_score, threshold.
        beta: Beta for F-beta score.
        n_resamples: Bootstrap resample count per split.
        seed: Random seed.

    Returns:
        CI matrix report dict with split_metrics_ci,
        transport_drop_ci, and ci_quality_summary.
    """
    split_metrics_ci: Dict[str, Any] = {}
    for idx, (split_name, payload) in enumerate(split_payloads.items()):
        y_true = payload["y_true"]
        y_score = payload["y_score"]
        threshold = float(payload["threshold"])
        point_metrics, _ = metric_panel(y_true, y_score, threshold, beta=beta)
        ci_summary, effective = bootstrap_metric_ci(
            y_true=y_true,
            y_score=y_score,
            threshold=threshold,
            beta=beta,
            n_resamples=int(n_resamples),
            seed=int(seed + idx * 17),
        )
        metrics_block: Dict[str, Any] = {}
        for metric_name, point_value in point_metrics.items():
            ci = ci_summary.get(metric_name, {})
            ci_lo = ci.get("ci_lower")
            ci_hi = ci.get("ci_upper")
            lo = float(ci_lo) if ci_lo is not None else None
            hi = float(ci_hi) if ci_hi is not None else None
            width = round(hi - lo, 6) if lo is not None and hi is not None else None
            metrics_block[metric_name] = {
                "point": float(point_value),
                "ci_95": [lo, hi],
                "ci_width": width,
                "n_resamples": int(effective),
            }
        split_metrics_ci[split_name] = {
            "row_count": int(len(y_true)),
            "positive_count": int(np.sum(np.asarray(y_true, dtype=int) == 1)),
            "selected_threshold": float(threshold),
            "metrics": metrics_block,
        }

    external_metrics_ci: Dict[str, Any] = {}
    for idx, payload in enumerate(external_payloads):
        cohort_id = str(payload["cohort_id"])
        y_true = payload["y_true"]
        y_score = payload["y_score"]
        threshold = float(payload["threshold"])
        point_metrics, _ = metric_panel(y_true, y_score, threshold, beta=beta)
        ci_summary, effective = bootstrap_metric_ci(
            y_true=y_true,
            y_score=y_score,
            threshold=threshold,
            beta=beta,
            n_resamples=int(n_resamples),
            seed=int(seed + 900 + idx * 29),
        )
        metrics_block: Dict[str, Any] = {}
        for metric_name, point_value in point_metrics.items():
            ci = ci_summary.get(metric_name, {})
            ci_lo = ci.get("ci_lower")
            ci_hi = ci.get("ci_upper")
            lo = float(ci_lo) if ci_lo is not None else None
            hi = float(ci_hi) if ci_hi is not None else None
            width = round(hi - lo, 6) if lo is not None and hi is not None else None
            metrics_block[metric_name] = {
                "point": float(point_value),
                "ci_95": [lo, hi],
                "ci_width": width,
                "n_resamples": int(effective),
            }
        external_metrics_ci[cohort_id] = {
            "cohort_type": str(payload["cohort_type"]),
            "row_count": int(len(y_true)),
            "positive_count": int(np.sum(np.asarray(y_true, dtype=int) == 1)),
            "selected_threshold": float(threshold),
            "metrics": metrics_block,
        }

    transport_drop_ci: Dict[str, Any] = {}
    internal_test = split_metrics_ci.get("test")
    if isinstance(internal_test, dict) and isinstance(internal_test.get("metrics"), dict):
        for cohort_id, ext in external_metrics_ci.items():
            ext_metrics = ext.get("metrics") if isinstance(ext, dict) else None
            if not isinstance(ext_metrics, dict):
                continue
            transport_drop_ci[cohort_id] = {
                "pr_auc_drop": {
                    "point": float(internal_test["metrics"]["pr_auc"]["point"] - ext_metrics["pr_auc"]["point"]),
                    "ci_95": None,
                    "ci_width": None,
                    "ci_note": "not_computed_point_estimate_only",
                    "n_resamples": int(ext_metrics["pr_auc"]["n_resamples"]),
                },
                "f2_beta_drop": {
                    "point": float(internal_test["metrics"]["f2_beta"]["point"] - ext_metrics["f2_beta"]["point"]),
                    "ci_95": None,
                    "ci_width": None,
                    "ci_note": "not_computed_point_estimate_only",
                    "n_resamples": int(ext_metrics["f2_beta"]["n_resamples"]),
                },
                "brier_increase": {
                    "point": float(ext_metrics["brier"]["point"] - internal_test["metrics"]["brier"]["point"]),
                    "ci_95": None,
                    "ci_width": None,
                    "ci_note": "not_computed_point_estimate_only",
                    "n_resamples": int(ext_metrics["brier"]["n_resamples"]),
                },
            }

    return {
        "status": "pass",
        "schema_version": "v4.0",
        "split_metrics_ci": {**split_metrics_ci, "external": external_metrics_ci},
        "transport_drop_ci": transport_drop_ci,
        "ci_quality_summary": {
            "required_resamples": int(n_resamples),
            "split_count": int(len(split_metrics_ci)),
            "external_count": int(len(external_metrics_ci)),
        },
    }


def _calibration_assessment(
    y_true: "np.ndarray",
    proba: "np.ndarray",
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Compute calibration slope, intercept, E:O ratio, and binned curve.

    TRIPOD+AI Item 15d: calibration plot, slope, intercept.

    Args:
        y_true: Binary ground truth labels.
        proba: Predicted probabilities.
        n_bins: Number of bins for calibration curve.

    Returns:
        Dict with slope, intercept, expected_observed_ratio, and bin data.
    """
    from sklearn.calibration import calibration_curve as _cal_curve

    result: Dict[str, Any] = {}
    # E:O ratio (expected / observed)
    observed = float(np.sum(y_true))
    expected = float(np.sum(proba))
    result["expected_observed_ratio"] = round(expected / max(observed, 1e-12), 4)
    # Calibration slope & intercept via logistic regression on logit(proba)
    eps = 1e-7
    proba_clip = np.clip(proba, eps, 1.0 - eps)
    logit_p = np.log(proba_clip / (1.0 - proba_clip))
    try:
        from sklearn.linear_model import LogisticRegression as _LR
        cal_lr = _LR(max_iter=2000, solver="lbfgs", C=np.inf)
        cal_lr.fit(logit_p.reshape(-1, 1), y_true)
        result["calibration_slope"] = round(float(cal_lr.coef_[0, 0]), 4)
        result["calibration_intercept"] = round(float(cal_lr.intercept_[0]), 4)
    except Exception as exc:
        print(f"[WARN] calibration_slope computation failed: {exc}", file=sys.stderr)
        result["calibration_slope"] = None
        result["calibration_intercept"] = None
    # Expected Calibration Error (equal-frequency bins)
    try:
        n_samples = len(y_true)
        ece_bins = min(n_bins, max(2, n_samples // 15))
        order = np.argsort(proba)
        blocks = np.array_split(order, ece_bins)
        ece_total = 0.0
        for blk in blocks:
            if len(blk) == 0:
                continue
            avg_pred = float(np.mean(proba[blk]))
            avg_true = float(np.mean(y_true[blk]))
            ece_total += (len(blk) / n_samples) * abs(avg_true - avg_pred)
        result["ece"] = round(float(ece_total), 4)
    except Exception as exc:
        print(f"[WARN] ECE computation failed: {exc}", file=sys.stderr)
        result["ece"] = None
    # Binned calibration curve
    try:
        frac_pos, mean_pred = _cal_curve(y_true, proba, n_bins=n_bins, strategy="uniform")
        result["calibration_curve"] = {
            "n_bins": int(n_bins),
            "fraction_of_positives": [round(float(v), 4) for v in frac_pos],
            "mean_predicted_value": [round(float(v), 4) for v in mean_pred],
        }
    except Exception as exc:
        print(f"[WARN] calibration_curve computation failed: {exc}", file=sys.stderr)
        result["calibration_curve"] = None
    return result


def _annotate_calibration_resampling_risk(
    calibration: Dict[str, Any],
    candidate_row: Optional[Dict[str, Any]],
    calibration_method: str = "none",
) -> Dict[str, Any]:
    """Add resampling calibration warning for internal-imbalance models.

    Models in INTERNAL_IMBALANCE_FAMILIES (BRF, EasyEnsemble, RUSBoost)
    use balanced bootstrap or undersampling internally. This shifts
    predicted probabilities and inflates calibration slope (van den
    Goorbergh et al., BMC Med Res Methodol 2022;22:312).

    Always annotates calibration_assessment with a resampling risk
    note for these families, including the actual slope deviation.
    """
    if not isinstance(calibration, dict) or calibration.get("skipped"):
        return calibration
    if not isinstance(candidate_row, dict):
        return calibration

    family = str(candidate_row.get("base_model_id", ""))
    if family not in INTERNAL_IMBALANCE_FAMILIES:
        return calibration

    slope = calibration.get("calibration_slope")
    if slope is None:
        return calibration

    deviation = abs(float(slope) - 1.0)
    auto_calibrated = calibration_method != "none"
    if auto_calibrated:
        warning = (
            f"{family} uses internal resampling — auto-calibrated with "
            f"{calibration_method}. Post-calibration slope={slope:.3f} "
            f"(deviation={deviation:.3f}). "
            f"Ref: van den Goorbergh et al., BMC Med Res Methodol 2022;22:312."
        )
    else:
        warning = (
            f"{family} uses internal resampling (balanced bootstrap / undersampling) "
            f"which shifts predicted probabilities. Calibration slope={slope:.3f} "
            f"(deviation={deviation:.3f} from ideal 1.0). "
            f"Post-hoc recalibration (Platt/isotonic) is recommended. "
            f"Ref: van den Goorbergh et al., BMC Med Res Methodol 2022;22:312."
        )
    calibration["resampling_calibration_risk"] = {
        "model_family": family,
        "slope_deviation_from_unity": round(deviation, 4),
        "auto_calibrated": auto_calibrated,
        "calibration_method": calibration_method,
        "warning": warning,
    }
    return calibration


def _decision_curve_analysis(
    y_true: "np.ndarray",
    proba: "np.ndarray",
    thresholds: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Compute net benefit at various threshold probabilities for DCA.

    TRIPOD+AI Item 15e: decision curve analysis.

    Net benefit = TP/N - FP/N * (pt / (1 - pt))
    where pt is the threshold probability.

    Args:
        y_true: Binary ground truth labels.
        proba: Predicted probabilities.
        thresholds: Threshold probabilities to evaluate.

    Returns:
        Dict with threshold, net_benefit_model, net_benefit_treat_all.
    """
    if thresholds is None:
        thresholds = [round(t, 2) for t in np.arange(0.05, 1.00, 0.05).tolist()]
    n = len(y_true)
    prevalence = float(np.mean(y_true))
    results = []
    for pt in thresholds:
        pred = (proba >= pt).astype(int)
        tp = int(np.sum((pred == 1) & (y_true == 1)))
        fp = int(np.sum((pred == 1) & (y_true == 0)))
        weight = pt / max(1.0 - pt, 1e-12)
        nb_model = (tp / n) - (fp / n) * weight
        nb_all = prevalence - (1.0 - prevalence) * weight
        results.append({
            "threshold": round(pt, 2),
            "net_benefit_model": round(float(nb_model), 6),
            "net_benefit_treat_all": round(float(nb_all), 6),
            "net_benefit_treat_none": 0.0,
        })
    return {"thresholds": results}


def _sample_size_adequacy(
    n_events: int,
    n_features: int,
    n_total: int,
) -> Dict[str, Any]:
    """Report sample size adequacy using events-per-variable (EPV).

    PROBAST domain 3: EPV >= 10 is minimum, >= 20 is recommended.
    Riley et al. (2020) criteria also considered.

    Args:
        n_events: Number of positive-class events.
        n_features: Number of predictor features used.
        n_total: Total sample size.

    Returns:
        Dict with EPV, adequacy flags, and recommendations.
    """
    epv = float(n_events) / max(n_features, 1)
    if epv >= 20:
        adequacy = "adequate"
    elif epv >= 10:
        adequacy = "marginal"
    else:
        adequacy = "insufficient"
    return {
        "n_events": int(n_events),
        "n_non_events": int(n_total - n_events),
        "n_features": int(n_features),
        "n_total": int(n_total),
        "events_per_variable": round(epv, 2),
        "adequacy": adequacy,
        "threshold_minimum": 10,
        "threshold_recommended": 20,
    }


def _multicollinearity_check(
    X: "pd.DataFrame",
    max_features: int = 50,
) -> Dict[str, Any]:
    """Compute Variance Inflation Factors for feature multicollinearity.

    PROBAST domain 3 signalling question: collinearity among predictors.

    Args:
        X: Feature DataFrame (imputed, no NaNs).
        max_features: Skip VIF if more features than this (too slow).

    Returns:
        Dict with per-feature VIF and flags for high collinearity.
    """
    cols = list(X.columns)
    if len(cols) > max_features or len(cols) < 2:
        return {"skipped": True, "reason": f"n_features={len(cols)}", "vif": []}
    from numpy.linalg import LinAlgError
    try:
        X_arr = X.values.astype(float)
        if np.isnan(X_arr).any():
            return {"skipped": True, "reason": "contains_nan", "vif": []}
        X_mean = X_arr - X_arr.mean(axis=0)
        xtx = X_mean.T @ X_mean
        try:
            xtx_inv = np.linalg.inv(xtx)
        except LinAlgError:
            xtx_inv = np.linalg.pinv(xtx)
        vifs = [round(float(xtx_inv[i, i] * xtx[i, i]), 2) for i in range(len(cols))]
    except Exception as exc:
        print(f"[WARN] VIF computation failed: {exc}", file=sys.stderr)
        return {"skipped": True, "reason": "computation_error", "vif": []}
    vif_records = [{"feature": str(c), "vif": v} for c, v in zip(cols, vifs)]
    high_vif = [r for r in vif_records if r["vif"] > 10.0]
    return {
        "skipped": False,
        "vif": vif_records,
        "high_vif_count": len(high_vif),
        "high_vif_features": [r["feature"] for r in high_vif],
        "max_vif": round(max(vifs) if vifs else 0.0, 2),
    }


def _permutation_importance_report(
    estimator: Any,
    X_test: "pd.DataFrame",
    y_test: "np.ndarray",
    scoring: str = "average_precision",
    n_repeats: int = 10,
    seed: int = 42,
    top_k: int = 20,
) -> Dict[str, Any]:
    """Compute permutation feature importance on the test set.

    Complements SHAP with a model-agnostic importance measure.

    Args:
        estimator: Fitted estimator.
        X_test: Test feature DataFrame.
        y_test: Test labels.
        scoring: Scoring metric.
        n_repeats: Number of permutation repeats.
        seed: Random seed.
        top_k: Number of top features to report.

    Returns:
        Dict with feature importance rankings.
    """
    from sklearn.inspection import permutation_importance as _perm_imp
    try:
        result = _perm_imp(
            estimator, X_test, y_test,
            scoring=scoring, n_repeats=n_repeats,
            random_state=seed, n_jobs=-1,
        )
        importances = result.importances_mean
        order = np.argsort(importances)[::-1]
        cols = list(X_test.columns)
        records = []
        for idx in order[:top_k]:
            records.append({
                "feature": str(cols[idx]),
                "importance_mean": round(float(importances[idx]), 6),
                "importance_std": round(float(result.importances_std[idx]), 6),
            })
        return {"scoring": scoring, "n_repeats": n_repeats, "top_features": records}
    except Exception as exc:
        return {"scoring": scoring, "error": str(exc), "top_features": []}


def _net_reclassification_improvement(
    y_true: "np.ndarray",
    proba_new: "np.ndarray",
    proba_ref: "np.ndarray",
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """Compute Net Reclassification Improvement (NRI) vs a reference model.

    Pencina et al. (2008) Statistics in Medicine.
    Category-free (continuous) NRI is also computed.

    Args:
        y_true: Binary ground truth labels.
        proba_new: Predicted probabilities from the new model.
        proba_ref: Predicted probabilities from the reference model.
        threshold: Risk threshold for category-based NRI.

    Returns:
        Dict with NRI_events, NRI_nonevents, NRI_total, and continuous NRI.
    """
    events = y_true == 1
    nonevents = y_true == 0
    # Category-based NRI
    cat_new = (proba_new >= threshold).astype(int)
    cat_ref = (proba_ref >= threshold).astype(int)
    up_events = int(np.sum((cat_new > cat_ref) & events))
    down_events = int(np.sum((cat_new < cat_ref) & events))
    up_nonevents = int(np.sum((cat_new > cat_ref) & nonevents))
    down_nonevents = int(np.sum((cat_new < cat_ref) & nonevents))
    n_events = max(int(np.sum(events)), 1)
    n_nonevents = max(int(np.sum(nonevents)), 1)
    nri_events = (up_events - down_events) / n_events
    nri_nonevents = (down_nonevents - up_nonevents) / n_nonevents
    nri_total = nri_events + nri_nonevents
    # Continuous NRI (category-free)
    diff = proba_new - proba_ref
    cnri_events = float(np.mean(diff[events])) if np.sum(events) > 0 else 0.0
    cnri_nonevents = float(-np.mean(diff[nonevents])) if np.sum(nonevents) > 0 else 0.0
    cnri_total = cnri_events + cnri_nonevents
    return {
        "threshold": float(threshold),
        "nri_events": round(float(nri_events), 4),
        "nri_nonevents": round(float(nri_nonevents), 4),
        "nri_total": round(float(nri_total), 4),
        "continuous_nri_events": round(float(cnri_events), 4),
        "continuous_nri_nonevents": round(float(cnri_nonevents), 4),
        "continuous_nri_total": round(float(cnri_total), 4),
        "reclassification_table": {
            "events_up": up_events,
            "events_down": down_events,
            "nonevents_up": up_nonevents,
            "nonevents_down": down_nonevents,
        },
    }


def _integrated_discrimination_improvement(
    y_true: "np.ndarray",
    proba_new: "np.ndarray",
    proba_ref: "np.ndarray",
) -> Dict[str, Any]:
    """Compute Integrated Discrimination Improvement (IDI).

    Pencina et al. (2008) Statistics in Medicine.
    IDI = (IS_new - IS_ref) where IS = mean(p|events) - mean(p|non-events).
    IDI measures the improvement in discrimination slope between two models.

    Required by top-tier journals (JAMA, Lancet) when comparing prediction models.

    Args:
        y_true: Binary ground truth labels.
        proba_new: Predicted probabilities from the new (candidate) model.
        proba_ref: Predicted probabilities from the reference (baseline) model.

    Returns:
        Dict with IDI, IS_new, IS_ref, and relative IDI.
    """
    events = y_true == 1
    nonevents = y_true == 0
    n_events = int(np.sum(events))
    n_nonevents = int(np.sum(nonevents))

    if n_events < 1 or n_nonevents < 1:
        return {
            "idi": None,
            "is_new": None,
            "is_ref": None,
            "relative_idi": None,
            "note": "insufficient_events_or_nonevents",
        }

    # Discrimination slope (integrated sensitivity - integrated 1-specificity)
    is_new = float(np.mean(proba_new[events]) - np.mean(proba_new[nonevents]))
    is_ref = float(np.mean(proba_ref[events]) - np.mean(proba_ref[nonevents]))
    idi = is_new - is_ref
    relative_idi = idi / is_ref if is_ref != 0 else None

    return {
        "idi": round(float(idi), 6),
        "discrimination_slope_new": round(is_new, 6),
        "discrimination_slope_ref": round(is_ref, 6),
        "relative_idi": round(float(relative_idi), 4) if relative_idi is not None else None,
        "interpretation": (
            "new_model_better" if idi > 0
            else "reference_model_better" if idi < 0
            else "no_difference"
        ),
    }


def _delong_test(
    y_true: "np.ndarray",
    proba_a: "np.ndarray",
    proba_b: "np.ndarray",
) -> Dict[str, Any]:
    """DeLong test for comparing two ROC-AUC values.

    DeLong et al. (1988) — standard for AUC comparison in clinical ML.
    Nature Medicine / Lancet require this when comparing models.

    Args:
        y_true: Binary ground truth labels.
        proba_a: Predicted probabilities from model A (new).
        proba_b: Predicted probabilities from model B (reference).

    Returns:
        Dict with auc_a, auc_b, z_statistic, p_value.
    """
    from scipy import stats as _stats
    pos = np.where(y_true == 1)[0]
    neg = np.where(y_true == 0)[0]
    m = len(pos)
    k = len(neg)
    if m < 2 or k < 2:
        return {"auc_a": None, "auc_b": None, "z_statistic": None, "p_value": None}
    # Structural components (Mann-Whitney U-statistic based, vectorized)
    def _placements(proba: "np.ndarray") -> "np.ndarray":
        scores_pos = proba[pos]
        scores_neg = proba[neg]
        # shape: (m, k) — broadcast comparison
        gt = (scores_pos[:, None] > scores_neg[None, :]).astype(float)
        eq = (scores_pos[:, None] == scores_neg[None, :]).astype(float)
        return np.mean(gt + 0.5 * eq, axis=1)
    def _placements_neg(proba: "np.ndarray") -> "np.ndarray":
        scores_pos = proba[pos]
        scores_neg = proba[neg]
        # shape: (k, m) — broadcast comparison
        lt = (scores_neg[:, None] < scores_pos[None, :]).astype(float)
        eq = (scores_neg[:, None] == scores_pos[None, :]).astype(float)
        return np.mean(lt + 0.5 * eq, axis=1)
    v10_a = _placements(proba_a)
    v10_b = _placements(proba_b)
    v01_a = _placements_neg(proba_a)
    v01_b = _placements_neg(proba_b)
    auc_a = float(np.mean(v10_a))
    auc_b = float(np.mean(v10_b))
    # Covariance matrix of AUC difference
    s10 = np.cov(np.column_stack([v10_a, v10_b]), rowvar=False, ddof=1)
    s01 = np.cov(np.column_stack([v01_a, v01_b]), rowvar=False, ddof=1)
    s = s10 / m + s01 / k
    diff = auc_a - auc_b
    var_diff = float(s[0, 0] + s[1, 1] - 2 * s[0, 1])
    if var_diff <= 0:
        return {"auc_a": round(auc_a, 6), "auc_b": round(auc_b, 6),
                "auc_diff": round(float(diff), 6),
                "z_statistic": None, "p_value": 1.0, "significant_at_005": False}
    z = diff / np.sqrt(var_diff)
    p = float(2 * _stats.norm.sf(abs(z)))
    return {
        "auc_a": round(auc_a, 6),
        "auc_b": round(auc_b, 6),
        "auc_diff": round(float(diff), 6),
        "z_statistic": round(float(z), 4),
        "p_value": round(p, 6),
        "significant_at_005": bool(p < 0.05),
    }


def _mcnemar_test(
    y_true: "np.ndarray",
    pred_a: "np.ndarray",
    pred_b: "np.ndarray",
) -> Dict[str, Any]:
    """McNemar test for comparing two classifiers' disagreements.

    Tests whether the two classifiers make the same types of errors.

    Args:
        y_true: Binary ground truth labels.
        pred_a: Binary predictions from model A (new).
        pred_b: Binary predictions from model B (reference).

    Returns:
        Dict with contingency table, chi2 statistic, p_value.
    """
    from scipy import stats as _stats
    correct_a = (pred_a == y_true).astype(int)
    correct_b = (pred_b == y_true).astype(int)
    # b = A correct, B wrong; c = A wrong, B correct
    b = int(np.sum((correct_a == 1) & (correct_b == 0)))
    c = int(np.sum((correct_a == 0) & (correct_b == 1)))
    if b + c == 0:
        return {"b": b, "c": c, "chi2": 0.0, "p_value": 1.0, "significant_at_005": False}
    # Edwards correction
    chi2 = float((abs(b - c) - 1) ** 2 / (b + c))
    p = float(_stats.chi2.sf(chi2, df=1))
    return {
        "b_a_correct_b_wrong": b,
        "c_a_wrong_b_correct": c,
        "chi2": round(chi2, 4),
        "p_value": round(p, 6),
        "significant_at_005": bool(p < 0.05),
    }


def _prediction_uncertainty(
    proba: "np.ndarray",
) -> Dict[str, Any]:
    """Compute prediction-level uncertainty statistics.

    Reports entropy distribution and identifies high-uncertainty predictions.
    ICML/NeurIPS expect uncertainty quantification in clinical ML.

    Args:
        proba: Predicted probabilities.

    Returns:
        Dict with entropy statistics and high-uncertainty fraction.
    """
    eps = 1e-12
    p = np.clip(proba, eps, 1.0 - eps)
    entropy = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
    return {
        "entropy_mean": round(float(np.mean(entropy)), 4),
        "entropy_std": round(float(np.std(entropy)), 4),
        "entropy_median": round(float(np.median(entropy)), 4),
        "entropy_max": round(float(np.max(entropy)), 4),
        "high_uncertainty_fraction": round(float(np.mean(entropy > 0.9)), 4),
        "low_confidence_fraction": round(float(np.mean((proba > 0.3) & (proba < 0.7))), 4),
    }


def _subgroup_performance(
    y_true: "np.ndarray",
    proba: "np.ndarray",
    threshold: float,
    beta: float,
    feature_df: "pd.DataFrame",
    max_subgroups: int = 8,
    max_cardinality: int = 20,
) -> Dict[str, Any]:
    """Compute performance metrics across subgroups for fairness assessment.

    NeurIPS/ICML fairness checklist: report performance disparities.
    Nature Medicine: subgroup analysis required for clinical applicability.

    Args:
        y_true: Binary ground truth labels.
        proba: Predicted probabilities.
        threshold: Decision threshold.
        beta: Beta for F-beta score.
        feature_df: Feature DataFrame to identify subgroup columns.
        max_subgroups: Max number of features to analyze.
        max_cardinality: Max distinct values for a column to qualify as
            subgroup (default 20, covers race/ethnicity categories).

    Returns:
        Dict with per-feature subgroup performance breakdown.
    """
    results: Dict[str, Any] = {"features_analyzed": 0, "subgroups": {}}
    # Identify candidate subgroup columns (binary or low-cardinality categorical).
    # Upper bound raised from 5→20 so demographic variables like
    # race_ethnicity (6-7 categories) are not silently excluded.
    candidates = []
    for col in feature_df.columns:
        nunique = feature_df[col].nunique()
        if 2 <= nunique <= max_cardinality:
            candidates.append((col, nunique))
    candidates.sort(key=lambda x: x[1])
    candidates = candidates[:max_subgroups]
    results["features_analyzed"] = len(candidates)
    for col, _ in candidates:
        groups = feature_df[col].dropna().unique()
        group_results = []
        for g in sorted(groups, key=str):
            mask = (feature_df[col] == g).values
            if np.sum(mask) < 10 or np.sum(y_true[mask]) < 2:
                continue
            y_sub = y_true[mask]
            p_sub = proba[mask]
            pred_sub = (p_sub >= threshold).astype(int)
            tp = int(np.sum((pred_sub == 1) & (y_sub == 1)))
            fp = int(np.sum((pred_sub == 1) & (y_sub == 0)))
            fn = int(np.sum((pred_sub == 0) & (y_sub == 1)))
            sens = tp / max(tp + fn, 1)
            ppv = tp / max(tp + fp, 1)
            try:
                auc = float(roc_auc_score(y_sub, p_sub))
            except Exception:  # noqa: BLE001 — subgroup may lack both classes
                auc = None
            if auc is not None and not np.isfinite(auc):
                auc = None
            try:
                pr_auc = float(average_precision_score(y_sub, p_sub))
            except Exception:  # noqa: BLE001 — subgroup may lack both classes
                pr_auc = None
            if pr_auc is not None and not np.isfinite(pr_auc):
                pr_auc = None
            group_results.append({
                "group_value": str(g),
                "n": int(np.sum(mask)),
                "n_positive": int(np.sum(y_sub)),
                "prevalence": round(float(np.mean(y_sub)), 4),
                "sensitivity": round(float(sens), 4),
                "ppv": round(float(ppv), 4),
                "roc_auc": round(auc, 4) if auc is not None else None,
                "pr_auc": round(pr_auc, 4) if pr_auc is not None else None,
            })
        if len(group_results) >= 2:
            aucs = [g["roc_auc"] for g in group_results if g["roc_auc"] is not None]
            sens_vals = [g["sensitivity"] for g in group_results]
            results["subgroups"][str(col)] = {
                "groups": group_results,
                "auc_range": round(max(aucs) - min(aucs), 4) if len(aucs) >= 2 else None,
                "sensitivity_range": round(max(sens_vals) - min(sens_vals), 4),
                "equalized_odds_gap": round(max(sens_vals) - min(sens_vals), 4),
            }
    # Disparate impact ratio (overall)
    if results["subgroups"]:
        first_feature = list(results["subgroups"].values())[0]
        groups = first_feature["groups"]
        positive_rates = []
        for g in groups:
            positive_rates.append(g.get("sensitivity", 0))
        if positive_rates and max(positive_rates) > 0:
            results["disparate_impact_ratio"] = round(min(positive_rates) / max(positive_rates), 4)
        else:
            results["disparate_impact_ratio"] = None
    return results


def _inference_benchmark(
    estimator: Any,
    X_sample: "pd.DataFrame",
    n_repeats: int = 5,
) -> Dict[str, Any]:
    """Benchmark inference latency and report model size.

    NeurIPS/ICML paper checklist requires computational cost reporting.

    Args:
        estimator: Fitted estimator.
        X_sample: Sample of test data for timing.
        n_repeats: Number of timing repeats.

    Returns:
        Dict with latency_ms_per_sample, total_inference_ms, model_param_count.
    """
    import time
    sample = X_sample.head(min(100, len(X_sample)))
    # Warm-up run to exclude JIT/cache cold-start
    try:
        if hasattr(estimator, "predict_proba"):
            estimator.predict_proba(sample)
        else:
            estimator.predict(sample)
    except Exception:  # noqa: BLE001 — warm-up; failure is benign
        pass
    times = []
    for _ in range(n_repeats):
        t0 = time.perf_counter()
        try:
            if hasattr(estimator, "predict_proba"):
                estimator.predict_proba(sample)
            else:
                estimator.predict(sample)
        except Exception as exc:
            print(f"[WARN] inference_latency: predict failed: {exc}", file=sys.stderr)
            break
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    if not times:
        return {"latency_ms_per_sample": None, "total_inference_ms": None, "n_samples": 0}
    avg_total = float(np.mean(times))
    n = len(sample)
    # Model parameter count estimation
    param_count = None
    try:
        if hasattr(estimator, "named_steps"):
            clf = estimator.named_steps.get("clf", estimator)
        else:
            clf = estimator
        if hasattr(clf, "coef_"):
            param_count = int(np.prod(clf.coef_.shape)) + (int(clf.intercept_.shape[0]) if hasattr(clf, "intercept_") else 0)
        elif hasattr(clf, "n_estimators") and hasattr(clf, "estimators_"):
            param_count = sum(t.tree_.node_count for t in (clf.estimators_ if not hasattr(clf.estimators_[0], '__len__') else [e for sub in clf.estimators_ for e in sub]))
        elif hasattr(clf, "get_booster"):
            param_count = len(clf.get_booster().get_dump())
    except Exception:  # noqa: BLE001 — param count is informational
        pass
    return {
        "inference_latency_ms_per_sample": round(avg_total / max(n, 1), 4),
        "total_inference_ms": round(avg_total, 2),
        "n_samples_timed": int(n),
        "n_repeats": int(n_repeats),
        "model_param_count": param_count,
    }


def _environment_versions() -> Dict[str, str]:
    """Capture key package versions for reproducibility.

    NeurIPS reproducibility checklist requires environment specification.

    Returns:
        Dict mapping package name to version string.
    """
    versions: Dict[str, str] = {}
    for pkg in ("numpy", "pandas", "sklearn", "scipy", "xgboost", "lightgbm", "shap", "joblib"):
        try:
            mod = __import__(pkg)
            versions[pkg] = str(getattr(mod, "__version__", "unknown"))
        except ImportError:
            versions[pkg] = "not_installed"
    versions["python"] = sys.version.split()[0]
    import platform as _plat
    versions["platform"] = _plat.platform()
    return versions


def _feature_ablation_study(
    estimator: Any,
    X_test: "pd.DataFrame",
    y_test: "np.ndarray",
    proba_full: "np.ndarray",
    threshold: float,
    beta: float,
    top_k: int = 10,
    seed: int = 42,
) -> Dict[str, Any]:
    """Permutation-based feature importance (often called "ablation" in ML).

    Measures performance drop when each feature is individually permuted
    (Breiman 2001). This is NOT true ablation (retraining without the feature)
    but is standard practice for fitted model diagnostics.

    Args:
        estimator: Fitted estimator.
        X_test: Test feature DataFrame.
        y_test: Test labels.
        proba_full: Full-model predictions on test set.
        threshold: Decision threshold.
        beta: Beta for F-beta.
        top_k: Number of top impactful features to report.
        seed: Random seed for reproducible permutations.

    Returns:
        Dict with feature-level ablation results sorted by impact.
    """
    from sklearn.metrics import average_precision_score as _ap
    full_pr_auc = float(_ap(y_test, proba_full))
    rng = np.random.default_rng(int(seed))
    results = []
    cols = list(X_test.columns)
    for col in cols:
        X_ablated = X_test.copy()
        X_ablated[col] = rng.permutation(X_ablated[col].values)
        try:
            if hasattr(estimator, "predict_proba"):
                p_abl = estimator.predict_proba(X_ablated)
                if p_abl.ndim == 2 and p_abl.shape[1] >= 2:
                    p_abl = p_abl[:, 1]
                else:
                    p_abl = p_abl.ravel()
            else:
                p_abl = estimator.predict(X_ablated).ravel()
            abl_pr_auc = float(_ap(y_test, p_abl))
        except Exception as exc:
            print(f"[WARN] feature_ablation failed for '{col}': {exc}", file=sys.stderr)
            abl_pr_auc = full_pr_auc
        drop = full_pr_auc - abl_pr_auc
        results.append({
            "feature": str(col),
            "pr_auc_full": round(full_pr_auc, 6),
            "pr_auc_ablated": round(abl_pr_auc, 6),
            "pr_auc_drop": round(float(drop), 6),
        })
    results.sort(key=lambda r: r["pr_auc_drop"], reverse=True)
    return {
        "method": "leave_one_feature_out",
        "metric": "pr_auc",
        "full_model_pr_auc": round(full_pr_auc, 6),
        "feature_count": len(cols),
        "top_features": results[:top_k],
    }


def _error_analysis(
    y_true: "np.ndarray",
    proba: "np.ndarray",
    threshold: float,
    feature_df: "pd.DataFrame",
    top_k: int = 5,
) -> Dict[str, Any]:
    """Analyze false positives and false negatives for error patterns.

    Nature Medicine requires understanding of model failure modes.

    Args:
        y_true: Binary ground truth labels.
        proba: Predicted probabilities.
        threshold: Decision threshold.
        feature_df: Feature DataFrame for characterization.
        top_k: Number of features to report for error characterization.

    Returns:
        Dict with FP/FN counts, confidence distributions, and feature diffs.
    """
    pred = (proba >= threshold).astype(int)
    tp_mask = (pred == 1) & (y_true == 1)
    fp_mask = (pred == 1) & (y_true == 0)
    tn_mask = (pred == 0) & (y_true == 0)
    fn_mask = (pred == 0) & (y_true == 1)

    def _confidence_stats(mask: "np.ndarray") -> Optional[Dict[str, float]]:
        p_sub = proba[mask]
        if len(p_sub) == 0:
            return None
        return {
            "count": int(len(p_sub)),
            "prob_mean": round(float(np.mean(p_sub)), 4),
            "prob_std": round(float(np.std(p_sub)), 4),
            "prob_median": round(float(np.median(p_sub)), 4),
        }

    # Feature means comparison: FP vs TN, FN vs TP
    feature_diffs: Dict[str, Any] = {}
    numeric_cols = []
    for col in feature_df.columns:
        try:
            vals = pd.to_numeric(feature_df[col], errors="coerce")
            if vals.notna().sum() > 10:
                numeric_cols.append(col)
        except Exception:  # noqa: BLE001 — column type detection; non-numeric skipped
            pass
    for col in numeric_cols[:top_k]:
        vals = pd.to_numeric(feature_df[col], errors="coerce").values.astype(float)
        fp_vals = vals[fp_mask]
        tn_vals = vals[tn_mask]
        fn_vals = vals[fn_mask]
        tp_vals = vals[tp_mask]
        entry: Dict[str, Any] = {}
        if len(fp_vals) > 0 and len(tn_vals) > 0:
            fp_m = float(np.nanmean(fp_vals))
            tn_m = float(np.nanmean(tn_vals))
            if np.isfinite(fp_m) and np.isfinite(tn_m):
                entry["fp_mean"] = round(fp_m, 4)
                entry["tn_mean"] = round(tn_m, 4)
                entry["fp_tn_diff"] = round(fp_m - tn_m, 4)
        if len(fn_vals) > 0 and len(tp_vals) > 0:
            fn_m = float(np.nanmean(fn_vals))
            tp_m = float(np.nanmean(tp_vals))
            if np.isfinite(fn_m) and np.isfinite(tp_m):
                entry["fn_mean"] = round(fn_m, 4)
                entry["tp_mean"] = round(tp_m, 4)
                entry["fn_tp_diff"] = round(fn_m - tp_m, 4)
        if entry:
            feature_diffs[str(col)] = entry

    return {
        "true_positives": _confidence_stats(tp_mask),
        "false_positives": _confidence_stats(fp_mask),
        "true_negatives": _confidence_stats(tn_mask),
        "false_negatives": _confidence_stats(fn_mask),
        "feature_characterization": feature_diffs,
    }


def _compute_overfit_risk(
    train_metrics: Dict[str, Any],
    valid_metrics: Dict[str, Any],
    test_metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Compute overfitting risk level from train/valid (and optionally test) metric gaps.

    Risk is determined **solely from train-valid gap** to avoid using test
    data for model selection decisions.  When *test_metrics* is provided the
    train-test gap is recorded in the ``gaps`` dict for post-hoc reporting
    but does **not** influence the returned risk level.

    Args:
        train_metrics: Metric dict from training split.
        valid_metrics: Metric dict from validation split.
        test_metrics: Metric dict from test split (optional, for reporting).

    Returns:
        Tuple of (risk_level, gaps_dict, warning_messages).
    """
    gaps: Dict[str, Any] = {}
    warnings_list: List[str] = []
    for mk in ("pr_auc", "roc_auc", "brier"):
        tr = float(train_metrics.get(mk, 0.0))
        va = float(valid_metrics.get(mk, 0.0))
        tv_gap = tr - va
        entry: Dict[str, Any] = {
            "train": tr, "valid": va,
            "train_valid_gap": round(tv_gap, 6),
        }
        if test_metrics is not None:
            te = float(test_metrics.get(mk, 0.0))
            tt_gap = tr - te
            entry["test"] = te
            entry["train_test_gap"] = round(tt_gap, 6)
            if mk != "brier" and tt_gap > 0.15:
                warnings_list.append(f"{mk} gap (train-test): {tt_gap:.4f} — likely overfitting or distribution shift.")
        gaps[mk] = entry
        if mk == "brier":
            if tv_gap < -0.05:
                warnings_list.append(f"Brier score gap (train-valid): {tv_gap:.4f} — possible overfitting.")
        else:
            if tv_gap > 0.10:
                warnings_list.append(f"{mk} gap (train-valid): {tv_gap:.4f} — possible overfitting.")
    # Risk level is based on train-valid gap ONLY (no test leakage).
    max_tv_auc_gap = max(
        (float(gaps.get(k, {}).get("train_valid_gap", 0.0)) for k in ("pr_auc", "roc_auc")),
        default=0.0,
    )
    brier_tv_gap = float(gaps.get("brier", {}).get("train_valid_gap", 0.0))
    if max_tv_auc_gap > 0.20 or brier_tv_gap < -0.10:
        risk = "high"
    elif max_tv_auc_gap > 0.10 or brier_tv_gap < -0.05:
        risk = "medium"
    else:
        risk = "low"
    return risk, gaps, warnings_list


def _full_candidate_eval(
    model_id: str,
    estimator_map: Dict[str, Any],
    X_train: "pd.DataFrame",
    y_train: "np.ndarray",
    X_valid: "pd.DataFrame",
    y_valid: "np.ndarray",
    threshold_selection_split: str,
    calibration_fit_split: str,
    calibration_method: str,
    beta: float,
    sensitivity_floor: float,
    npv_floor: float,
    specificity_floor: float,
    ppv_floor: float,
    cv_splits: int,
    random_seed: int,
    imbalance_strategy: str,
) -> Dict[str, Any]:
    """Train-calibrate-threshold-evaluate pipeline for one candidate (no test data).

    Used by the overfitting callback to evaluate alternative candidates using
    **only train/valid data** to avoid test-data leakage in model selection.

    Args:
        model_id: Identifier of the candidate model.
        estimator_map: Map from model_id to sklearn estimator.
        X_train, y_train: Training features and labels.
        X_valid, y_valid: Validation features and labels.
        threshold_selection_split: Split used for threshold ('valid' or 'cv_inner').
        calibration_fit_split: Split used for calibration ('valid' or 'cv_inner').
        calibration_method: Calibration method name.
        beta: Beta for F-beta threshold scoring.
        sensitivity_floor, npv_floor, specificity_floor, ppv_floor: Clinical floors.
        cv_splits: Number of CV folds.
        random_seed: Random seed.
        imbalance_strategy: Imbalance handling strategy.

    Returns:
        Dict with model_id, risk (from train-valid gap only), gaps, warnings,
        threshold, estimator, calibrator, and train/valid metrics.
    """
    est = clone(estimator_map[model_id])
    est, _ = fit_estimator_with_imbalance(
        estimator=est,
        X_train=X_train,
        y_train=y_train,
        strategy=imbalance_strategy,
        seed=int(random_seed),
    )
    # Threshold data
    if threshold_selection_split == "valid":
        t_y, t_raw = y_valid, predict_proba_1(est, X_valid)
    else:
        t_y = y_train
        t_raw = cv_oof_proba(est, X_train, y_train, cv_splits, random_seed, imbalance_strategy=imbalance_strategy)
    # Calibration data
    if calibration_fit_split == "valid":
        c_y, c_raw = y_valid, predict_proba_1(est, X_valid)
    else:
        c_y = y_train
        c_raw = cv_oof_proba(est, X_train, y_train, cv_splits, random_seed, imbalance_strategy=imbalance_strategy)
    cal = fit_probability_calibrator(c_y, c_raw, calibration_method, int(random_seed))
    t_proba = apply_probability_calibrator(cal, t_raw)
    # Guard split
    _has_valid_eval = len(y_valid) > 0 if isinstance(y_valid, np.ndarray) else False
    if threshold_selection_split == "cv_inner" and _has_valid_eval:
        g_y = y_valid
        g_proba = apply_probability_calibrator(cal, predict_proba_1(est, X_valid))
    else:
        g_y = y_train
        g_raw = cv_oof_proba(est, X_train, y_train, cv_splits, random_seed, imbalance_strategy=imbalance_strategy)
        g_proba = apply_probability_calibrator(cal, g_raw)
    info = choose_threshold(
        t_y, t_proba, beta, sensitivity_floor, npv_floor,
        specificity_floor, ppv_floor, g_y, g_proba,
    )
    thresh = float(info["selected_threshold"])
    # Metrics on train + valid only (no test — avoids leakage)
    tr_p = apply_probability_calibrator(cal, predict_proba_1(est, X_train))
    tr_m, tr_cm = metric_panel(y_train, tr_p, thresh, beta=beta)
    if _has_valid_eval:
        va_p = apply_probability_calibrator(cal, predict_proba_1(est, X_valid))
        va_m, va_cm = metric_panel(y_valid, va_p, thresh, beta=beta)
    else:
        va_p = tr_p  # fallback: use train metrics for risk assessment
        va_m, va_cm = tr_m, tr_cm
    risk, gaps, warns = _compute_overfit_risk(tr_m, va_m)
    max_gap = max(
        float(gaps.get(k, {}).get("train_valid_gap", 0.0))
        for k in ("pr_auc", "roc_auc")
    )
    return {
        "model_id": model_id,
        "risk": risk,
        "max_gap": max_gap,
        "gaps": gaps,
        "warnings": warns,
        "threshold": thresh,
        "threshold_info": info,
        "valid_pr_auc": float(va_m.get("pr_auc", 0.0)),
        "estimator": est,
        "calibrator": cal,
        "train_metrics": tr_m, "train_cm": tr_cm,
        "valid_metrics": va_m, "valid_cm": va_cm,
        "train_proba": tr_p, "valid_proba": va_p,
    }


def _phase0_preflight_and_config(args: argparse.Namespace) -> Dict[str, Any]:
    """Phase 0: Preflight gate verification and configuration loading.

    Validates CLI args, loads policy files, resolves thresholds and
    calibration/selection split settings.

    Returns dict with all config values needed by subsequent phases.
    """
    # ── Pre-training gate verification (fail-closed) ──────────────────────
    if not getattr(args, "skip_preflight_check", False):
        _evidence_dir = Path(args.train).expanduser().resolve().parent.parent / "evidence"
        _preflight_gates = {
            "leakage_report.json": ("leakage_gate", "S01: patient-level split isolation"),
        }
        if _evidence_dir.is_dir() or (_evidence_dir.parent / "configs").is_dir():
            for _report_name, (_gate_name, _rule) in _preflight_gates.items():
                _report_path = _evidence_dir / _report_name
                if not _report_path.is_file():
                    print(
                        f"[PREFLIGHT] {_gate_name} report not found: {_report_path}\n"
                        f"  Rule {_rule} requires this gate to pass before training.\n"
                        f"  Run: python3 scripts/gates/leakage_gate.py --train <train> --test <test> "
                        f"--id-cols <ID> --target-col y --report {_report_path} --strict",
                        file=sys.stderr,
                    )
                    raise SystemExit(f"preflight_failed: {_gate_name} report missing. Run the gate first.")
                try:
                    with _report_path.open("r", encoding="utf-8") as _fh:
                        _rpt = json.load(_fh)
                    _rpt_status = str(_rpt.get("status", "")).strip().lower()
                    _rpt_gate = str(_rpt.get("gate_name", "")).strip()
                    _rpt_envelope = str(_rpt.get("envelope_version", "")).strip()
                    if _rpt_status != "pass":
                        raise SystemExit(
                            f"preflight_failed: {_gate_name} status={_rpt_status}. "
                            f"Fix the issues and re-run the gate before training."
                        )
                    if not _rpt_gate or not _rpt_envelope:
                        raise SystemExit(
                            f"preflight_failed: {_report_name} is missing gate_name or envelope_version. "
                            f"This may be a hand-crafted file. Re-run the gate to produce a valid report."
                        )
                except json.JSONDecodeError as _exc:
                    raise SystemExit(
                        f"preflight_failed: {_report_name} is not valid JSON: {_exc}"
                    )

    # ── Auto-exclude codebook-flagged leakage columns ─────────────────────
    # If cohort_definition_gate produced a report with codebook_auto_exclude_columns,
    # merge them into --definition-cols so they are forcibly excluded from features.
    _evidence_dir_for_codebook = Path(args.train).expanduser().resolve().parent.parent / "evidence"
    _cohort_report_path = _evidence_dir_for_codebook / "cohort_definition_report.json"
    if _cohort_report_path.is_file():
        try:
            with _cohort_report_path.open("r", encoding="utf-8") as _fh:
                _cohort_rpt = json.load(_fh)
            _auto_exclude = (_cohort_rpt.get("study_design", {})
                             .get("codebook_auto_exclude_columns", []))
            if _auto_exclude:
                existing = set(
                    c.strip() for c in getattr(args, "definition_cols", "").split(",") if c.strip()
                )
                new_cols = sorted(set(_auto_exclude) - existing)
                if new_cols:
                    merged = ",".join(sorted(existing | set(new_cols)))
                    args.definition_cols = merged
                    print(
                        f"[SAFE] codebook_auto_exclude: {len(new_cols)} column(s) flagged "
                        f"by cohort codebook validation added to definition_cols: "
                        f"{', '.join(new_cols)}",
                        file=sys.stderr,
                    )
        except (json.JSONDecodeError, KeyError, TypeError, FileNotFoundError, OSError):
            pass  # Non-fatal: codebook exclusion is best-effort

    # ── Argument validation ───────────────────────────────────────────────
    if args.cv_splits < 3:
        raise SystemExit("--cv-splits must be >= 3.")
    if args.beta <= 0:
        raise SystemExit("--beta must be > 0.")
    if args.primary_metric.strip().lower() != "pr_auc":
        raise SystemExit("--primary-metric must be pr_auc for this strict workflow.")
    if bool(args.external_cohort_spec) != bool(args.external_validation_report_out):
        raise SystemExit("--external-cohort-spec and --external-validation-report-out must be provided together.")
    if args.external_cohort_spec and not args.prediction_trace_out:
        raise SystemExit("--prediction-trace-out is required when --external-cohort-spec is provided.")
    if args.feature_engineering_report_out and not args.feature_group_spec:
        raise SystemExit("--feature-group-spec is required when --feature-engineering-report-out is used.")

    # ── Policy & config loading ───────────────────────────────────────────
    policy = load_policy(args.performance_policy)
    missingness_policy = load_missingness_policy(args.missingness_policy)
    external_spec = load_external_cohort_spec(args.external_cohort_spec)
    feature_group_spec = load_feature_group_spec(args.feature_group_spec)
    fe_mode_cfg = mode_config(args.feature_engineering_mode)
    threshold_policy = policy.get("threshold_policy") if isinstance(policy, dict) else None
    clinical_floors = policy.get("clinical_floors") if isinstance(policy, dict) else None
    if isinstance(threshold_policy, dict) and isinstance(threshold_policy.get("clinical_floors"), dict):
        clinical_floors = threshold_policy.get("clinical_floors")

    beta = float(policy.get("beta", args.beta)) if isinstance(policy.get("beta"), (int, float)) else float(args.beta)
    sensitivity_floor = (
        float(clinical_floors.get("sensitivity_min"))
        if isinstance(clinical_floors, dict) and isinstance(clinical_floors.get("sensitivity_min"), (int, float))
        else float(args.sensitivity_floor)
    )
    npv_floor = (
        float(clinical_floors.get("npv_min"))
        if isinstance(clinical_floors, dict) and isinstance(clinical_floors.get("npv_min"), (int, float))
        else float(args.npv_floor)
    )
    specificity_floor = (
        float(clinical_floors.get("specificity_min"))
        if isinstance(clinical_floors, dict) and isinstance(clinical_floors.get("specificity_min"), (int, float))
        else float(args.specificity_floor)
    )
    ppv_floor = (
        float(clinical_floors.get("ppv_min"))
        if isinstance(clinical_floors, dict) and isinstance(clinical_floors.get("ppv_min"), (int, float))
        else float(args.ppv_floor)
    )
    calibration_method = str(policy.get("calibration_method", args.calibration_method)).strip().lower()
    if calibration_method not in {"sigmoid", "isotonic", "power", "beta", "none"}:
        calibration_method = str(args.calibration_method).strip().lower()
    if calibration_method not in {"sigmoid", "isotonic", "power", "beta", "none"}:
        calibration_method = "none"
    selection_data = str(args.selection_data).strip().lower()
    if selection_data not in {"valid", "cv_inner"}:
        raise SystemExit("--selection-data in this trainer must be valid/cv_inner.")
    threshold_selection_split = str(args.threshold_selection_split).strip().lower()
    if threshold_selection_split not in {"valid", "cv_inner"}:
        raise SystemExit("--threshold-selection-split in this trainer must be valid/cv_inner.")
    calibration_fit_split = threshold_selection_split
    if isinstance(threshold_policy, dict):
        token = str(threshold_policy.get("calibration_fit_split", calibration_fit_split)).strip().lower()
        if token in {"valid", "cv_inner"}:
            calibration_fit_split = token
    token_top = str(policy.get("calibration_fit_split", calibration_fit_split)).strip().lower()
    if token_top in {"valid", "cv_inner"}:
        calibration_fit_split = token_top

    return {
        "fast_diagnostic_mode": bool(args.fast_diagnostic_mode),
        "policy": policy,
        "missingness_policy": missingness_policy,
        "external_spec": external_spec,
        "feature_group_spec": feature_group_spec,
        "fe_mode_cfg": fe_mode_cfg,
        "threshold_policy": threshold_policy,
        "clinical_floors": clinical_floors,
        "beta": beta,
        "sensitivity_floor": sensitivity_floor,
        "npv_floor": npv_floor,
        "specificity_floor": specificity_floor,
        "ppv_floor": ppv_floor,
        "calibration_method": calibration_method,
        "selection_data": selection_data,
        "threshold_selection_split": threshold_selection_split,
        "calibration_fit_split": calibration_fit_split,
        "model_pool_config": parse_model_pool_config(policy, args),
    }


def _phase1_data_loading(ctx: Dict[str, Any]) -> None:
    """Phase 1: Load splits, resolve feature columns, apply group filtering.

    Reads from ctx: args, feature_group_spec, threshold_selection_split,
                    calibration_fit_split
    Writes to ctx:  train_df, valid_df, test_df, groups, forbidden_features,
                    stage0_features, ignore_cols, base_feature_cols
    May update:     threshold_selection_split, calibration_fit_split (if no valid split)
    """
    args = ctx["args"]
    feature_group_spec = ctx["feature_group_spec"]

    train_df = load_split(args.train)
    valid_df = load_split(args.valid) if args.valid and args.valid.strip() else pd.DataFrame()
    test_df = load_split(args.test) if args.test and args.test.strip() else pd.DataFrame()

    # Auto-select model selection mode based on available splits
    if len(valid_df) == 0:
        if str(args.selection_data).strip().lower() == "valid":
            print("  [INFO] No validation split provided. Switching to --selection-data=cv_inner.")
            args.selection_data = "cv_inner"
            ctx["selection_data"] = "cv_inner"
        if ctx["threshold_selection_split"] == "valid":
            print("  [INFO] No validation split provided. Switching threshold selection to cv_inner.")
            ctx["threshold_selection_split"] = "cv_inner"
        if ctx["calibration_fit_split"] == "valid":
            ctx["calibration_fit_split"] = "cv_inner"

    ignore_cols = parse_ignore_cols(args.ignore_cols, args.target_col, getattr(args, "definition_cols", ""))
    base_feature_cols = select_feature_columns(train_df, ignore_cols)
    groups, forbidden_features = normalize_feature_groups(feature_group_spec)
    grouped_features = sorted({feature for values in groups.values() for feature in values})
    if grouped_features:
        stage0_features = [f for f in base_feature_cols if f in grouped_features and f not in set(forbidden_features)]
    else:
        stage0_features = [f for f in base_feature_cols if f not in set(forbidden_features)]
    if not stage0_features:
        stage0_features = [f for f in base_feature_cols if f not in set(forbidden_features)]
    if not stage0_features:
        raise SystemExit("No usable features remain after feature-group and forbidden-feature filtering.")

    ctx.update({
        "train_df": train_df, "valid_df": valid_df, "test_df": test_df,
        "groups": groups, "forbidden_features": forbidden_features,
        "stage0_features": stage0_features, "ignore_cols": ignore_cols,
        "base_feature_cols": base_feature_cols,
    })


def _phase2_feature_engineering(ctx: Dict[str, Any]) -> None:
    """Phase 2: Missingness filter, stability selection, encoding, VIF, external cohorts.

    Reads from ctx: train_df, valid_df, test_df, stage0_features, groups,
                    fe_mode_cfg, external_spec, args
    Writes to ctx:  X_train, y_train, X_valid, y_valid, X_test, y_test,
                    has_valid, has_test, selected_features, pre_encoding_features,
                    stage1_report, categorical_report, external_cohorts
    """
    args = ctx["args"]
    train_df, valid_df, test_df = ctx["train_df"], ctx["valid_df"], ctx["test_df"]
    stage0_features = list(ctx["stage0_features"])
    groups = ctx["groups"]
    fe_mode_cfg = ctx["fe_mode_cfg"]
    external_spec = ctx["external_spec"]

    # ── Train-only missingness check ─────────────────────────────────────
    _TRAIN_MISS_THRESHOLD = 0.95
    _features_to_drop: list[str] = []
    for feat in stage0_features:
        if feat not in train_df.columns:
            continue
        tr_miss = train_df[feat].isna().mean()
        if tr_miss > _TRAIN_MISS_THRESHOLD:
            print(
                f"[WARN] high_train_missingness: "
                f"'{feat}' missing {tr_miss:.1%} in training data. "
                f"Dropping feature (>{_TRAIN_MISS_THRESHOLD:.0%} threshold)."
            )
            _features_to_drop.append(feat)
    if _features_to_drop:
        _drop_set = set(_features_to_drop)
        stage0_features = [f for f in stage0_features if f not in _drop_set]
        if not stage0_features:
            raise SystemExit(
                "All features dropped due to high missingness in training data. "
                "Check data quality or adjust inclusion criteria."
            )

    low_mem = getattr(args, "low_memory", False)
    if low_mem:
        for _df in (train_df, valid_df, test_df):
            for col in _df.select_dtypes(include=["float64"]).columns:
                _df[col] = pd.to_numeric(_df[col], downcast="float")
            for col in _df.select_dtypes(include=["int64"]).columns:
                _df[col] = pd.to_numeric(_df[col], downcast="integer")

    # ── Filter + stability selection ────────────────────────────────
    X_train_stage0, y_train = prepare_xy(train_df, stage0_features, args.target_col)
    stage1_features, stage1_report = select_features_by_filter(
        X_train_stage0,
        stage0_features,
        max_missing_ratio=float(fe_mode_cfg["max_missing_ratio"]),
        min_variance=float(fe_mode_cfg["min_variance"]),
    )
    if not stage1_features:
        stage1_features = list(stage0_features)

    categorical_report = detect_categorical_features(X_train_stage0, stage1_features)
    stage1_report["categorical_analysis"] = categorical_report

    stability_frequency = feature_stability_frequency(
        X_train=X_train_stage0,
        y_train=y_train,
        features=stage1_features,
        repeats=int(fe_mode_cfg["stability_repeats"]),
        seed=int(args.random_seed),
    )
    selected_features, group_selection_report = group_preselect_features(
        X_train=X_train_stage0,
        y_train=y_train,
        features=stage1_features,
        groups=groups,
        keep_ratio=float(fe_mode_cfg["group_keep_ratio"]),
        stability_frequency=stability_frequency,
    )
    if not selected_features:
        selected_features = list(stage1_features)

    del X_train_stage0
    if low_mem:
        gc.collect()

    X_train, y_train = prepare_xy(train_df, selected_features, args.target_col)
    if len(valid_df) > 0:
        X_valid, y_valid = prepare_xy(valid_df, selected_features, args.target_col)
    else:
        X_valid, y_valid = pd.DataFrame(), np.array([])
    if len(test_df) > 0:
        X_test, y_test = prepare_xy(test_df, selected_features, args.target_col)
    else:
        X_test, y_test = pd.DataFrame(), np.array([])
    has_valid = len(X_valid) > 0 and len(y_valid) > 0
    has_test = len(X_test) > 0 and len(y_test) > 0

    # Auto-encode detected categorical features (fit on train only, MLGG-P05)
    pre_encoding_features = list(selected_features)
    if categorical_report.get("categorical_count", 0) > 0:
        X_train, X_valid, X_test, selected_features = encode_categorical_features(
            X_train, X_valid, X_test, categorical_report,
        )
        print(f"  Categorical encoding: {categorical_report['categorical_count']} features detected, "
              f"now {len(selected_features)} columns after OneHot.")

    # VIF multicollinearity detection (train only)
    from _gate_utils import compute_vif, check_nonlinearity
    _vif_data = X_train.values if hasattr(X_train, "values") else X_train
    _vif_data = np.where(np.isnan(_vif_data),
                         np.nanmedian(_vif_data, axis=0), _vif_data)
    if _vif_data.shape[1] <= 200:
        vif_report = compute_vif(_vif_data, selected_features)
        stage1_report["vif_analysis"] = vif_report
        if vif_report.get("critical_features"):
            print(f"  VIF WARNING: {len(vif_report['critical_features'])} features with VIF>10: "
                  f"{vif_report['critical_features'][:5]}")
    else:
        stage1_report["vif_analysis"] = {"skipped": True, "reason": f"p={_vif_data.shape[1]} > 200"}

    # Nonlinearity check (train only)
    nonlinearity_report = check_nonlinearity(_vif_data, y_train, selected_features)
    nonlinear_features = [r["feature"] for r in nonlinearity_report if r.get("nonlinear")]
    stage1_report["nonlinearity_analysis"] = {
        "results": nonlinearity_report,
        "nonlinear_features": nonlinear_features,
        "n_nonlinear": len(nonlinear_features),
    }
    if nonlinear_features:
        print(f"  Nonlinearity detected in {len(nonlinear_features)} features: "
              f"{nonlinear_features[:5]}")

    # Train medians for external cohort missing-feature fill
    _train_medians = {}
    if hasattr(X_train, "columns"):
        for col in X_train.columns:
            med = X_train[col].median()
            if math.isfinite(med):
                _train_medians[col] = float(med)
    external_cohorts = resolve_external_cohorts(
        external_spec=external_spec,
        external_spec_path=args.external_cohort_spec,
        feature_cols=selected_features,
        default_target_col=args.target_col,
        default_patient_id_col=args.patient_id_col,
        train_fill_values=_train_medians,
    )
    if args.external_cohort_spec and not external_cohorts:
        import logging as _logging
        _logging.warning("external_cohort_spec provided but contains no cohort entries; skipping external validation.")
    if has_valid and len(np.unique(y_valid)) < 2:
        raise SystemExit("valid split must contain both classes for threshold/model selection.")

    ctx.update({
        "X_train": X_train, "y_train": y_train,
        "X_valid": X_valid, "y_valid": y_valid,
        "X_test": X_test, "y_test": y_test,
        "has_valid": has_valid, "has_test": has_test,
        "selected_features": selected_features,
        "pre_encoding_features": pre_encoding_features,
        "stage1_features": stage1_features,
        "stage1_report": stage1_report,
        "categorical_report": categorical_report,
        "external_cohorts": external_cohorts,
        "stability_frequency": stability_frequency,
        "group_selection_report": group_selection_report,
        "low_mem": low_mem,
    })


def _phase3_imbalance(ctx: Dict[str, Any]) -> None:
    """Phase 3: Resolve imputation plan and probe imbalance strategies via CV.

    Reads from ctx: X_train, y_train, selected_features, missingness_policy,
                    model_pool_config, args
    Writes to ctx:  imputation, selected_imbalance_strategy, effective_class_weight,
                    strategy_probe_rows, resolved_dev
    """
    args = ctx["args"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    selected_features = ctx["selected_features"]
    missingness_policy = ctx["missingness_policy"]
    model_pool_config = ctx["model_pool_config"]

    imputation = resolve_imputation_plan(
        missingness_policy,
        train_rows=int(X_train.shape[0]),
        feature_count=len(selected_features),
    )
    positive_count = int(np.sum(y_train == 1))
    negative_count = int(np.sum(y_train == 0))
    minority_count = int(min(positive_count, negative_count))
    majority_count = int(max(positive_count, negative_count))
    imbalance_ratio = (float(majority_count) / float(minority_count)) if minority_count > 0 else float("inf")
    selected_imbalance_metric = str(getattr(args, "imbalance_selection_metric", "pr_auc")).strip().lower()
    if selected_imbalance_metric not in {"pr_auc", "roc_auc"}:
        raise SystemExit("--imbalance-selection-metric must be pr_auc or roc_auc.")
    imbalance_candidates = resolve_imbalance_strategy_candidates(
        candidates_arg=str(getattr(args, "imbalance_strategy_candidates", "")),
        single_arg=str(getattr(args, "imbalance_strategy", "")),
        class_weight_override=str(getattr(args, "class_weight_override", "auto")),
        imbalance_ratio=float(imbalance_ratio),
    )
    if not imbalance_candidates:
        imbalance_candidates = ["none"]
    strategy_probe_rows: List[Dict[str, Any]] = []
    selected_imbalance_strategy = str(imbalance_candidates[0])

    resolved_dev = resolve_device(str(getattr(args, "device", "cpu")))

    if len(imbalance_candidates) > 1:
        probe_results: List[Dict[str, Any]] = []
        for idx, strategy in enumerate(imbalance_candidates):
            probe_class_weight = "balanced" if strategy == "class_weight" else None
            try:
                probe_estimator = _build_estimator_for_family(
                    family="logistic_l2",
                    params={"C": 1.0},
                    seed=int(args.random_seed),
                    imputation_strategy=str(imputation["executed_strategy"]),
                    class_weight=probe_class_weight,
                    n_jobs=int(getattr(args, "n_jobs", -1)),
                    device=resolved_dev,
                )
                mean_score, std_score, n_folds, _ = cv_score_pr_auc(
                    estimator=probe_estimator,
                    X=X_train,
                    y=y_train,
                    n_splits=args.cv_splits,
                    seed=int(args.random_seed) + (idx * 17),
                    imbalance_strategy=str(strategy),
                    score_metric=selected_imbalance_metric,
                    temporal_cv=bool(getattr(args, "temporal_cv", False)),
                )
                probe_results.append({
                    "strategy": str(strategy), "status": "pass",
                    "selection_metric": selected_imbalance_metric,
                    "mean": float(mean_score), "std": float(std_score),
                    "n_folds": int(n_folds),
                })
            except Exception as exc:
                probe_results.append({
                    "strategy": str(strategy), "status": "fail",
                    "selection_metric": selected_imbalance_metric,
                    "error": str(exc),
                })
        passed = [row for row in probe_results if row.get("status") == "pass"]
        if not passed:
            error_tokens: List[str] = []
            for row in probe_results:
                strategy_name = str(row.get("strategy", "unknown"))
                err = str(row.get("error", "unknown_error")).strip() or "unknown_error"
                error_tokens.append(f"{strategy_name}={err}")
            raise SystemExit(
                "imbalance_strategy_probe_failed: all requested imbalance strategies "
                f"failed during CV probe. details: {'; '.join(error_tokens)}"
            )
        selected_probe = sorted(
            passed,
            key=lambda row: (
                -float(row.get("mean", 0.0)),
                float(row.get("std", 0.0)),
                str(row.get("strategy", "")),
            ),
        )[0]
        selected_imbalance_strategy = str(selected_probe.get("strategy"))
        strategy_probe_rows = probe_results
    else:
        strategy_probe_rows = [{
            "strategy": str(selected_imbalance_strategy), "status": "pass",
            "selection_metric": selected_imbalance_metric,
            "selection_mode": "single_strategy_no_probe",
        }]

    effective_class_weight: Optional[str] = "balanced" if selected_imbalance_strategy == "class_weight" else None
    model_pool_config["train_rows"] = int(X_train.shape[0])
    model_pool_config["feature_count"] = len(selected_features)
    if str(model_pool_config.get("search_strategy", "")).strip().lower() == "optuna":
        model_pool_config["optuna_X_train"] = X_train
        model_pool_config["optuna_y_train"] = y_train
        model_pool_config["optuna_cv_splits"] = int(args.cv_splits)
        model_pool_config["optuna_trials"] = int(getattr(args, "optuna_trials", 50))

    ctx.update({
        "imputation": imputation,
        "imbalance_candidates": imbalance_candidates,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "imbalance_ratio": imbalance_ratio,
        "selected_imbalance_metric": selected_imbalance_metric,
        "selected_imbalance_strategy": selected_imbalance_strategy,
        "effective_class_weight": effective_class_weight,
        "strategy_probe_rows": strategy_probe_rows,
        "resolved_dev": resolved_dev,
    })


def _phase4_candidates(ctx: Dict[str, Any]) -> None:
    """Phase 4: Build candidate model pool and score via CV or validation.

    Reads from ctx: args, X_train, y_train, X_valid, y_valid, has_valid,
                    imputation, effective_class_weight, model_pool_config,
                    resolved_dev, selected_imbalance_strategy, selection_data
    Writes to ctx:  candidates, candidate_space_meta, candidate_rows, estimator_map
    """
    args = ctx["args"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    has_valid = ctx["has_valid"]
    imputation = ctx["imputation"]
    effective_class_weight = ctx["effective_class_weight"]
    model_pool_config = ctx["model_pool_config"]
    resolved_dev = ctx["resolved_dev"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]
    selection_data = ctx["selection_data"]

    candidates, candidate_space_meta = build_candidates(
        seed=int(args.random_seed),
        sampling_seed=int(args.random_seed),
        imputation_strategy=str(imputation["executed_strategy"]),
        class_weight=effective_class_weight,
        model_pool_config=model_pool_config,
        device=resolved_dev,
        temporal_cv=bool(getattr(args, "temporal_cv", False)),
    )
    if len(candidates) < 3:
        raise SystemExit(
            "candidate_pool_too_small: candidate pool must contain >=3 models; "
            "expand --model-pool or increase --max-trials-per-family."
        )
    checkpoint_path = Path(args.checkpoint_file) if args.checkpoint_file else None
    resumed_rows: Dict[str, Dict[str, Any]] = {}
    if checkpoint_path and args.resume_from_checkpoint and checkpoint_path.exists():
        try:
            with checkpoint_path.open("r", encoding="utf-8") as _cfh:
                _ckpt = json.load(_cfh)
            if isinstance(_ckpt, dict) and isinstance(_ckpt.get("candidate_rows"), list):
                for _cr in _ckpt["candidate_rows"]:
                    if isinstance(_cr, dict) and "model_id" in _cr:
                        resumed_rows[str(_cr["model_id"])] = _cr
                print(f"Checkpoint: resumed {len(resumed_rows)} scored candidates.", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Checkpoint: corrupted or unreadable ({exc}), starting fresh.", file=sys.stderr)

    candidate_rows: List[Dict[str, Any]] = []
    n_candidates = len(candidates)
    for cand_idx, cand in enumerate(candidates):
        mid = str(cand["model_id"])
        if mid in resumed_rows:
            candidate_rows.append(resumed_rows[mid])
            print(f"[PROGRESS] {cand_idx + 1}/{n_candidates} {mid} (cached)", file=sys.stderr, flush=True)
            continue
        print(f"[PROGRESS] {cand_idx + 1}/{n_candidates} {mid}", file=sys.stderr, flush=True)
        # Internal-imbalance families skip external resampling
        cand_imbalance = "none" if cand.get("_internal_imbalance") else selected_imbalance_strategy
        if selection_data == "cv_inner":
            mean_score, std_score, n_folds, fold_scores = cv_score_pr_auc(
                cand["estimator"], X_train, y_train,
                n_splits=args.cv_splits, seed=args.random_seed,
                imbalance_strategy=cand_imbalance,
                score_metric="pr_auc",
                temporal_cv=bool(getattr(args, "temporal_cv", False)),
            )
        else:
            if not has_valid:
                raise SystemExit("selection_data=valid requires a validation split.")
            model = clone(cand["estimator"])
            model, _ = fit_estimator_with_imbalance(
                estimator=model, X_train=X_train, y_train=y_train,
                strategy=cand_imbalance, seed=int(args.random_seed),
            )
            valid_proba = predict_proba_1(model, X_valid)
            mean_score = float(average_precision_score(y_valid, valid_proba))
            std_score, n_folds, fold_scores = 0.0, 1, [mean_score]
        candidate_rows.append({
            "model_id": cand["model_id"], "base_model_id": cand["base_model_id"],
            "family": cand["family"], "complexity_rank": cand["complexity_rank"],
            "hyperparameters": cand["hyperparameters"],
            "regularization_profile": cand["regularization_profile"],
            "search_meta": cand["search_meta"],
            "selection_metrics": {"pr_auc": {
                "mean": mean_score, "std": std_score,
                "n_folds": n_folds, "fold_scores": [float(x) for x in fold_scores],
            }},
            "selected": False,
        })
        if checkpoint_path:
            _ckpt_payload = {"candidate_rows": candidate_rows, "completed_count": len(candidate_rows)}
            _ckpt_tmp = checkpoint_path.with_suffix(".tmp")
            with _ckpt_tmp.open("w", encoding="utf-8") as _cfh:
                json.dump(_ckpt_payload, _cfh, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False)
            _ckpt_tmp.replace(checkpoint_path)

    estimator_map = {cand["model_id"]: cand["estimator"] for cand in candidates}

    requested_ensembles = [f for f in model_pool_config.get("model_pool", []) if f in ENSEMBLE_FAMILIES]
    ensemble_top_k = int(getattr(args, "ensemble_top_k", 0) or 0)
    if ensemble_top_k <= 0 and requested_ensembles:
        ensemble_top_k = DEFAULT_ENSEMBLE_TOP_K
    if requested_ensembles and ensemble_top_k >= 2 and len(candidate_rows) >= 2:
        ensemble_cands = build_ensemble_candidates(
            candidate_rows=candidate_rows, estimator_map=estimator_map,
            requested_ensembles=requested_ensembles, top_k=ensemble_top_k,
            seed=int(args.random_seed),
        )
        for ecand in ensemble_cands:
            if selection_data == "cv_inner":
                mean_score, std_score, n_folds, fold_scores = cv_score_pr_auc(
                    ecand["estimator"], X_train, y_train,
                    n_splits=args.cv_splits, seed=args.random_seed,
                    imbalance_strategy=selected_imbalance_strategy,
                    score_metric="pr_auc",
                    temporal_cv=bool(getattr(args, "temporal_cv", False)),
                )
            else:
                if not has_valid:
                    raise SystemExit("selection_data=valid requires a validation split for ensemble scoring.")
                emodel = clone(ecand["estimator"])
                emodel, _ = fit_estimator_with_imbalance(
                    estimator=emodel, X_train=X_train, y_train=y_train,
                    strategy=selected_imbalance_strategy, seed=int(args.random_seed),
                )
                valid_proba = predict_proba_1(emodel, X_valid)
                mean_score = float(average_precision_score(y_valid, valid_proba))
                std_score, n_folds, fold_scores = 0.0, 1, [mean_score]
            candidate_rows.append({
                "model_id": ecand["model_id"], "base_model_id": ecand["base_model_id"],
                "family": ecand["family"], "complexity_rank": ecand["complexity_rank"],
                "hyperparameters": ecand["hyperparameters"],
                "regularization_profile": ecand["regularization_profile"],
                "search_meta": ecand["search_meta"],
                "selection_metrics": {"pr_auc": {
                    "mean": mean_score, "std": std_score,
                    "n_folds": n_folds, "fold_scores": [float(x) for x in fold_scores],
                }},
                "selected": False,
            })
            estimator_map[ecand["model_id"]] = ecand["estimator"]

    ctx.update({
        "candidates": candidates, "candidate_space_meta": candidate_space_meta,
        "candidate_rows": candidate_rows, "estimator_map": estimator_map,
    })


def _phase5_selection(ctx: Dict[str, Any]) -> None:
    """Phase 5: Select best model via one-SE rule, fit on full train set.

    Reads from ctx: candidate_rows, estimator_map, X_train, y_train, X_valid,
                    y_valid, selected_imbalance_strategy, threshold_selection_split,
                    calibration_fit_split, args
    Writes to ctx:  selected_model_id, selected_estimator, selected_candidate_row,
                    selected_fit_meta, threshold_y, threshold_proba_raw,
                    calibration_y, calibration_proba_raw
    """
    args = ctx["args"]
    candidate_rows = ctx["candidate_rows"]
    estimator_map = ctx["estimator_map"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]
    threshold_selection_split = ctx["threshold_selection_split"]
    calibration_fit_split = ctx["calibration_fit_split"]

    trace = choose_model_one_se([
        {
            "model_id": row["model_id"],
            "complexity_rank": row["complexity_rank"],
            "mean": row["selection_metrics"]["pr_auc"]["mean"],
            "std": row["selection_metrics"]["pr_auc"]["std"],
            "n_folds": row["selection_metrics"]["pr_auc"]["n_folds"],
        }
        for row in candidate_rows
    ])
    selected_model_id = str(trace["chosen_model_id"])
    for row in candidate_rows:
        row["selected"] = bool(row["model_id"] == selected_model_id)
    selected_candidate_row = next((row for row in candidate_rows if bool(row.get("selected"))), None)
    selected_estimator = clone(estimator_map[selected_model_id])
    selected_estimator, selected_fit_meta = fit_estimator_with_imbalance(
        estimator=selected_estimator, X_train=X_train, y_train=y_train,
        strategy=selected_imbalance_strategy, seed=int(args.random_seed),
    )
    if threshold_selection_split == "valid":
        threshold_y = y_valid
        threshold_proba_raw = predict_proba_1(selected_estimator, X_valid)
    else:
        threshold_y = y_train
        threshold_proba_raw = cv_oof_proba(
            estimator=selected_estimator, X=X_train, y=y_train,
            n_splits=args.cv_splits, seed=args.random_seed,
            imbalance_strategy=selected_imbalance_strategy,
        )
    if calibration_fit_split == "valid":
        calibration_y = y_valid
        calibration_proba_raw = predict_proba_1(selected_estimator, X_valid)
    else:
        calibration_y = y_train
        calibration_proba_raw = cv_oof_proba(
            estimator=selected_estimator, X=X_train, y=y_train,
            n_splits=args.cv_splits, seed=args.random_seed,
            imbalance_strategy=selected_imbalance_strategy,
        )

    ctx.update({
        "selected_model_id": selected_model_id,
        "selected_estimator": selected_estimator,
        "selected_candidate_row": selected_candidate_row,
        "selected_fit_meta": selected_fit_meta,
        "selection_trace": trace,
        "threshold_y": threshold_y, "threshold_proba_raw": threshold_proba_raw,
        "calibration_y": calibration_y, "calibration_proba_raw": calibration_proba_raw,
    })


def _phase6_calibration(ctx: Dict[str, Any]) -> None:
    """Phase 6: Fit probability calibrator and choose clinical threshold.

    Reads from ctx: calibration_y, calibration_proba_raw, threshold_proba_raw,
                    threshold_y, calibration_method, selected_estimator,
                    threshold_selection_split, has_valid, X_valid, y_valid,
                    X_train, y_train, selected_imbalance_strategy, beta,
                    sensitivity_floor, npv_floor, specificity_floor, ppv_floor, args
    Writes to ctx:  calibrator, selected_threshold, threshold_info
    """
    args = ctx["args"]
    calibration_method = ctx["calibration_method"]
    selected_estimator = ctx["selected_estimator"]
    threshold_selection_split = ctx["threshold_selection_split"]
    has_valid = ctx["has_valid"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]

    # Auto-enable Platt calibration for internal-imbalance models.
    # Balanced bootstrap / undersampling shifts predicted probabilities
    # (van den Goorbergh et al., BMC Med Res Methodol 2022;22:312).
    # Sigmoid (Platt) scaling corrects this with minimal overhead.
    selected_row = ctx.get("selected_candidate_row") or {}
    family = str(selected_row.get("base_model_id", ""))
    if family in INTERNAL_IMBALANCE_FAMILIES and calibration_method == "none":
        calibration_method = "sigmoid"
        ctx["calibration_method"] = calibration_method
        print(
            f"[AUTO] calibration_method upgraded none→sigmoid for {family} "
            f"(internal resampling shifts probabilities; van den Goorbergh 2022)",
            file=sys.stderr, flush=True,
        )

    calibrator = fit_probability_calibrator(
        y_true=ctx["calibration_y"], proba_raw=ctx["calibration_proba_raw"],
        method=calibration_method, seed=int(args.random_seed),
    )
    threshold_proba = apply_probability_calibrator(calibrator, ctx["threshold_proba_raw"])
    guard_y: Optional[np.ndarray] = None
    guard_proba: Optional[np.ndarray] = None
    if threshold_selection_split == "cv_inner" and has_valid:
        guard_y = y_valid
        guard_proba = apply_probability_calibrator(calibrator, predict_proba_1(selected_estimator, X_valid))
    elif threshold_selection_split == "cv_inner" and not has_valid:
        guard_y = y_train
        guard_proba_raw = cv_oof_proba(
            estimator=selected_estimator, X=X_train, y=y_train,
            n_splits=args.cv_splits, seed=args.random_seed + 7777,
            imbalance_strategy=selected_imbalance_strategy,
        )
        guard_proba = apply_probability_calibrator(calibrator, guard_proba_raw)
    else:
        guard_y = y_train
        guard_proba_raw = cv_oof_proba(
            estimator=selected_estimator, X=X_train, y=y_train,
            n_splits=args.cv_splits, seed=args.random_seed,
            imbalance_strategy=selected_imbalance_strategy,
        )
        guard_proba = apply_probability_calibrator(calibrator, guard_proba_raw)
    threshold_info = choose_threshold(
        y_valid=ctx["threshold_y"], proba_valid=threshold_proba,
        beta=ctx["beta"],
        sensitivity_floor=ctx["sensitivity_floor"], npv_floor=ctx["npv_floor"],
        specificity_floor=ctx["specificity_floor"], ppv_floor=ctx["ppv_floor"],
        guard_y=guard_y, guard_proba=guard_proba,
    )
    selected_threshold = float(threshold_info["selected_threshold"])

    ctx.update({
        "calibrator": calibrator,
        "selected_threshold": selected_threshold,
        "threshold_info": threshold_info,
    })


def _phase78_eval_diagnostics(ctx: Dict[str, Any]) -> None:
    """Phases 7-8: Evaluate all splits, compute CI, baselines, build model_selection_report.

    Reads from ctx: selected_estimator, calibrator, selected_threshold, X/y arrays,
                    has_valid, has_test, beta, fast_diagnostic_mode, imputation, etc.
    Writes to ctx:  train/valid/test_proba, train/valid/test_metrics, train/valid/test_cm,
                    ci_lo, ci_hi, ci_n, all_metric_ci, optimism_correction,
                    learning_curve_report, prevalence_baseline, logistic_baseline,
                    baseline_logit_proba_test, baseline_proba_test, split_fingerprints,
                    model_selection_report, overfit_risk, overfit_gaps, overfit_warnings
    """
    args = ctx["args"]
    selected_estimator = ctx["selected_estimator"]
    calibrator = ctx["calibrator"]
    selected_threshold = ctx["selected_threshold"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    X_test, y_test = ctx["X_test"], ctx["y_test"]
    has_valid, has_test = ctx["has_valid"], ctx["has_test"]
    beta = ctx["beta"]
    fast_diagnostic_mode = ctx["fast_diagnostic_mode"]
    imputation = ctx["imputation"]
    effective_class_weight = ctx["effective_class_weight"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]

    # ── Metrics on all splits ────────────────────────────────────────────
    train_proba = apply_probability_calibrator(calibrator, predict_proba_1(selected_estimator, X_train))
    train_metrics, train_cm = metric_panel(y_train, train_proba, selected_threshold, beta=beta)

    if has_valid:
        valid_proba = apply_probability_calibrator(calibrator, predict_proba_1(selected_estimator, X_valid))
        valid_metrics, valid_cm = metric_panel(y_valid, valid_proba, selected_threshold, beta=beta)
    else:
        valid_proba = np.array([])
        valid_metrics, valid_cm = {}, {}

    if has_test:
        test_proba = apply_probability_calibrator(calibrator, predict_proba_1(selected_estimator, X_test))
        test_metrics, test_cm = metric_panel(y_test, test_proba, selected_threshold, beta=beta)
    else:
        test_proba = np.array([])
        test_metrics, test_cm = {}, {}

    # ── Bootstrap CI ─────────────────────────────────────────────────────
    if fast_diagnostic_mode:
        ci_lo, ci_hi, ci_n = None, None, 0
        all_metric_ci: Dict[str, Any] = {}
    else:
        ci_lo, ci_hi, ci_n = bootstrap_ci_pr_auc(
            y_true=y_test, proba=test_proba,
            n_resamples=int(args.bootstrap_resamples), seed=args.random_seed,
        )
        all_metric_ci, _ = bootstrap_metric_ci(
            y_true=y_test, y_score=test_proba,
            threshold=selected_threshold, beta=beta,
            n_resamples=int(args.bootstrap_resamples), seed=args.random_seed,
        )

    # ── Optimism correction ──────────────────────────────────────────────
    if fast_diagnostic_mode:
        optimism_correction: Dict[str, Any] = {"skipped": True, "reason": "fast_diagnostic_mode"}
    else:
        try:
            optimism_correction = bootstrap_optimism_correction(
                estimator=selected_estimator, X_train=X_train, y_train=y_train,
                threshold=selected_threshold, beta=beta,
                n_resamples=min(int(args.bootstrap_resamples), 200), seed=args.random_seed,
            )
        except Exception as exc:
            print(f"[WARN] bootstrap_optimism_correction failed: {exc}", file=sys.stderr)
            optimism_correction = {"skipped": True, "reason": str(exc)}

    # ── Learning curve ───────────────────────────────────────────────────
    if fast_diagnostic_mode:
        learning_curve_report: Dict[str, Any] = {"skipped": True, "reason": "fast_diagnostic_mode"}
    else:
        try:
            learning_curve_report = learning_curve_data(
                estimator=selected_estimator, X_train=X_train, y_train=y_train,
                X_valid=X_valid, y_valid=y_valid,
                threshold=selected_threshold, beta=beta, seed=args.random_seed,
            )
        except Exception as exc:
            print(f"[WARN] learning_curve_data failed: {exc}", file=sys.stderr)
            learning_curve_report = {"skipped": True, "reason": str(exc)}

    # ── Baselines ────────────────────────────────────────────────────────
    prevalence = float(np.mean(y_train))
    if has_test:
        baseline_proba_test = np.full(shape=y_test.shape[0], fill_value=prevalence, dtype=float)
        prevalence_baseline = {
            "roc_auc": float(roc_auc_score(y_test, baseline_proba_test)),
            "pr_auc": float(average_precision_score(y_test, baseline_proba_test)),
            "brier": float(brier_score_loss(y_test, baseline_proba_test)),
        }
    else:
        baseline_proba_test = np.array([])
        prevalence_baseline = {"roc_auc": None, "pr_auc": None, "brier": None}

    baseline_logit = Pipeline(steps=[
        ("imputer", build_imputer(str(imputation["executed_strategy"]), args.random_seed)),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            max_iter=4000, solver="liblinear", C=1.0,
            class_weight=effective_class_weight, random_state=args.random_seed,
        )),
    ])
    baseline_logit, baseline_fit_meta = fit_estimator_with_imbalance(
        estimator=baseline_logit, X_train=X_train, y_train=y_train,
        strategy=selected_imbalance_strategy, seed=int(args.random_seed) + 313,
    )
    if has_test:
        baseline_logit_proba_test = predict_proba_1(baseline_logit, X_test)
        logistic_baseline = {
            "roc_auc": float(roc_auc_score(y_test, baseline_logit_proba_test)),
            "pr_auc": float(average_precision_score(y_test, baseline_logit_proba_test)),
            "brier": float(brier_score_loss(y_test, baseline_logit_proba_test)),
        }
    else:
        baseline_logit_proba_test = np.array([])
        logistic_baseline = {"roc_auc": None, "pr_auc": None, "brier": None}

    # ── Split fingerprints ───────────────────────────────────────────────
    split_fingerprints = {
        "train": {
            "path": str(Path(args.train).expanduser().resolve()),
            "sha256": sha256_file(Path(args.train).expanduser().resolve()),
            "row_count": int(X_train.shape[0]),
        },
    }
    if has_valid and args.valid:
        split_fingerprints["valid"] = {
            "path": str(Path(args.valid).expanduser().resolve()),
            "sha256": sha256_file(Path(args.valid).expanduser().resolve()),
            "row_count": int(X_valid.shape[0]),
        }
    if has_test and args.test:
        split_fingerprints["test"] = {
            "path": str(Path(args.test).expanduser().resolve()),
            "sha256": sha256_file(Path(args.test).expanduser().resolve()),
            "row_count": int(X_test.shape[0]),
        }

    # ── Model selection report ───────────────────────────────────────────
    selection_data = ctx["selection_data"]
    model_pool_config = ctx["model_pool_config"]
    model_selection_report = {
        "status": "pass",
        "primary_metric": "pr_auc",
        "test_used_for_model_selection": False,
        "selection_policy": {
            "primary_metric": "pr_auc",
            "selection_data": selection_data,
            "one_se_rule": True,
            "complexity_tie_breaker": "prefer_lower_complexity_rank",
            "test_used_for_model_selection": False,
            "imbalance_strategy": selected_imbalance_strategy,
            "imbalance_strategy_candidates": list(ctx["imbalance_candidates"]),
            "imbalance_selection_metric": ctx["selected_imbalance_metric"],
            "imbalance_probe": ctx["strategy_probe_rows"],
            "requested_model_pool": list(model_pool_config.get("requested_models", [])),
            "model_pool": list(model_pool_config.get("model_pool", [])),
            "required_models": list(model_pool_config.get("required_models", [])),
            "auto_added_required_models": list(model_pool_config.get("auto_added_required_models", [])),
            "hyperparameter_tuning": {
                "strategy": str(model_pool_config.get("search_strategy", "random_subsample")),
                "max_trials_per_family": int(model_pool_config.get("max_trials_per_family", 1)),
                "sampling_seed": int(args.random_seed),
                "n_jobs": int(model_pool_config.get("n_jobs", -1)),
            },
        },
        "candidate_count": len(ctx["candidate_rows"]),
        "candidates": ctx["candidate_rows"],
        "selection_trace": ctx["selection_trace"],
        "selected_model_id": ctx["selected_model_id"],
        "selected_model_family": (ctx["selected_candidate_row"] or {}).get("base_model_id"),
        "selected_model_hyperparameters": (ctx["selected_candidate_row"] or {}).get("hyperparameters"),
        "selected_model_regularization_profile": (ctx["selected_candidate_row"] or {}).get("regularization_profile"),
        "candidate_space": ctx["candidate_space_meta"],
        "data_fingerprints": split_fingerprints,
        "imputation": imputation,
        "feature_engineering": {
            "mode": str(args.feature_engineering_mode),
            "selected_feature_count": int(len(ctx["selected_features"])),
            "selected_features": ctx["selected_features"],
            "selection_scope": "cv_inner_train_only" if selection_data == "cv_inner" else "train_only",
        },
    }

    # ── Overfit risk ─────────────────────────────────────────────────────
    overfit_risk, overfit_gaps, overfit_warnings = _compute_overfit_risk(
        train_metrics, valid_metrics, test_metrics,
    )
    if overfit_warnings:
        print(f"[WARN] Overfitting detected ({len(overfit_warnings)} signal(s)):")
        for w in overfit_warnings:
            print(f"  - {w}")

    ctx.update({
        "train_proba": train_proba, "train_metrics": train_metrics, "train_cm": train_cm,
        "valid_proba": valid_proba, "valid_metrics": valid_metrics, "valid_cm": valid_cm,
        "test_proba": test_proba, "test_metrics": test_metrics, "test_cm": test_cm,
        "ci_lo": ci_lo, "ci_hi": ci_hi, "ci_n": ci_n, "all_metric_ci": all_metric_ci,
        "optimism_correction": optimism_correction, "learning_curve_report": learning_curve_report,
        "prevalence": prevalence, "prevalence_baseline": prevalence_baseline,
        "logistic_baseline": logistic_baseline,
        "baseline_logit_proba_test": baseline_logit_proba_test,
        "baseline_proba_test": baseline_proba_test,
        "baseline_fit_meta": baseline_fit_meta,
        "split_fingerprints": split_fingerprints,
        "model_selection_report": model_selection_report,
        "overfit_risk": overfit_risk, "overfit_gaps": overfit_gaps,
        "overfit_warnings": overfit_warnings,
    })


def _phase9_overfit_callback(ctx: Dict[str, Any]) -> None:
    """Phase 9: If overfit_risk >= medium, evaluate alternative candidates.

    May REASSIGN via ctx: selected_model_id, selected_estimator, calibrator,
    selected_threshold, threshold_info, train/valid/test metrics/cm/proba,
    ci_lo/hi/n, all_metric_ci, overfit_risk/gaps/warnings, selected_candidate_row.

    Always writes: fallback_trace, original_model_id, callback_activated,
                   overfit_recommendations.
    """
    args = ctx["args"]
    selected_model_id = ctx["selected_model_id"]
    selected_estimator = ctx["selected_estimator"]
    calibrator = ctx["calibrator"]
    selected_threshold = ctx["selected_threshold"]
    train_metrics = ctx["train_metrics"]; valid_metrics = ctx["valid_metrics"]
    test_metrics = ctx["test_metrics"]
    train_proba = ctx["train_proba"]; valid_proba = ctx["valid_proba"]
    test_proba = ctx["test_proba"]
    train_cm = ctx["train_cm"]; valid_cm = ctx["valid_cm"]; test_cm = ctx["test_cm"]
    overfit_risk = ctx["overfit_risk"]; overfit_gaps = ctx["overfit_gaps"]
    overfit_warnings = ctx["overfit_warnings"]
    candidate_rows = ctx["candidate_rows"]; estimator_map = ctx["estimator_map"]
    selected_candidate_row = ctx["selected_candidate_row"]
    model_selection_report = ctx["model_selection_report"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    X_test, y_test = ctx["X_test"], ctx["y_test"]
    has_test = ctx["has_test"]
    beta = ctx["beta"]
    fast_diagnostic_mode = ctx["fast_diagnostic_mode"]
    ci_lo, ci_hi, ci_n = ctx["ci_lo"], ctx["ci_hi"], ctx["ci_n"]
    all_metric_ci = ctx["all_metric_ci"]
    threshold_info = ctx["threshold_info"]

    fallback_trace: List[Dict[str, Any]] = []
    original_model_id = selected_model_id
    callback_activated = overfit_risk in ("medium", "high")
    if callback_activated:
        print(f"[CALLBACK] Overfitting risk={overfit_risk} — evaluating alternative candidates (train-valid only)...")
        initial_max_gap = max(
            float(overfit_gaps.get(k, {}).get("train_valid_gap", 0.0))
            for k in ("pr_auc", "roc_auc")
        )
        fallback_trace.append({
            "round": 0, "model_id": selected_model_id,
            "risk": overfit_risk, "max_gap": round(initial_max_gap, 6),
            "valid_pr_auc": float(valid_metrics.get("pr_auc", 0.0)),
            "action": "initial_selection",
        })
        alt_candidates = sorted(
            [r for r in candidate_rows if r["model_id"] != selected_model_id],
            key=lambda r: (int(r.get("complexity_rank", 999)), str(r["model_id"])),
        )
        eval_kwargs = dict(
            estimator_map=estimator_map,
            X_train=X_train, y_train=y_train, X_valid=X_valid, y_valid=y_valid,
            threshold_selection_split=ctx["threshold_selection_split"],
            calibration_fit_split=ctx["calibration_fit_split"],
            calibration_method=ctx["calibration_method"],
            beta=beta, sensitivity_floor=ctx["sensitivity_floor"],
            npv_floor=ctx["npv_floor"], specificity_floor=ctx["specificity_floor"],
            ppv_floor=ctx["ppv_floor"], cv_splits=args.cv_splits,
            random_seed=args.random_seed,
            imbalance_strategy=ctx["selected_imbalance_strategy"],
        )
        best_alt: Optional[Dict[str, Any]] = None
        for rnd, alt_row in enumerate(alt_candidates, start=1):
            alt_id = str(alt_row["model_id"])
            try:
                result = _full_candidate_eval(model_id=alt_id, **eval_kwargs)
            except Exception as exc:
                print(f"  [CALLBACK] round {rnd}: {alt_id} — error: {exc}")
                fallback_trace.append({
                    "round": rnd, "model_id": alt_id,
                    "risk": "error", "max_gap": None,
                    "valid_pr_auc": None, "action": f"error: {exc}",
                })
                continue
            fallback_trace.append({
                "round": rnd, "model_id": alt_id,
                "risk": result["risk"], "max_gap": round(result["max_gap"], 6),
                "valid_pr_auc": round(result["valid_pr_auc"], 4), "action": "evaluated",
            })
            print(f"  [CALLBACK] round {rnd}: {alt_id} — risk={result['risk']}, "
                  f"valid-PR-AUC={result['valid_pr_auc']:.4f}, gap={result['max_gap']:.4f}")
            if result["risk"] == "low":
                best_alt = result
                break
            if best_alt is None or result["max_gap"] < best_alt["max_gap"]:
                best_alt = result

        if best_alt is not None:
            accept = (
                best_alt["risk"] == "low"
                or (best_alt["risk"] == "medium" and overfit_risk == "high")
                or best_alt["max_gap"] < initial_max_gap - 0.02
            )
            if accept:
                alt_id = best_alt["model_id"]
                print(f"  [CALLBACK] Switching to {alt_id} (risk={best_alt['risk']}, "
                      f"gap={best_alt['max_gap']:.4f})")
                selected_model_id = alt_id
                selected_estimator = best_alt["estimator"]
                calibrator = best_alt["calibrator"]
                selected_threshold = best_alt["threshold"]
                threshold_info = best_alt["threshold_info"]
                train_metrics = best_alt["train_metrics"]
                valid_metrics = best_alt["valid_metrics"]
                train_cm = best_alt["train_cm"]; valid_cm = best_alt["valid_cm"]
                train_proba = best_alt["train_proba"]
                valid_proba = best_alt["valid_proba"]
                overfit_risk = best_alt["risk"]
                overfit_gaps = best_alt["gaps"]
                overfit_warnings = best_alt["warnings"]
                for row in candidate_rows:
                    row["selected"] = bool(row["model_id"] == selected_model_id)
                selected_candidate_row = next(
                    (r for r in candidate_rows if bool(r.get("selected"))), None
                )
                if has_test:
                    test_proba = apply_probability_calibrator(
                        calibrator, predict_proba_1(selected_estimator, X_test),
                    )
                    test_metrics, test_cm = metric_panel(y_test, test_proba, selected_threshold, beta=beta)
                    if not fast_diagnostic_mode:
                        ci_lo, ci_hi, ci_n = bootstrap_ci_pr_auc(
                            y_true=y_test, proba=test_proba,
                            n_resamples=int(args.bootstrap_resamples), seed=args.random_seed,
                        )
                        all_metric_ci, _ = bootstrap_metric_ci(
                            y_true=y_test, y_score=test_proba,
                            threshold=selected_threshold, beta=beta,
                            n_resamples=int(args.bootstrap_resamples), seed=args.random_seed,
                        )
                overfit_risk, overfit_gaps, overfit_warnings = _compute_overfit_risk(
                    train_metrics, valid_metrics, test_metrics if has_test else None,
                )
                fallback_trace.append({
                    "round": "final", "model_id": alt_id,
                    "risk": best_alt["risk"], "max_gap": round(best_alt["max_gap"], 6),
                    "valid_pr_auc": round(best_alt["valid_pr_auc"], 4), "action": "accepted",
                })
            else:
                print(f"  [CALLBACK] No better alternative found — keeping {selected_model_id}")
                fallback_trace.append({
                    "round": "final", "model_id": selected_model_id,
                    "risk": overfit_risk, "max_gap": round(initial_max_gap, 6),
                    "valid_pr_auc": round(float(valid_metrics.get("pr_auc", 0.0)), 4),
                    "action": "kept_original",
                })

    # Update model_selection_report with final model (may differ after callback)
    model_selection_report["selected_model_id"] = selected_model_id
    model_selection_report["selected_model_family"] = (selected_candidate_row or {}).get("base_model_id")
    model_selection_report["selected_model_hyperparameters"] = (selected_candidate_row or {}).get("hyperparameters")
    model_selection_report["selected_model_regularization_profile"] = (selected_candidate_row or {}).get("regularization_profile")

    overfit_recommendations: List[str] = []
    if overfit_risk in ("medium", "high"):
        overfit_recommendations.append("Increase regularization (higher C penalty, lower max_depth).")
        overfit_recommendations.append("Reduce feature count or apply stricter feature selection.")
        overfit_recommendations.append("Collect more training samples if possible.")
    if overfit_risk == "high":
        overfit_recommendations.append("Consider a simpler model family (e.g., logistic regression).")
        overfit_recommendations.append("Use stronger cross-validation (more folds, repeated CV).")

    ctx.update({
        "selected_model_id": selected_model_id, "selected_estimator": selected_estimator,
        "calibrator": calibrator, "selected_threshold": selected_threshold,
        "threshold_info": threshold_info,
        "train_metrics": train_metrics, "valid_metrics": valid_metrics,
        "test_metrics": test_metrics, "train_cm": train_cm, "valid_cm": valid_cm,
        "test_cm": test_cm, "train_proba": train_proba, "valid_proba": valid_proba,
        "test_proba": test_proba, "ci_lo": ci_lo, "ci_hi": ci_hi, "ci_n": ci_n,
        "all_metric_ci": all_metric_ci,
        "overfit_risk": overfit_risk, "overfit_gaps": overfit_gaps,
        "overfit_warnings": overfit_warnings,
        "selected_candidate_row": selected_candidate_row,
        "overfit_recommendations": overfit_recommendations,
        "fallback_trace": fallback_trace, "original_model_id": original_model_id,
        "callback_activated": callback_activated,
    })


def main() -> int:
    """Entry point for the train-select-evaluate pipeline.

    Orchestrates 10 phases:

    Phase 0: PREFLIGHT & CONFIG (args validation, policy loading)
      Outputs: args, policy, beta, thresholds, calibration/selection config
    Phase 1: DATA LOADING (splits, feature columns)
      Outputs: train/valid/test_df, X/y arrays, has_valid, has_test
    Phase 2: FEATURE ENGINEERING (filter, stability, VIF, encoding)
      Outputs: selected_features, stage1_report, categorical_report
    Phase 3: IMBALANCE PROBE (strategy selection)
      Outputs: selected_imbalance_strategy, effective_class_weight
    Phase 4: CANDIDATE POOL (build + CV score)
      Outputs: candidates, candidate_rows, estimator_map
    Phase 5: MODEL SELECTION (one-SE rule + fit)
      Outputs: selected_model_id, selected_estimator
    Phase 6: THRESHOLD & CALIBRATION
      Outputs: calibrator, selected_threshold, threshold_info
    Phase 7: EVALUATION (metrics + bootstrap CI)
      Outputs: train/valid/test_metrics, all_metric_ci
    Phase 8: DIAGNOSTICS (optimism correction, baselines, learning curve)
      Outputs: model_selection_report, prevalence/logistic baselines
    Phase 9: OVERFITTING CALLBACK [MUTATES 17 VARS]
      May reassign: selected_estimator, calibrator, threshold, metrics, probas
    Phase 10+: REPORTS & OUTPUT (external, robustness, seed, file writes)

    Returns:
        Exit code (0 for success).

    Raises:
        SystemExit: On invalid arguments or data issues.
        ValueError: On data validation failures (e.g., empty splits).
    """
    configure_runtime_warning_filters()
    args = parse_args()

    # All pipeline state flows through ctx — a mutable dict that each phase
    # reads from and writes to. This replaces 50+ local variables and makes
    # Phase 9's 17-variable mutation safe (it just updates ctx keys).
    ctx: Dict[str, Any] = {"args": args}

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 0: PREFLIGHT & CONFIG → _phase0_preflight_and_config()
    # ═══════════════════════════════════════════════════════════════════════
    print("[STEP  1/12] Preflight & config...", file=sys.stderr, flush=True)
    ctx.update(_phase0_preflight_and_config(args))

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 1: DATA LOADING → _phase1_data_loading()
    # ═══════════════════════════════════════════════════════════════════════
    print("[STEP  2/12] Loading data splits...", file=sys.stderr, flush=True)
    _phase1_data_loading(ctx)
    # Bridge ctx → locals for phases not yet migrated to ctx
    train_df = ctx["train_df"]
    valid_df = ctx["valid_df"]
    test_df = ctx["test_df"]
    stage0_features = ctx["stage0_features"]
    groups = ctx["groups"]
    forbidden_features = ctx["forbidden_features"]
    threshold_selection_split = ctx["threshold_selection_split"]
    calibration_fit_split = ctx["calibration_fit_split"]
    feature_group_spec = ctx["feature_group_spec"]
    fe_mode_cfg = ctx["fe_mode_cfg"]
    fast_diagnostic_mode = ctx["fast_diagnostic_mode"]
    policy = ctx["policy"]
    missingness_policy = ctx["missingness_policy"]
    external_spec = ctx["external_spec"]
    threshold_policy = ctx["threshold_policy"]
    clinical_floors = ctx["clinical_floors"]
    beta = ctx["beta"]
    sensitivity_floor = ctx["sensitivity_floor"]
    npv_floor = ctx["npv_floor"]
    specificity_floor = ctx["specificity_floor"]
    ppv_floor = ctx["ppv_floor"]
    calibration_method = ctx["calibration_method"]
    selection_data = ctx["selection_data"]
    model_pool_config = ctx["model_pool_config"]

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 2: FEATURE ENGINEERING → _phase2_feature_engineering()
    # ═════════════════════════════════════════════════════════════════════
    print("[STEP  3/12] Feature engineering...", file=sys.stderr, flush=True)
    _phase2_feature_engineering(ctx)
    # Bridge ctx → locals for phases not yet migrated
    X_train = ctx["X_train"]; y_train = ctx["y_train"]
    X_valid = ctx["X_valid"]; y_valid = ctx["y_valid"]
    X_test = ctx["X_test"]; y_test = ctx["y_test"]
    has_valid = ctx["has_valid"]; has_test = ctx["has_test"]
    selected_features = ctx["selected_features"]
    pre_encoding_features = ctx["pre_encoding_features"]
    stage1_report = ctx["stage1_report"]
    categorical_report = ctx["categorical_report"]
    external_cohorts = ctx["external_cohorts"]
    stage1_features = ctx["stage1_features"]
    stability_frequency = ctx["stability_frequency"]
    group_selection_report = ctx["group_selection_report"]
    low_mem = ctx["low_mem"]

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 3: IMPUTATION & IMBALANCE STRATEGY → _phase3_imbalance()
    # ═══════════════════════════════════════════════════════════════════════
    print("[STEP  4/12] Imputation & imbalance strategy...", file=sys.stderr, flush=True)
    ctx.update({"X_train": X_train, "y_train": y_train, "selected_features": selected_features,
                "missingness_policy": missingness_policy, "model_pool_config": model_pool_config})
    _phase3_imbalance(ctx)
    imputation = ctx["imputation"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]
    effective_class_weight = ctx["effective_class_weight"]
    strategy_probe_rows = ctx["strategy_probe_rows"]
    resolved_dev = ctx["resolved_dev"]
    imbalance_candidates = ctx["imbalance_candidates"]
    selected_imbalance_metric = ctx["selected_imbalance_metric"]
    positive_count = ctx["positive_count"]
    negative_count = ctx["negative_count"]
    imbalance_ratio = ctx["imbalance_ratio"]

    # ═══════════════════════════════════════════════════════════════════════
    # PHASES 4-6: CANDIDATE POOL → MODEL SELECTION → CALIBRATION
    # → _phase4_candidates(), _phase5_selection(), _phase6_calibration()
    # ═══════════════════════════════════════════════════════════════════════
    ctx.update({
        "X_train": X_train, "y_train": y_train, "X_valid": X_valid, "y_valid": y_valid,
        "has_valid": has_valid, "selected_features": selected_features,
        "imputation": imputation, "effective_class_weight": effective_class_weight,
        "model_pool_config": model_pool_config, "resolved_dev": resolved_dev,
        "selected_imbalance_strategy": selected_imbalance_strategy,
        "selection_data": selection_data,
        "threshold_selection_split": threshold_selection_split,
        "calibration_fit_split": calibration_fit_split,
        "calibration_method": calibration_method,
        "beta": beta, "sensitivity_floor": sensitivity_floor,
        "npv_floor": npv_floor, "specificity_floor": specificity_floor,
        "ppv_floor": ppv_floor,
    })
    print("[STEP  5/12] Building candidate models + CV scoring...", file=sys.stderr, flush=True)
    _phase4_candidates(ctx)
    print("[STEP  6/12] Model selection (one-SE rule)...", file=sys.stderr, flush=True)
    _phase5_selection(ctx)
    print("[STEP  7/12] Calibration + threshold...", file=sys.stderr, flush=True)
    _phase6_calibration(ctx)
    # Bridge ctx → locals (re-read calibration_method — may have been
    # auto-upgraded from 'none' to 'sigmoid' for imblearn models)
    calibration_method = ctx["calibration_method"]
    candidates = ctx["candidates"]
    candidate_space_meta = ctx["candidate_space_meta"]
    candidate_rows = ctx["candidate_rows"]
    estimator_map = ctx["estimator_map"]
    selected_model_id = ctx["selected_model_id"]
    selected_estimator = ctx["selected_estimator"]
    selected_candidate_row = ctx["selected_candidate_row"]
    selected_fit_meta = ctx["selected_fit_meta"]
    calibrator = ctx["calibrator"]
    selected_threshold = ctx["selected_threshold"]
    threshold_info = ctx["threshold_info"]
    threshold_y = ctx["threshold_y"]
    calibration_y = ctx["calibration_y"]
    trace = ctx["selection_trace"]

    # ═══════════════════════════════════════════════════════════════════════
    # PHASES 7-8: EVALUATION + DIAGNOSTICS → _phase78_eval_diagnostics()
    # ═══════════════════════════════════════════════════════════════════════
    ctx.update({
        "selected_estimator": selected_estimator, "calibrator": calibrator,
        "selected_threshold": selected_threshold, "threshold_info": threshold_info,
        "X_train": X_train, "y_train": y_train, "X_valid": X_valid, "y_valid": y_valid,
        "X_test": X_test, "y_test": y_test, "has_valid": has_valid, "has_test": has_test,
        "beta": beta, "fast_diagnostic_mode": fast_diagnostic_mode,
        "imputation": imputation, "effective_class_weight": effective_class_weight,
        "selected_imbalance_strategy": selected_imbalance_strategy,
        "selection_data": selection_data, "selected_model_id": selected_model_id,
        "selected_candidate_row": selected_candidate_row,
        "candidate_rows": candidate_rows, "candidate_space_meta": candidate_space_meta,
        "selection_trace": trace, "selected_features": selected_features,
        "imbalance_candidates": imbalance_candidates,
        "selected_imbalance_metric": selected_imbalance_metric,
        "strategy_probe_rows": strategy_probe_rows,
        "model_pool_config": model_pool_config,
    })
    print("[STEP  8/12] Evaluation (metrics + bootstrap CI)...", file=sys.stderr, flush=True)
    _phase78_eval_diagnostics(ctx)
    # Bridge ctx → locals for Phases 9+
    train_proba = ctx["train_proba"]; train_metrics = ctx["train_metrics"]; train_cm = ctx["train_cm"]
    valid_proba = ctx["valid_proba"]; valid_metrics = ctx["valid_metrics"]; valid_cm = ctx["valid_cm"]
    test_proba = ctx["test_proba"]; test_metrics = ctx["test_metrics"]; test_cm = ctx["test_cm"]
    ci_lo = ctx["ci_lo"]; ci_hi = ctx["ci_hi"]; ci_n = ctx["ci_n"]
    all_metric_ci = ctx["all_metric_ci"]
    optimism_correction = ctx["optimism_correction"]
    learning_curve_report = ctx["learning_curve_report"]
    prevalence_baseline = ctx["prevalence_baseline"]
    logistic_baseline = ctx["logistic_baseline"]
    baseline_logit_proba_test = ctx["baseline_logit_proba_test"]
    baseline_proba_test = ctx["baseline_proba_test"]
    split_fingerprints = ctx["split_fingerprints"]
    model_selection_report = ctx["model_selection_report"]
    overfit_risk = ctx["overfit_risk"]; overfit_gaps = ctx["overfit_gaps"]
    overfit_warnings = ctx["overfit_warnings"]
    baseline_fit_meta = ctx["baseline_fit_meta"]
    prevalence = ctx["prevalence"]


    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 9: OVERFITTING CALLBACK → _phase9_overfit_callback()
    # ═══════════════════════════════════════════════════════════════════════
    ctx.update({
        "selected_model_id": selected_model_id, "selected_estimator": selected_estimator,
        "calibrator": calibrator, "selected_threshold": selected_threshold,
        "threshold_info": threshold_info,
        "train_metrics": train_metrics, "valid_metrics": valid_metrics,
        "test_metrics": test_metrics, "train_cm": train_cm, "valid_cm": valid_cm,
        "test_cm": test_cm, "train_proba": train_proba, "valid_proba": valid_proba,
        "test_proba": test_proba, "ci_lo": ci_lo, "ci_hi": ci_hi, "ci_n": ci_n,
        "all_metric_ci": all_metric_ci,
        "overfit_risk": overfit_risk, "overfit_gaps": overfit_gaps,
        "overfit_warnings": overfit_warnings,
        "candidate_rows": candidate_rows, "estimator_map": estimator_map,
        "selected_candidate_row": selected_candidate_row,
        "model_selection_report": model_selection_report,
    })
    _phase9_overfit_callback(ctx)
    # Re-read all potentially mutated variables from ctx
    selected_model_id = ctx["selected_model_id"]
    selected_estimator = ctx["selected_estimator"]
    calibrator = ctx["calibrator"]
    selected_threshold = ctx["selected_threshold"]
    threshold_info = ctx["threshold_info"]
    train_metrics = ctx["train_metrics"]; valid_metrics = ctx["valid_metrics"]
    test_metrics = ctx["test_metrics"]
    train_cm = ctx["train_cm"]; valid_cm = ctx["valid_cm"]; test_cm = ctx["test_cm"]
    train_proba = ctx["train_proba"]; valid_proba = ctx["valid_proba"]
    test_proba = ctx["test_proba"]
    ci_lo = ctx["ci_lo"]; ci_hi = ctx["ci_hi"]; ci_n = ctx["ci_n"]
    all_metric_ci = ctx["all_metric_ci"]
    overfit_risk = ctx["overfit_risk"]; overfit_gaps = ctx["overfit_gaps"]
    overfit_warnings = ctx["overfit_warnings"]
    selected_candidate_row = ctx["selected_candidate_row"]
    overfit_recommendations = ctx["overfit_recommendations"]
    fallback_trace = ctx["fallback_trace"]
    original_model_id = ctx["original_model_id"]
    callback_activated = ctx["callback_activated"]


    # ═══════════════════════════════════════════════════════════════════════
    # PHASES 10-12: ASSESSMENTS + REPORTS + OUTPUT
    # → _phase10_12_reports_output()
    # ═══════════════════════════════════════════════════════════════════════
    # Sync all remaining locals into ctx for the final mega-phase
    ctx.update({
        "selected_model_id": selected_model_id, "selected_estimator": selected_estimator,
        "calibrator": calibrator, "selected_threshold": selected_threshold,
        "threshold_info": threshold_info,
        "X_train": X_train, "y_train": y_train, "X_valid": X_valid, "y_valid": y_valid,
        "X_test": X_test, "y_test": y_test, "has_valid": has_valid, "has_test": has_test,
        "train_proba": train_proba, "valid_proba": valid_proba, "test_proba": test_proba,
        "train_metrics": train_metrics, "valid_metrics": valid_metrics,
        "test_metrics": test_metrics, "train_cm": train_cm, "valid_cm": valid_cm,
        "test_cm": test_cm, "ci_n": ci_n, "all_metric_ci": all_metric_ci,
        "optimism_correction": optimism_correction, "learning_curve_report": learning_curve_report,
        "prevalence": prevalence, "prevalence_baseline": prevalence_baseline,
        "logistic_baseline": logistic_baseline,
        "baseline_logit_proba_test": baseline_logit_proba_test,
        "baseline_proba_test": baseline_proba_test, "baseline_fit_meta": baseline_fit_meta,
        "split_fingerprints": split_fingerprints,
        "model_selection_report": model_selection_report,
        "overfit_risk": overfit_risk, "overfit_gaps": overfit_gaps,
        "overfit_warnings": overfit_warnings, "overfit_recommendations": overfit_recommendations,
        "fallback_trace": fallback_trace, "original_model_id": original_model_id,
        "callback_activated": callback_activated,
        "candidate_rows": candidate_rows, "estimator_map": estimator_map,
        "candidate_space_meta": candidate_space_meta,
        "selected_candidate_row": selected_candidate_row, "selected_fit_meta": selected_fit_meta,
        "external_cohorts": external_cohorts, "beta": beta,
        "fast_diagnostic_mode": fast_diagnostic_mode,
        "imputation": imputation, "effective_class_weight": effective_class_weight,
        "selected_imbalance_strategy": selected_imbalance_strategy,
        "selection_data": selection_data,
        "threshold_selection_split": threshold_selection_split,
        "calibration_fit_split": calibration_fit_split, "calibration_method": calibration_method,
        "sensitivity_floor": sensitivity_floor, "npv_floor": npv_floor,
        "specificity_floor": specificity_floor, "ppv_floor": ppv_floor,
        "model_pool_config": model_pool_config,
        "imbalance_candidates": imbalance_candidates,
        "selected_imbalance_metric": selected_imbalance_metric,
        "strategy_probe_rows": strategy_probe_rows,
        "positive_count": positive_count, "negative_count": negative_count,
        "imbalance_ratio": imbalance_ratio,
        "stage0_features": stage0_features, "stage1_features": stage1_features,
        "selected_features": selected_features, "pre_encoding_features": pre_encoding_features,
        "stage1_report": stage1_report,
        "stability_frequency": stability_frequency,
        "group_selection_report": group_selection_report,
        "groups": groups, "forbidden_features": forbidden_features,
        "fe_mode_cfg": fe_mode_cfg, "low_mem": low_mem,
        "train_df": train_df, "valid_df": valid_df, "test_df": test_df,
        "calibration_y": calibration_y, "resolved_dev": resolved_dev,
        "policy": policy, "selection_trace": trace,
    })
    return _phase10_12_reports_output(ctx)


def _phase10_12_reports_output(ctx: Dict[str, Any]) -> int:
    """Phases 10-12: TRIPOD assessments, external validation, reports, file output.

    Pure output phase — no upstream mutations. Returns exit code 0.
    """
    args = ctx["args"]
    selected_estimator = ctx["selected_estimator"]
    calibrator = ctx["calibrator"]
    selected_threshold = ctx["selected_threshold"]
    threshold_info = ctx["threshold_info"]
    X_train, y_train = ctx["X_train"], ctx["y_train"]
    X_valid, y_valid = ctx["X_valid"], ctx["y_valid"]
    X_test, y_test = ctx["X_test"], ctx["y_test"]
    has_valid, has_test = ctx["has_valid"], ctx["has_test"]
    train_proba, valid_proba, test_proba = ctx["train_proba"], ctx["valid_proba"], ctx["test_proba"]
    train_metrics, valid_metrics, test_metrics = ctx["train_metrics"], ctx["valid_metrics"], ctx["test_metrics"]
    train_cm, valid_cm, test_cm = ctx["train_cm"], ctx["valid_cm"], ctx["test_cm"]
    ci_n, all_metric_ci = ctx["ci_n"], ctx["all_metric_ci"]
    optimism_correction = ctx["optimism_correction"]
    learning_curve_report = ctx["learning_curve_report"]
    prevalence_baseline = ctx["prevalence_baseline"]
    logistic_baseline = ctx["logistic_baseline"]
    baseline_logit_proba_test = ctx["baseline_logit_proba_test"]
    baseline_proba_test = ctx["baseline_proba_test"]
    baseline_fit_meta = ctx["baseline_fit_meta"]
    split_fingerprints = ctx["split_fingerprints"]
    model_selection_report = ctx["model_selection_report"]
    overfit_gaps = ctx["overfit_gaps"]; overfit_warnings = ctx["overfit_warnings"]
    overfit_risk = ctx["overfit_risk"]
    overfit_recommendations = ctx["overfit_recommendations"]
    fallback_trace = ctx["fallback_trace"]
    original_model_id = ctx["original_model_id"]
    callback_activated = ctx["callback_activated"]
    candidate_rows = ctx["candidate_rows"]
    estimator_map = ctx["estimator_map"]
    candidate_space_meta = ctx["candidate_space_meta"]
    selected_candidate_row = ctx["selected_candidate_row"]
    selected_fit_meta = ctx["selected_fit_meta"]
    selected_model_id = ctx["selected_model_id"]
    external_cohorts = ctx["external_cohorts"]
    beta = ctx["beta"]; fast_diagnostic_mode = ctx["fast_diagnostic_mode"]
    imputation = ctx["imputation"]; effective_class_weight = ctx["effective_class_weight"]
    selected_imbalance_strategy = ctx["selected_imbalance_strategy"]
    selection_data = ctx["selection_data"]
    threshold_selection_split = ctx["threshold_selection_split"]
    calibration_fit_split = ctx["calibration_fit_split"]
    calibration_method = ctx["calibration_method"]
    sensitivity_floor = ctx["sensitivity_floor"]; npv_floor = ctx["npv_floor"]
    specificity_floor = ctx["specificity_floor"]; ppv_floor = ctx["ppv_floor"]
    model_pool_config = ctx["model_pool_config"]
    imbalance_candidates = ctx["imbalance_candidates"]
    selected_imbalance_metric = ctx["selected_imbalance_metric"]
    strategy_probe_rows = ctx["strategy_probe_rows"]
    positive_count = ctx["positive_count"]; negative_count = ctx["negative_count"]
    imbalance_ratio = ctx["imbalance_ratio"]
    stage0_features = ctx["stage0_features"]; stage1_features = ctx["stage1_features"]
    selected_features = ctx["selected_features"]
    pre_encoding_features = ctx["pre_encoding_features"]
    stage1_report = ctx["stage1_report"]
    stability_frequency = ctx["stability_frequency"]
    group_selection_report = ctx["group_selection_report"]
    groups = ctx["groups"]; forbidden_features = ctx["forbidden_features"]
    fe_mode_cfg = ctx["fe_mode_cfg"]; low_mem = ctx["low_mem"]
    train_df, valid_df, test_df = ctx["train_df"], ctx["valid_df"], ctx["test_df"]
    calibration_y = ctx["calibration_y"]
    resolved_dev = ctx["resolved_dev"]
    policy = ctx["policy"]
    trace = ctx["selection_trace"]

    print("[STEP  9/12] TRIPOD+AI assessments...", file=sys.stderr, flush=True)
    epv_report = _sample_size_adequacy(
        n_events=int(np.sum(y_train)),
        n_features=int(X_train.shape[1]),
        n_total=int(X_train.shape[0]),
    )
    vif_report = _multicollinearity_check(X_train)
    _no_test_stub = {"skipped": True, "reason": "no_test_split"}
    if has_test:
        calibration_test = _calibration_assessment(y_test, test_proba)
        dca_test = _decision_curve_analysis(y_test, test_proba)
        nri_vs_prevalence = _net_reclassification_improvement(
            y_test, test_proba, baseline_proba_test, threshold=selected_threshold,
        )
        nri_vs_logistic = _net_reclassification_improvement(
            y_test, test_proba, baseline_logit_proba_test, threshold=selected_threshold,
        )
        if not fast_diagnostic_mode:
            perm_imp = _permutation_importance_report(
                estimator=selected_estimator,
                X_test=X_test,
                y_test=y_test,
                scoring="average_precision",
                n_repeats=10,
                seed=args.random_seed,
            )
        else:
            perm_imp = {"scoring": "average_precision", "top_features": [], "skipped": True}
        # Top-conference supplementary assessments
        test_pred = (test_proba >= selected_threshold).astype(int)
        baseline_logit_pred = (baseline_logit_proba_test >= selected_threshold).astype(int)
        delong_vs_logistic = _delong_test(y_test, test_proba, baseline_logit_proba_test)
        idi_vs_prevalence = _integrated_discrimination_improvement(
            y_test, test_proba, baseline_proba_test,
        )
        idi_vs_logistic = _integrated_discrimination_improvement(
            y_test, test_proba, baseline_logit_proba_test,
        )
        mcnemar_vs_logistic = _mcnemar_test(y_test, test_pred, baseline_logit_pred)
        pred_uncertainty = _prediction_uncertainty(test_proba)
    else:
        calibration_test = _no_test_stub
        dca_test = _no_test_stub
        nri_vs_prevalence = _no_test_stub
        nri_vs_logistic = _no_test_stub
        perm_imp = _no_test_stub
        delong_vs_logistic = _no_test_stub
        idi_vs_prevalence = _no_test_stub
        idi_vs_logistic = _no_test_stub
        mcnemar_vs_logistic = _no_test_stub
        pred_uncertainty = _no_test_stub
        test_pred = np.array([])
        baseline_logit_pred = np.array([])
    env_versions = _environment_versions()
    if has_test:
        subgroup_report = _subgroup_performance(
            y_true=y_test, proba=test_proba,
            threshold=selected_threshold, beta=beta,
            feature_df=X_test,
        )
        inference_bench = _inference_benchmark(selected_estimator, X_test)
        error_analysis_report = _error_analysis(y_test, test_proba, selected_threshold, X_test)
        if not fast_diagnostic_mode:
            ablation_report = _feature_ablation_study(
                estimator=selected_estimator,
                X_test=X_test, y_test=y_test,
                proba_full=test_proba,
                threshold=selected_threshold, beta=beta,
                seed=args.random_seed,
            )
        else:
            ablation_report = {"method": "leave_one_feature_out", "skipped": True, "top_features": []}
    else:
        subgroup_report = _no_test_stub
        inference_bench = _no_test_stub
        error_analysis_report = _no_test_stub
        ablation_report = _no_test_stub

    evaluation_report = {
        "schema_version": 2,
        "model_id": selected_model_id,
        "split": "test",
        "primary_metric": "pr_auc",
        "metrics": test_metrics,
        "split_metrics": {
            "train": {"metrics": train_metrics, "confusion_matrix": train_cm},
            "valid": {"metrics": valid_metrics, "confusion_matrix": valid_cm},
            "test": {"metrics": test_metrics, "confusion_matrix": test_cm},
        },
        "overfitting_analysis": {
            "gaps": overfit_gaps,
            "warnings": overfit_warnings,
            "overfit_detected": bool(overfit_warnings),
            "risk_level": overfit_risk,
            "recommendations": overfit_recommendations,
            "callback_activated": callback_activated,
            "original_model_id": original_model_id if callback_activated else None,
            "fallback_trace": fallback_trace if fallback_trace else None,
        },
        "calibration_assessment": _annotate_calibration_resampling_risk(
            calibration_test, selected_candidate_row, calibration_method,
        ),
        "bootstrap_optimism_correction": optimism_correction,
        "learning_curve": learning_curve_report,
        "decision_curve_analysis": dca_test,
        "sample_size_adequacy": epv_report,
        "multicollinearity": vif_report,
        "permutation_importance": perm_imp,
        "net_reclassification_improvement": {
            "vs_prevalence_baseline": nri_vs_prevalence,
            "vs_logistic_baseline": nri_vs_logistic,
        },
        "integrated_discrimination_improvement": {
            "vs_prevalence_baseline": idi_vs_prevalence,
            "vs_logistic_baseline": idi_vs_logistic,
        },
        "statistical_tests": {
            "delong_vs_logistic": delong_vs_logistic,
            "mcnemar_vs_logistic": mcnemar_vs_logistic,
        },
        "prediction_uncertainty": pred_uncertainty,
        "subgroup_performance": subgroup_report,
        "inference_benchmark": inference_bench,
        "error_analysis": error_analysis_report,
        "feature_ablation": ablation_report,
        "environment": env_versions,
        "threshold_selection": {
            "selection_split": threshold_selection_split,
            "strategy": "maximize_fbeta_under_floors",
            "beta": beta,
            "calibration_method": calibration_method,
            "calibration_fit_split": calibration_fit_split,
            "selected_threshold": selected_threshold,
            "constraints": {
                "sensitivity_min": sensitivity_floor,
                "npv_min": npv_floor,
                "specificity_min": specificity_floor,
                "ppv_min": ppv_floor,
            },
            "constraints_satisfied_selection_split": bool(threshold_info["constraints_satisfied_selection_split"]),
            "constraints_satisfied_guard_split": (
                bool(threshold_info["constraints_satisfied_guard_split"])
                if threshold_info["constraints_satisfied_guard_split"] is not None
                else None
            ),
            "constraints_satisfied_overall": bool(threshold_info["constraints_satisfied_overall"]),
            # Backward-compatible alias kept for older consumers.
            "constraints_satisfied": bool(threshold_info["constraints_satisfied_overall"]),
            "selected_metrics_on_selection_split": threshold_info["selected_metrics_on_valid"],
            "selected_confusion_on_selection_split": threshold_info["selected_confusion_on_valid"],
            "selected_metrics_on_valid": threshold_info["selected_metrics_on_valid"]
            if threshold_selection_split == "valid"
            else None,
            "selected_confusion_on_valid": threshold_info["selected_confusion_on_valid"]
            if threshold_selection_split == "valid"
            else None,
            "selected_metrics_on_guard_split": threshold_info["guard_metrics"]
            if threshold_selection_split == "cv_inner"
            else None,
        },
        "uncertainty": {
            "method": "bootstrap" if not fast_diagnostic_mode else "not_computed_fast_diagnostic",
            "n_resamples": ci_n,
            "metrics": (
                {
                    metric_name: {
                        "ci_95": [ci_vals["ci_lower"], ci_vals["ci_upper"]],
                        "ci_width": ci_vals["ci_width"],
                    }
                    for metric_name, ci_vals in all_metric_ci.items()
                }
                if not fast_diagnostic_mode and all_metric_ci
                else {
                    "pr_auc": {"ci_95": None, "ci_width": None},
                }
            ),
        },
        "baselines": {
            "prevalence_model": {"metrics": prevalence_baseline},
            "logistic_regression_baseline": {"metrics": logistic_baseline},
        },
        "feature_engineering": {
            "provenance": {
                "mode": str(args.feature_engineering_mode),
                "stage0_candidate_count": int(len(stage0_features)),
                "stage1_filtered_count": int(len(stage1_features)),
                "selected_feature_count": int(len(selected_features)),
            }
        },
        "distribution_summary": {},
        "ci_matrix_ref": None,
        "transport_ci_ref": None,
        "metadata": {
            "feature_count": len(selected_features),
            "features": selected_features,
            "beta": beta,
            "selection_data": selection_data,
            "threshold_selection_split": threshold_selection_split,
            "model_pool": {
                "requested": list(model_pool_config.get("requested_models", [])),
                "effective": list(model_pool_config.get("model_pool", [])),
                "required_models": list(model_pool_config.get("required_models", [])),
                "auto_added_required_models": list(model_pool_config.get("auto_added_required_models", [])),
                "candidate_count": int(len(candidate_rows)),
                "max_trials_per_family": int(model_pool_config.get("max_trials_per_family", 1)),
                "search_strategy": str(model_pool_config.get("search_strategy", "random_subsample")),
                "n_jobs": int(model_pool_config.get("n_jobs", -1)),
                "optional_backends": model_pool_config.get("optional_backends", {}),
                "unavailable_models": candidate_space_meta.get("unavailable_models", []),
            },
            "selected_model": {
                "model_id": selected_model_id,
                "base_model_id": (selected_candidate_row or {}).get("base_model_id"),
                "family": (selected_candidate_row or {}).get("family"),
                "hyperparameters": (selected_candidate_row or {}).get("hyperparameters"),
                "regularization_profile": (selected_candidate_row or {}).get("regularization_profile"),
            },
            "overfitting_controls": {
                "one_se_rule": True,
                "complexity_tie_breaker": "prefer_lower_complexity_rank",
                "selection_data": selection_data,
                "threshold_selection_split": threshold_selection_split,
                "threshold_guard_split": "valid" if threshold_selection_split == "cv_inner" else "cv_inner_oof_train",
                "regularization_enabled": True,
                "class_weight": effective_class_weight if effective_class_weight is not None else "none",
                "imbalance_strategy": selected_imbalance_strategy,
            },
            "calibration": {
                "method": calibration_method,
                "fit_split": calibration_fit_split,
                "enabled": calibration_method != "none",
                "fitted": calibrator is not None,
                "fit_rows": int(calibration_y.shape[0]),
                "details": calibrator if isinstance(calibrator, dict) else None,
            },
            "trainer_supported_selection_data": ["valid", "cv_inner"],
            "trainer_supported_threshold_selection_splits": ["valid", "cv_inner"],
            "trainer_supported_calibration_fit_splits": ["valid", "cv_inner"],
            "evaluation_model_fit_split": "train",
            "train_rows": int(X_train.shape[0]),
            "valid_rows": int(X_valid.shape[0]) if has_valid else 0,
            "test_rows": int(X_test.shape[0]) if has_test else 0,
            "data_fingerprints": split_fingerprints,
            "imputation": imputation,
            "imbalance": {
                "positive_count": positive_count,
                "negative_count": negative_count,
                "imbalance_ratio_majority_to_minority": (
                    float(imbalance_ratio) if math.isfinite(imbalance_ratio) else None
                ),
                "selected_strategy": selected_imbalance_strategy,
                "candidate_strategies": list(imbalance_candidates),
                "selection_metric": selected_imbalance_metric,
                "strategy_probe": strategy_probe_rows,
                "selected_fit": selected_fit_meta,
                "baseline_fit": baseline_fit_meta,
                "effective_class_weight": effective_class_weight if effective_class_weight is not None else "none",
                "class_weight_activation_threshold": 1.5,
            },
        },
    }

    def _patient_ids_or_fallback(df: pd.DataFrame, default_prefix: str) -> List[str]:
        """Extract patient IDs or generate sequential fallback IDs.

        Args:
            df: Source DataFrame.
            default_prefix: Prefix for fallback IDs (e.g., 'train').

        Returns:
            List of patient ID strings.
        """
        if args.patient_id_col in df.columns:
            return df[args.patient_id_col].astype(str).tolist()
        return [f"{default_prefix}_{i}" for i in range(int(df.shape[0]))]

    prediction_trace_frames: List[pd.DataFrame] = []
    prediction_trace_frames.append(
        build_prediction_trace_rows(
            scope="train",
            cohort_id="internal_train",
            cohort_type="",
            patient_ids=_patient_ids_or_fallback(train_df, "train"),
            y_true=y_train,
            y_score=train_proba,
            threshold=selected_threshold,
            model_id=selected_model_id,
        )
    )
    if has_valid:
        prediction_trace_frames.append(
            build_prediction_trace_rows(
                scope="valid",
                cohort_id="internal_valid",
                cohort_type="",
                patient_ids=_patient_ids_or_fallback(valid_df, "valid"),
                y_true=y_valid,
                y_score=valid_proba,
                threshold=selected_threshold,
                model_id=selected_model_id,
            )
        )
    if has_test:
        prediction_trace_frames.append(
            build_prediction_trace_rows(
                scope="test",
                cohort_id="internal_test",
                cohort_type="",
                patient_ids=_patient_ids_or_fallback(test_df, "test"),
                y_true=y_test,
                y_score=test_proba,
                threshold=selected_threshold,
                model_id=selected_model_id,
            )
        )

    external_validation_report: Optional[Dict[str, Any]] = None
    external_rows: List[Dict[str, Any]] = []
    external_score_cache: Dict[str, np.ndarray] = {}
    for cohort in external_cohorts:
        cohort_id = str(cohort["cohort_id"])
        cohort_type = str(cohort["cohort_type"])
        X_ext = cohort["X"]
        y_ext = cohort["y"]
        if len(np.unique(y_ext)) < 2:
            raise SystemExit(f"External cohort '{cohort_id}' must contain both classes for replay metrics.")
        proba_ext_raw = predict_proba_1(selected_estimator, X_ext)
        proba_ext = apply_probability_calibrator(calibrator, proba_ext_raw)
        external_score_cache[cohort_id] = np.asarray(proba_ext, dtype=float)
        metrics_ext, cm_ext = metric_panel(y_ext, proba_ext, selected_threshold, beta=beta)
        prediction_trace_frames.append(
            build_prediction_trace_rows(
                scope="external",
                cohort_id=cohort_id,
                cohort_type=cohort_type,
                patient_ids=cohort["patient_ids"],
                y_true=y_ext,
                y_score=proba_ext,
                threshold=selected_threshold,
                model_id=selected_model_id,
            )
        )
        pr_auc_drop = float(test_metrics["pr_auc"] - metrics_ext["pr_auc"]) if "pr_auc" in test_metrics else None
        f2_drop = float(test_metrics["f2_beta"] - metrics_ext["f2_beta"]) if "f2_beta" in test_metrics else None
        brier_increase = float(metrics_ext["brier"] - test_metrics["brier"]) if "brier" in test_metrics else None
        external_rows.append(
            {
                "cohort_id": cohort_id,
                "cohort_type": cohort_type,
                "row_count": int(cohort["row_count"]),
                "positive_count": int(np.sum(y_ext == 1)),
                "selected_threshold": float(selected_threshold),
                "metrics": metrics_ext,
                "confusion_matrix": cm_ext,
                "data_fingerprint": {
                    "path": str(cohort["data_path"]),
                    "sha256": sha256_file(Path(str(cohort["data_path"]))),
                    "row_count": int(cohort["row_count"]),
                },
                "transport_gap": {
                    "pr_auc_drop_from_internal_test": pr_auc_drop,
                    "f2_beta_drop_from_internal_test": f2_drop,
                    "brier_increase_from_internal_test": brier_increase,
                },
            }
        )


    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 11: EXTERNAL VALIDATION + OPTIONAL REPORTS
    # Inputs:  external_cohorts, selected_estimator, calibrator
    # Outputs: external_validation_report, distribution_report_payload,
    #          ci_matrix_report_payload, robustness_report,
    #          seed_sensitivity_report
    # ═══════════════════════════════════════════════════════════════════════


    if args.external_validation_report_out:
        external_validation_report = {
            "status": "pass",
            "model_id": selected_model_id,
            "primary_metric": "pr_auc",
            "internal_test_metrics": {
                "pr_auc": float(test_metrics["pr_auc"]),
                "f2_beta": float(test_metrics["f2_beta"]),
                "brier": float(test_metrics["brier"]),
            },
            "cohort_count": int(len(external_rows)),
            "cohorts": external_rows,
            "metadata": {
                "selected_threshold": float(selected_threshold),
                "beta": float(beta),
                "external_cohort_spec": str(Path(args.external_cohort_spec).expanduser().resolve())
                if args.external_cohort_spec
                else None,
            },
        }

    group_selection_frequency: Dict[str, float] = {}
    group_blocks = group_selection_report.get("groups") if isinstance(group_selection_report, dict) else None
    if isinstance(group_blocks, dict):
        for group_name, payload in group_blocks.items():
            if not isinstance(payload, dict):
                continue
            selected = payload.get("selected_features")
            if not isinstance(selected, list) or not selected:
                group_selection_frequency[group_name] = 0.0
                continue
            freq_values = [float(stability_frequency.get(str(f), 0.0)) for f in selected if isinstance(f, str)]
            group_selection_frequency[group_name] = float(np.mean(freq_values)) if freq_values else 0.0

    feature_engineering_report = {
        "status": "pass",
        "schema_version": "v4.0",
        "mode": str(args.feature_engineering_mode),
        "selection_scope": "cv_inner_train_only" if selection_data == "cv_inner" else "train_only",
        "data_scopes_used": ["train_only", "cv_inner_train_only"] if selection_data == "cv_inner" else ["train_only"],
        "feature_groups": groups,
        "forbidden_features": forbidden_features,
        "selected_features": selected_features,
        "stability": {
            "feature_selection_frequency": {k: float(v) for k, v in stability_frequency.items()},
            "group_selection_frequency": {k: float(v) for k, v in group_selection_frequency.items()},
            "repeats": int(fe_mode_cfg["stability_repeats"]),
        },
        "filters": stage1_report,
        "group_preselection": group_selection_report,
        "reproducibility": {
            "random_seed": int(args.random_seed),
            "cv": {"n_splits": int(args.cv_splits), "selection_data": selection_data},
            "selection_thresholds": {
                "max_missing_ratio": float(fe_mode_cfg["max_missing_ratio"]),
                "min_variance": float(fe_mode_cfg["min_variance"]),
                "group_keep_ratio": float(fe_mode_cfg["group_keep_ratio"]),
            },
            "retained_feature_list": selected_features,
            "selection_scope": "cv_inner_train_only" if selection_data == "cv_inner" else "train_only",
        },
    }

    compute_distribution_summary = bool(args.distribution_report_out) or not fast_diagnostic_mode
    distribution_report_payload: Optional[Dict[str, Any]] = None
    if compute_distribution_summary:
        external_frames = [{"cohort_id": c["cohort_id"], "frame": c["frame"]} for c in external_cohorts]
        distribution_report_payload = build_distribution_report(
            train_df=train_df,
            valid_df=valid_df,
            test_df=test_df,
            external_frames=external_frames,
            target_col=args.target_col,
            feature_cols=selected_features,
        )
        evaluation_report["distribution_summary"] = {
            "split_count": int(len(distribution_report_payload.get("distribution_matrix", []))),
            "schema_version": str(distribution_report_payload.get("schema_version", "v4.0")),
        }
    else:
        evaluation_report["distribution_summary"] = {
            "split_count": 0,
            "schema_version": "v4.0",
            "skipped_fast_diagnostic_mode": True,
        }

    compute_ci_matrix = bool(args.ci_matrix_report_out) or not fast_diagnostic_mode
    ci_matrix_report_payload: Optional[Dict[str, Any]] = None
    if compute_ci_matrix:
        ci_policy_block = policy.get("ci_policy") if isinstance(policy, dict) else None
        ci_resamples = (
            int(ci_policy_block.get("n_resamples"))
            if isinstance(ci_policy_block, dict) and isinstance(ci_policy_block.get("n_resamples"), int)
            else int(args.ci_bootstrap_resamples)
        )
        ci_resamples = max(200, int(ci_resamples))
        split_ci_payloads = {
            "train": {"y_true": y_train, "y_score": train_proba, "threshold": selected_threshold},
        }
        if has_valid:
            split_ci_payloads["valid"] = {"y_true": y_valid, "y_score": valid_proba, "threshold": selected_threshold}
        if has_test:
            split_ci_payloads["test"] = {"y_true": y_test, "y_score": test_proba, "threshold": selected_threshold}
        external_ci_payloads = [
            {
                "cohort_id": str(c["cohort_id"]),
                "cohort_type": str(c["cohort_type"]),
                "y_true": c["y"],
                "y_score": external_score_cache.get(
                    str(c["cohort_id"]),
                    apply_probability_calibrator(calibrator, predict_proba_1(selected_estimator, c["X"])),
                ),
                "threshold": selected_threshold,
            }
            for c in external_cohorts
        ]
        ci_matrix_report_payload = build_ci_matrix_report(
            split_payloads=split_ci_payloads,
            external_payloads=external_ci_payloads,
            beta=beta,
            n_resamples=ci_resamples,
            seed=int(args.random_seed),
        )

    robustness_report: Optional[Dict[str, Any]] = None
    if args.robustness_report_out:
        requested_time_slices = max(1, int(args.robustness_time_slices))
        # Avoid unstable micro-slices on small test sets; keep each slice ~15 rows when possible.
        max_reliable_slices = max(1, int(X_test.shape[0] // 15))
        time_slices = max(1, min(requested_time_slices, max_reliable_slices))
        group_count = max(1, int(args.robustness_group_count))
        time_slices_block: Dict[str, Any] = {"slice_field": "event_time", "n_slices": time_slices, "slices": []}
        patient_groups_block: Dict[str, Any] = {
            "group_method": f"sha256({args.patient_id_col})%{group_count}",
            "n_groups": group_count,
            "groups": [],
        }

        time_values = pd.to_datetime(test_df["event_time"], errors="coerce", utc=True) if "event_time" in test_df.columns else None
        if time_values is None or bool(time_values.isna().all()):
            import logging as _logging
            _logging.warning("No parseable event_time in test split; skipping temporal robustness slices (cross-sectional data).")
            time_values = None
        elif time_values is not None and bool(time_values.isna().any()):
            # Drop rows with unparseable timestamps, keep the rest
            import logging as _logging
            _n_bad = int(time_values.isna().sum())
            _logging.warning(f"Dropped {_n_bad} rows with unparseable event_time from temporal robustness analysis.")
            _valid_mask = time_values.notna()
            time_values = time_values[_valid_mask]
        if time_values is not None:
            sorted_index = np.asarray(np.argsort(time_values.to_numpy()), dtype=int)
            for slice_idx, idx_block in enumerate(np.array_split(sorted_index, time_slices), start=1):
                if idx_block.size == 0:
                    continue
                y_slice = y_test[idx_block]
                proba_slice = test_proba[idx_block]
                metrics_slice = metric_panel_robust(y_slice, proba_slice, selected_threshold, beta=beta)
                times_slice = time_values.iloc[idx_block]
                time_slices_block["slices"].append(
                    {
                        "slice_id": f"t{slice_idx}",
                        "n": int(idx_block.size),
                        "positive_count": int(np.sum(y_slice == 1)),
                        "start_time_utc": str(times_slice.min().isoformat()),
                        "end_time_utc": str(times_slice.max().isoformat()),
                        "metrics": metrics_slice,
                    }
                )
        else:
            time_slices_block["skipped"] = True
            time_slices_block["reason"] = "cross_sectional_no_event_time"

        if args.patient_id_col not in test_df.columns:
            raise SystemExit(f"robustness report requires {args.patient_id_col} column in test split.")
        patient_ids = test_df[args.patient_id_col].astype(str).tolist()
        group_indices: Dict[int, List[int]] = {k: [] for k in range(group_count)}
        for idx, pid in enumerate(patient_ids):
            group_indices[stable_group_index(pid, group_count)].append(idx)
        for group_idx in range(group_count):
            idx_list = group_indices[group_idx]
            if not idx_list:
                continue
            idx_arr = np.asarray(idx_list, dtype=int)
            y_group = y_test[idx_arr]
            proba_group = test_proba[idx_arr]
            metrics_group = metric_panel_robust(y_group, proba_group, selected_threshold, beta=beta)
            patient_groups_block["groups"].append(
                {
                    "group_id": f"g{group_idx}",
                    "n": int(idx_arr.size),
                    "positive_count": int(np.sum(y_group == 1)),
                    "metrics": metrics_group,
                }
            )

        def summarize_block(rows: List[Dict[str, Any]]) -> Dict[str, float]:
            """Summarize PR-AUC range and drop across robustness slices.

            Args:
                rows: List of per-slice/group result dicts with 'metrics' key.

            Returns:
                Dict with pr_auc_min, pr_auc_max, pr_auc_range,
                pr_auc_worst_drop_from_overall.

            Raises:
                SystemExit: If no valid pr_auc values found.
            """
            values = [float(r["metrics"]["pr_auc"]) for r in rows if isinstance(r, dict) and isinstance(r.get("metrics"), dict)]
            if not values:
                return {"skipped": True, "reason": "no_valid_slices", "n_rows": 0}
            minimum = float(min(values))
            maximum = float(max(values))
            return {
                "pr_auc_min": minimum,
                "pr_auc_max": maximum,
                "pr_auc_range": float(maximum - minimum),
                "pr_auc_worst_drop_from_overall": float(test_metrics["pr_auc"] - minimum),
                "n_rows": int(len(values)),
            }

        robustness_report = {
            "status": "pass",
            "primary_metric": "pr_auc",
            "model_id": selected_model_id,
            "overall_test_metrics": {
                "pr_auc": float(test_metrics["pr_auc"]),
                "f2_beta": float(test_metrics["f2_beta"]),
                "brier": float(test_metrics["brier"]),
            },
            "time_slices": time_slices_block,
            "patient_hash_groups": patient_groups_block,
            "summary": {
                "time_slices": summarize_block(time_slices_block["slices"]),
                "patient_hash_groups": summarize_block(patient_groups_block["groups"]),
            },
            "metadata": {
                "selected_threshold": float(selected_threshold),
                "beta": float(beta),
                "selection_data": selection_data,
                "threshold_selection_split": threshold_selection_split,
                "requested_time_slices": int(requested_time_slices),
                "effective_time_slices": int(time_slices),
                "group_count": int(group_count),
            },
        }

    seed_sensitivity_report: Optional[Dict[str, Any]] = None
    if args.seed_sensitivity_out:
        seed_list = parse_seed_list(args.seed_sensitivity_seeds, default_seed=args.random_seed)
        seed_results: List[Dict[str, Any]] = []
        for seed in seed_list:
            seed_candidates, _ = build_candidates(
                seed=int(seed),
                sampling_seed=int(args.random_seed),
                imputation_strategy=str(imputation["executed_strategy"]),
                class_weight=effective_class_weight,
                model_pool_config=model_pool_config,
                device=resolved_dev,
            )
            seed_estimator_map = {cand["model_id"]: cand["estimator"] for cand in seed_candidates}
            if selected_model_id not in seed_estimator_map:
                raise ValueError(f"Selected model_id not found in seeded candidate map: {selected_model_id}")
            seed_estimator = clone(seed_estimator_map[selected_model_id])
            # Bootstrap resample the training data so that deterministic
            # models (e.g. HistGradientBoosting with subsample=1.0) still
            # produce varied results across seeds.  This tests stability to
            # training-set perturbation, which is the true intent of seed
            # sensitivity analysis.
            rng = np.random.RandomState(int(seed))
            n_train = X_train.shape[0]
            boot_idx = rng.choice(n_train, size=n_train, replace=True)
            X_train_seed = X_train.iloc[boot_idx].reset_index(drop=True)
            y_train_seed = y_train[boot_idx]
            seed_estimator, _ = fit_estimator_with_imbalance(
                estimator=seed_estimator,
                X_train=X_train_seed,
                y_train=y_train_seed,
                strategy=selected_imbalance_strategy,
                seed=int(seed),
            )

            if threshold_selection_split == "valid" and has_valid:
                threshold_y_seed = y_valid
                threshold_proba_seed_raw = predict_proba_1(seed_estimator, X_valid)
            else:
                threshold_y_seed = y_train
                threshold_proba_seed_raw = cv_oof_proba(
                    estimator=seed_estimator,
                    X=X_train,
                    y=y_train,
                    n_splits=args.cv_splits,
                    seed=seed,
                    imbalance_strategy=selected_imbalance_strategy,
                )
            if calibration_fit_split == "valid" and has_valid:
                calibration_y_seed = y_valid
                calibration_proba_seed_raw = predict_proba_1(seed_estimator, X_valid)
            else:
                calibration_y_seed = y_train
                calibration_proba_seed_raw = cv_oof_proba(
                    estimator=seed_estimator,
                    X=X_train,
                    y=y_train,
                    n_splits=args.cv_splits,
                    seed=seed,
                    imbalance_strategy=selected_imbalance_strategy,
                )
            calibrator_seed = fit_probability_calibrator(
                y_true=calibration_y_seed,
                proba_raw=calibration_proba_seed_raw,
                method=calibration_method,
                seed=int(seed),
            )
            threshold_proba_seed = apply_probability_calibrator(calibrator_seed, threshold_proba_seed_raw)
            guard_y_seed: Optional[np.ndarray] = None
            guard_proba_seed: Optional[np.ndarray] = None
            if threshold_selection_split == "cv_inner" and has_valid:
                guard_y_seed = y_valid
                guard_proba_seed = apply_probability_calibrator(
                    calibrator_seed,
                    predict_proba_1(seed_estimator, X_valid),
                )
            threshold_info_seed = choose_threshold(
                y_valid=threshold_y_seed,
                proba_valid=threshold_proba_seed,
                beta=beta,
                sensitivity_floor=sensitivity_floor,
                npv_floor=npv_floor,
                specificity_floor=specificity_floor,
                ppv_floor=ppv_floor,
                guard_y=guard_y_seed,
                guard_proba=guard_proba_seed,
            )
            threshold_seed = float(threshold_info_seed["selected_threshold"])
            test_proba_seed_raw = predict_proba_1(seed_estimator, X_test)
            test_proba_seed = apply_probability_calibrator(calibrator_seed, test_proba_seed_raw)
            test_metrics_seed, _ = metric_panel(y_test, test_proba_seed, threshold_seed, beta=beta)
            seed_results.append(
                {
                    "seed": int(seed),
                    "selected_threshold": threshold_seed,
                    "constraints_satisfied_selection_split": bool(
                        threshold_info_seed["constraints_satisfied_selection_split"]
                    ),
                    "constraints_satisfied_guard_split": (
                        bool(threshold_info_seed["constraints_satisfied_guard_split"])
                        if threshold_info_seed["constraints_satisfied_guard_split"] is not None
                        else None
                    ),
                    "constraints_satisfied_overall": bool(threshold_info_seed["constraints_satisfied_overall"]),
                    "constraints_satisfied": bool(threshold_info_seed["constraints_satisfied_overall"]),
                    "test_metrics": {
                        "pr_auc": float(test_metrics_seed["pr_auc"]),
                        "f2_beta": float(test_metrics_seed["f2_beta"]),
                        "brier": float(test_metrics_seed["brier"]),
                    },
                }
            )

        pr_auc_values = [float(row["test_metrics"]["pr_auc"]) for row in seed_results]
        f2_values = [float(row["test_metrics"]["f2_beta"]) for row in seed_results]
        brier_values = [float(row["test_metrics"]["brier"]) for row in seed_results]
        seed_sensitivity_report = {
            "status": "pass",
            "primary_metric": "pr_auc",
            "model_id": selected_model_id,
            "selection_data": selection_data,
            "threshold_selection_split": threshold_selection_split,
            "n_seed_runs": len(seed_results),
            "seeds": [int(x) for x in seed_list],
            "per_seed_results": seed_results,
            "summary": {
                "pr_auc": summarize_seed_metric(pr_auc_values),
                "f2_beta": summarize_seed_metric(f2_values),
                "brier": summarize_seed_metric(brier_values),
            },
            "metadata": {
                "beta": beta,
                "sensitivity_floor": sensitivity_floor,
                "npv_floor": npv_floor,
                "specificity_floor": specificity_floor,
                "ppv_floor": ppv_floor,
                "train_rows": int(X_train.shape[0]),
                "valid_rows": int(X_valid.shape[0]) if has_valid else 0,
                "test_rows": int(X_test.shape[0]) if has_test else 0,
            },
        }

    if low_mem:
        del train_df, valid_df, test_df
        gc.collect()


    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 12: FILE OUTPUT + MANIFEST
    # Inputs:  All reports, selected_estimator, calibrator
    # Outputs: JSON/CSV/pkl files to disk
    # ═══════════════════════════════════════════════════════════════════════


    print("[STEP 12/12] Writing output files...", file=sys.stderr, flush=True)
    model_selection_out = Path(args.model_selection_report_out).expanduser().resolve()
    evaluation_out = Path(args.evaluation_report_out).expanduser().resolve()

    prediction_trace_out: Optional[Path] = None
    if args.prediction_trace_out:
        prediction_trace_out = Path(args.prediction_trace_out).expanduser().resolve()
        ensure_parent(prediction_trace_out)
        prediction_trace_df = pd.concat(prediction_trace_frames, axis=0, ignore_index=True)
        # Write with deterministic gzip (mtime=0) so SHA-256 is reproducible.
        # pandas.to_csv with .gz extension uses gzip with mtime=current time,
        # making the compressed file non-deterministic across runs.
        if str(prediction_trace_out).endswith(".gz"):
            import gzip as _gzip_mod
            csv_bytes = prediction_trace_df.to_csv(index=False).encode("utf-8")
            with open(prediction_trace_out, "wb") as _f_out:
                with _gzip_mod.GzipFile(fileobj=_f_out, mode="wb", mtime=0) as _gz:
                    _gz.write(csv_bytes)
        else:
            prediction_trace_df.to_csv(prediction_trace_out, index=False)

    external_validation_out: Optional[Path] = None
    if args.external_validation_report_out and external_validation_report is not None:
        external_validation_out = Path(args.external_validation_report_out).expanduser().resolve()
        write_json(external_validation_out, external_validation_report)

    feature_engineering_out: Optional[Path] = None
    if args.feature_engineering_report_out:
        feature_engineering_out = Path(args.feature_engineering_report_out).expanduser().resolve()
        write_json(feature_engineering_out, feature_engineering_report)

    distribution_out: Optional[Path] = None
    if args.distribution_report_out and distribution_report_payload is not None:
        distribution_out = Path(args.distribution_report_out).expanduser().resolve()
        write_json(distribution_out, distribution_report_payload)

    ci_matrix_out: Optional[Path] = None
    if args.ci_matrix_report_out and ci_matrix_report_payload is not None:
        ci_matrix_out = Path(args.ci_matrix_report_out).expanduser().resolve()
        write_json(ci_matrix_out, ci_matrix_report_payload)

    evaluation_report["ci_matrix_ref"] = str(ci_matrix_out) if ci_matrix_out else None
    evaluation_report["transport_ci_ref"] = "transport_drop_ci" if ci_matrix_out else None
    if isinstance(evaluation_report.get("feature_engineering"), dict):
        provenance = evaluation_report["feature_engineering"].get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
            evaluation_report["feature_engineering"]["provenance"] = provenance
        provenance["feature_group_spec"] = str(Path(args.feature_group_spec).expanduser().resolve()) if args.feature_group_spec else None
        provenance["feature_engineering_report"] = str(feature_engineering_out) if feature_engineering_out else None
        provenance["selected_features"] = selected_features

    evaluation_metadata = evaluation_report.get("metadata")
    if not isinstance(evaluation_metadata, dict):
        evaluation_metadata = {}
        evaluation_report["metadata"] = evaluation_metadata
    evaluation_metadata["prediction_trace_sha256"] = (
        sha256_file(prediction_trace_out) if prediction_trace_out and prediction_trace_out.exists() else None
    )
    evaluation_metadata["external_validation_report_sha256"] = (
        sha256_file(external_validation_out)
        if external_validation_out and external_validation_out.exists()
        else None
    )
    evaluation_metadata["external_cohort_count"] = int(len(external_rows))
    # Include categorical analysis summary in evaluation report
    if stage1_report and "categorical_analysis" in stage1_report:
        cat_analysis = stage1_report["categorical_analysis"]
        evaluation_metadata["categorical_analysis"] = {
            "categorical_count": cat_analysis.get("categorical_count", 0),
            "coercion_warnings": cat_analysis.get("coercion_warnings", []),
        }
    # Include VIF and nonlinearity summaries
    if stage1_report and "vif_analysis" in stage1_report:
        va = stage1_report["vif_analysis"]
        evaluation_metadata["vif_analysis"] = {
            "max_vif": va.get("max_vif"),
            "critical_features": va.get("critical_features", []),
            "warn_features": va.get("warn_features", []),
        }
    if stage1_report and "nonlinearity_analysis" in stage1_report:
        na = stage1_report["nonlinearity_analysis"]
        evaluation_metadata["nonlinearity_analysis"] = {
            "n_nonlinear": na.get("n_nonlinear", 0),
            "nonlinear_features": na.get("nonlinear_features", []),
        }

    evaluation_metadata["feature_engineering_report_sha256"] = (
        sha256_file(feature_engineering_out)
        if feature_engineering_out and feature_engineering_out.exists()
        else None
    )
    evaluation_metadata["distribution_report_sha256"] = (
        sha256_file(distribution_out)
        if distribution_out and distribution_out.exists()
        else None
    )
    evaluation_metadata["ci_matrix_report_sha256"] = (
        sha256_file(ci_matrix_out) if ci_matrix_out and ci_matrix_out.exists() else None
    )
    threshold_block = evaluation_report.get("threshold_selection")
    threshold_fit_split = (
        str(threshold_block.get("calibration_fit_split")).strip().lower()
        if isinstance(threshold_block, dict) and threshold_block.get("calibration_fit_split") is not None
        else ""
    )
    calibration_meta = evaluation_metadata.get("calibration")
    metadata_fit_split = (
        str(calibration_meta.get("fit_split")).strip().lower()
        if isinstance(calibration_meta, dict) and calibration_meta.get("fit_split") is not None
        else ""
    )
    if threshold_fit_split and metadata_fit_split and threshold_fit_split != metadata_fit_split:
        raise SystemExit(
            "calibration_fit_split_mismatch: threshold_selection.calibration_fit_split "
            "must equal metadata.calibration.fit_split"
        )

    write_json(model_selection_out, model_selection_report)
    write_json(evaluation_out, evaluation_report)
    if args.robustness_report_out and robustness_report is not None:
        robustness_out = Path(args.robustness_report_out).expanduser().resolve()
        write_json(robustness_out, robustness_report)
    if args.seed_sensitivity_out and seed_sensitivity_report is not None:
        seed_sensitivity_out = Path(args.seed_sensitivity_out).expanduser().resolve()
        write_json(seed_sensitivity_out, seed_sensitivity_report)

    if args.model_out:
        model_out = Path(args.model_out).expanduser().resolve()
        ensure_parent(model_out)
        model_bundle = {
            "estimator": selected_estimator,
            "calibrator": calibrator,
            "threshold": selected_threshold,
            "calibration_method": calibration_method,
            "model_id": selected_model_id,
            "features": selected_features,
            "schema_version": 2,
        }
        joblib.dump(model_bundle, model_out)
        # Security: HMAC-sign the model artifact
        try:
            from _security import sign_model_artifact, ArtifactManifest
            sign_model_artifact(model_out)
        except ImportError:
            pass  # _security module not available — skip signing
        except Exception as _sign_exc:  # noqa: BLE001
            import logging as _logging
            _logging.warning(f"Model signing failed for {model_out}: {_sign_exc}")

    if getattr(args, "model_pool_out", None):
        pool_out = Path(args.model_pool_out).expanduser().resolve()
        ensure_parent(pool_out)
        # Build best-per-family pool for multi-model SHAP interpretability
        family_best: Dict[str, Dict[str, Any]] = {}
        for row in candidate_rows:
            family = str(row.get("family", row.get("base_model_id", "")))
            pr_auc = float(row["selection_metrics"]["pr_auc"]["mean"])
            if family not in family_best or pr_auc > family_best[family]["pr_auc"]:
                family_best[family] = {
                    "model_id": row["model_id"],
                    "pr_auc": pr_auc,
                    "hyperparameters": row.get("hyperparameters", {}),
                }
        pool_families: Dict[str, Any] = {}
        for family, info in family_best.items():
            mid = info["model_id"]
            if mid not in estimator_map:
                continue
            est = clone(estimator_map[mid])
            est, _ = fit_estimator_with_imbalance(
                estimator=est,
                X_train=X_train,
                y_train=y_train,
                strategy=selected_imbalance_strategy,
                seed=int(args.random_seed),
            )
            pool_families[family] = {
                "model_id": mid,
                "estimator": est,
                "hyperparameters": info["hyperparameters"],
                "cv_pr_auc_mean": info["pr_auc"],
            }
        model_pool = {
            "schema_version": 1,
            "families": pool_families,
            "features": selected_features,
            "original_features": pre_encoding_features,
            "selected_model_id": selected_model_id,
        }
        joblib.dump(model_pool, pool_out)
        try:
            from _security import sign_model_artifact
            sign_model_artifact(pool_out)
        except ImportError:
            pass
        except Exception as _sign_exc:  # noqa: BLE001
            import logging as _logging
            _logging.warning(f"Model pool signing failed for {pool_out}: {_sign_exc}")
        print(f"ModelPool: {pool_out} ({len(pool_families)} families)")

    if args.permutation_null_out:
        rng = np.random.default_rng(args.random_seed)
        null_path = Path(args.permutation_null_out).expanduser().resolve()
        ensure_parent(null_path)
        permutation_resamples = int(args.permutation_resamples)
        if fast_diagnostic_mode:
            permutation_resamples = min(permutation_resamples, 50)
        with null_path.open("w", encoding="utf-8") as fh:
            for _ in range(max(0, int(permutation_resamples))):
                y_perm = rng.permutation(y_test)
                score = float(average_precision_score(y_perm, test_proba))
                fh.write(f"{score:.10f}\n")

    print(f"SelectedModel: {selected_model_id}")
    print(f"PrimaryMetric(pr_auc,test): {test_metrics['pr_auc']:.6f}")
    print(f"ModelSelectionReport: {model_selection_out}")
    print(f"EvaluationReport: {evaluation_out}")
    if prediction_trace_out is not None:
        print(f"PredictionTrace: {prediction_trace_out}")
    if external_validation_out is not None:
        print(f"ExternalValidationReport: {external_validation_out}")
    if args.robustness_report_out and robustness_report is not None:
        print(f"RobustnessReport: {Path(args.robustness_report_out).expanduser().resolve()}")
    if args.seed_sensitivity_out and seed_sensitivity_report is not None:
        print(f"SeedSensitivityReport: {Path(args.seed_sensitivity_out).expanduser().resolve()}")
    if feature_engineering_out is not None:
        print(f"FeatureEngineeringReport: {feature_engineering_out}")
    if distribution_out is not None:
        print(f"DistributionReport: {distribution_out}")
    if ci_matrix_out is not None:
        print(f"CIMatrixReport: {ci_matrix_out}")

    # Security: create evidence integrity manifest
    try:
        from _security import ArtifactManifest
        manifest = ArtifactManifest()
        for epath in [evaluation_out, model_selection_out, ci_matrix_out,
                      feature_engineering_out, distribution_out,
                      external_validation_out, prediction_trace_out]:
            if epath is not None and Path(epath).exists():
                manifest.add_file(Path(epath))
        manifest_out = evaluation_out.parent / ".manifest.json"
        manifest.save(manifest_out)
    except Exception:  # noqa: BLE001
        pass  # Manifest is advisory; do not block pipeline

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
