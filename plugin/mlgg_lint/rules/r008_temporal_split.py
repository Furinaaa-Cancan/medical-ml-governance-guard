"""R008: train_test_split with shuffle on time-series/temporal data.

Revision (B9): require STRONG evidence of a forecasting / sequence task
before firing. Mere presence of a temporal keyword (e.g. ``admission`` in
``case_admission_id``) is not sufficient — many static patient-level
classification tasks include such columns without being time-ordered.
"""

from __future__ import annotations

import ast
from typing import Optional

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SPLIT_CALLS = {"train_test_split", "sklearn.model_selection.train_test_split"}

# ── Strong-signal vocabulary ─────────────────────────────────────────────────

# Function/attribute names indicating an actual datetime conversion.
_TO_DATETIME_NAMES = {"to_datetime", "DatetimeIndex", "Timestamp"}

# Keyword-style hints for sequence / forecasting model arguments.
_SEQUENCE_KW_NAMES = {
    "time_column", "time_idx", "time_index",
    "seq_len", "sequence_length", "seq_length",
    "lookback", "look_back", "look_ahead",
    "horizon", "forecast_horizon", "n_lags", "n_steps",
    "window", "window_size",
}

# Sequence model class names (LSTM/GRU/transformer time-series style).
_SEQUENCE_MODEL_NAMES = {
    "LSTM", "GRU", "SimpleRNN", "ConvLSTM2D", "Bidirectional",
    "TimeDistributed", "Conv1D",
}


def _has_pd_to_datetime_call(tree: ast.AST) -> bool:
    """Detect ``pd.to_datetime(...)`` / ``pandas.to_datetime(...)`` calls
    or assignment of a DatetimeIndex to ``df.index``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _TO_DATETIME_NAMES:
                return True
            if isinstance(func, ast.Name) and func.id in _TO_DATETIME_NAMES:
                return True
    return False


def _has_datetime_index_assignment(tree: ast.AST) -> bool:
    """Detect ``df.index = pd.to_datetime(...)`` or ``df.index = ...DatetimeIndex(...)``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "index":
                    val = node.value
                    if isinstance(val, ast.Call):
                        f = val.func
                        if (
                            isinstance(f, ast.Attribute) and f.attr in _TO_DATETIME_NAMES
                        ) or (
                            isinstance(f, ast.Name) and f.id in _TO_DATETIME_NAMES
                        ):
                            return True
    return False


def _has_sequence_kwarg_or_name(tree: ast.AST) -> bool:
    """Detect explicit forecasting/sequence keyword arguments or local
    variables named like sequence-model parameters (``seq_len``, ``horizon``)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in _SEQUENCE_KW_NAMES:
            return True
        if isinstance(node, ast.Name) and node.id in _SEQUENCE_KW_NAMES:
            return True
    return False


def _has_sequence_model_call(tree: ast.AST) -> bool:
    """Detect instantiation of a recurrent / temporal-aware layer (LSTM/GRU/..)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name: Optional[str] = None
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                name = f.attr
            if name in _SEQUENCE_MODEL_NAMES:
                return True
    return False


def _expr_indicates_3d(val: ast.AST) -> bool:
    """Recursively check if *val* expression evaluates to a 3D+ array.

    Recognises:
      - ``arr[:, :, :, ...]`` — Subscript with Tuple of ≥3 Slice elements.
      - ``arr.reshape((n, T, F))`` / ``arr.reshape(n, T, F)`` with ≥3 dims.
      - Method chains preserving shape (``.astype(...)``, ``.copy()``).
    """
    if val is None:
        return False
    # Subscript ``arr[:, :, :, ...]``
    if isinstance(val, ast.Subscript):
        slc = val.slice
        if isinstance(slc, ast.Tuple) and sum(
            1 for e in slc.elts if isinstance(e, ast.Slice)
        ) >= 3:
            return True
        # Recurse: arr[:, :, :, -1].astype(float) etc.
        return False
    # Method calls that preserve shape — peel back receiver
    if isinstance(val, ast.Call):
        if isinstance(val.func, ast.Attribute):
            attr = val.func.attr
            if attr == "reshape":
                shape_args = list(val.args)
                if len(shape_args) == 1 and isinstance(
                    shape_args[0], (ast.Tuple, ast.List)
                ):
                    shape_args = list(shape_args[0].elts)
                if len(shape_args) >= 3:
                    return True
                return False
            # Shape-preserving methods: continue down receiver
            if attr in {
                "astype", "copy", "squeeze", "transpose", "swapaxes",
                "moveaxis", "rollaxis", "view",
            }:
                return _expr_indicates_3d(val.func.value)
    return False


def _split_arg_is_3d(call: ast.Call, tree: ast.AST) -> bool:
    """Heuristic: the first positional arg of *call* is shaped (n, T, F)
    or higher (LSTM-style input).

    Signals tracked:
      - The arg variable was assigned from a 3-deep slice ``arr[:, :, :, ...]``.
      - The arg variable was assigned from a ``.reshape((n, T, F))`` with ≥3 dims.
      - The variable is reassigned from itself (e.g. ``test_X_np = test_X_np[:, :, :, -1]``).
    """
    if not call.args:
        return False
    arg = call.args[0]
    if not isinstance(arg, ast.Name):
        return False
    target_var = arg.id

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = []
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                names.append(tgt.id)
        if target_var not in names:
            continue
        if _expr_indicates_3d(node.value):
            return True
    return False


def _evidence_of_temporal_task(scope: ast.AST, split_call: ast.Call) -> bool:
    """Strong evidence that the data being split is part of a forecasting or
    sequence-aware task. See module docstring for rationale.

    Returns True if any of the following hold:
      - ``df.index = pd.to_datetime(...)`` / DatetimeIndex assignment.
      - ``pd.to_datetime(...)`` call somewhere AND the result feeds X
        (we approximate this by presence of any to_datetime call together
         with no obvious patient-level deduplication).
      - Explicit sequence keyword (``time_column``, ``seq_len``, ``lookback``,
        ``horizon``, ``window``...).
      - The first positional argument to ``train_test_split`` is shaped 3D
        (``(n, timesteps, features)`` for LSTM-style input).
      - A recurrent / temporal model layer (LSTM/GRU/Conv1D) is instantiated.
    """
    if _has_datetime_index_assignment(scope):
        return True
    if _has_sequence_kwarg_or_name(scope):
        return True
    if _split_arg_is_3d(split_call, scope):
        return True
    if _has_sequence_model_call(scope):
        return True
    # ``pd.to_datetime`` alone is a weaker signal — only count it if we
    # have no explicit deduplication patterns. For safety we still treat it
    # as evidence (project explicitly converts a column to datetime).
    if _has_pd_to_datetime_call(scope):
        return True
    return False


@register
class TemporalSplit(BaseRule):
    id = "R008"
    name = "temporal-split-shuffle"
    severity = Severity.WARNING
    description = (
        "train_test_split used with shuffle=True (default) on data that appears "
        "to belong to a forecasting or sequence task. Shuffled splits on "
        "time-series data cause future information to leak into training."
    )
    remediation = (
        "For temporal medical data, use time-based splits: sort by date and split "
        "chronologically, or use TimeSeriesSplit/GroupShuffleSplit with temporal ordering."
    )
    tags = ("leakage", "temporal")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tree: Optional[ast.AST] = None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        # If shuffle=False is explicit, we're already safe.
        for kw in node.keywords:
            if kw.arg == "shuffle":
                if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    self.generic_visit(node)
                    return

        scope = self._tree if self._tree is not None else node
        if not _evidence_of_temporal_task(scope, node):
            self.generic_visit(node)
            return

        self.report(
            node,
            "train_test_split with shuffle enabled (default) on temporal data. "
            "This allows future observations to leak into training. "
            "Use chronological splitting instead.",
        )
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self._diagnostics = []
        self._tree = tree
        self.visit(tree)
        return self._diagnostics
