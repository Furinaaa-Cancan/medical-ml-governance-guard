"""R004: train_test_split without groups= for patient/subject data.

Revision (B9): suppress when data is already deduplicated to one row per
patient upstream of the split — common pattern in retrospective cohort
studies where a patient-level outcome is computed before splitting.
"""

from __future__ import annotations

import ast
import re
from typing import Optional, Set

from mlgg_lint.ast_utils import call_name, matches_any
from mlgg_lint.models import Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule

_SPLIT_CALLS = {"train_test_split", "sklearn.model_selection.train_test_split"}

_PATIENT_HINTS = {
    "patient", "subject", "person", "individual", "participant",
    "pid", "patient_id", "subject_id", "person_id",
    # Medical record / encounter identifiers
    "encounter", "encounter_id", "admission", "admission_id",
    "visit", "visit_id", "episode", "episode_id",
    "mrn", "medical_record", "case_id",
}

# Group-key column names accepted as evidence of per-group deduplication.
_GROUP_KEY_HINTS = {
    "patient", "patient_id", "pid", "subject", "subject_id",
    "person", "person_id", "individual", "individual_id",
    "participant", "participant_id",
    "mrn", "medical_record", "case_id",
}

# Method names that, when called on a DataFrame with a patient-like subset,
# collapse the data to one row per group.
_DEDUP_METHODS = {"drop_duplicates"}
_GROUPBY_REDUCERS = {
    "first", "last", "head", "nth", "agg", "aggregate", "sum", "mean", "median",
    "min", "max", "count", "size", "any", "all",
}

# Function-call name hints that indicate per-patient outcome reduction.
# These are project/library helpers like ``link_patient_id_to_outcome`` —
# matched by simple regex against the call's terminal attribute.
_DEDUP_FN_PATTERNS = (
    re.compile(r"(?i)link[_]?patient[_]?id[_]?to[_]?outcome"),
    re.compile(r"(?i)link[_]?(patient|subject|pid)[_]?(to|with)[_]?outcome"),
    re.compile(r"(?i)reduce[_]?(to|by|per)[_]?(patient|subject|pid)"),
    re.compile(r"(?i)collapse[_]?(to|by|per)[_]?(patient|subject|pid)"),
    re.compile(r"(?i)one[_]?row[_]?per[_]?(patient|subject|pid)"),
    re.compile(r"(?i)per[_]?(patient|subject|pid)[_]?outcome"),
    re.compile(r"(?i)patient[_]?level[_]?outcome"),
    re.compile(r"(?i)unique[_]?(patient|subject|pid)"),
)

# String/comment-style markers stored as ast.Constant strings (docstrings, etc).
_DEDUP_TEXT_RE = re.compile(
    r"(?i)("
    r"per[\- ]patient"
    r"|one row per patient"
    r"|deduplicated"
    r"|unique patient"
    r"|single outcome"
    r"|avoid duplicates"
    r"|reduce.{0,40}(patient|subject|pid)"
    r"|to[_\- ]outcome"
    r"|link[_\- ]patient[_\- ]id"
    r"|patient[_\- ]level"
    r")"
)


def _has_patient_identifiers(tree: ast.Module) -> bool:
    """Check if the AST contains patient/subject-like variable names or
    string literals — using precise Name/Constant node checks rather than
    ast.dump() which would match inside comments and unrelated strings."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id.lower() in _PATIENT_HINTS:
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Use word-boundary matching to avoid false positives like
            # "impatient" matching "patient" or "revisiting" matching "visit"
            words = set(node.value.lower().replace("-", "_").split("_"))
            # Also split on whitespace for natural language strings
            for w in node.value.lower().split():
                words.add(w.strip(".,;:!?'\"()"))
            if words & _PATIENT_HINTS:
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr.lower() in _PATIENT_HINTS:
                return True
    return False


def _string_literals_match_group_hint(node: ast.AST) -> bool:
    """Return True if any string constant inside *node* names a patient-like
    column (used to detect ``df.groupby('patient_id')`` etc)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            tokens = sub.value.lower().replace("-", "_").split("_")
            if any(tok in _GROUP_KEY_HINTS for tok in tokens):
                return True
    return False


def _call_arg_or_kw(call: ast.Call, kw_name: str) -> Optional[ast.AST]:
    """Return the first arg or named keyword (e.g. ``subset``) of *call*."""
    for kw in call.keywords:
        if kw.arg == kw_name:
            return kw.value
    return call.args[0] if call.args else None


def _is_drop_duplicates_call(call: ast.Call) -> bool:
    """``df.drop_duplicates(...)`` with patient-like ``subset=`` (or no subset)."""
    if not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr not in _DEDUP_METHODS:
        return False
    # Look for subset argument
    for kw in call.keywords:
        if kw.arg == "subset":
            return _string_literals_match_group_hint(kw.value)
    # Positional subset
    if call.args:
        if _string_literals_match_group_hint(call.args[0]):
            return True
    # No-arg drop_duplicates() drops on all columns — conservatively accept
    # because for a per-patient cohort with no duplicate patients across rows,
    # it has the same effect.
    return not call.args and not any(kw.arg == "subset" for kw in call.keywords)


def _is_groupby_reduce_chain(call: ast.Call) -> bool:
    """Detect ``df.groupby('patient_id').first()`` and similar reducers."""
    if not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr not in _GROUPBY_REDUCERS:
        return False
    # Walk back to find a ``.groupby(...)`` somewhere in the receiver chain
    receiver = call.func.value
    while isinstance(receiver, (ast.Call, ast.Attribute)):
        if isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute):
            if receiver.func.attr == "groupby":
                # check the groupby arg names a patient-like column
                if receiver.args and _string_literals_match_group_hint(receiver.args[0]):
                    return True
                # keyword 'by='
                for kw in receiver.keywords:
                    if kw.arg == "by" and _string_literals_match_group_hint(kw.value):
                        return True
                return False
            receiver = receiver.func.value
        elif isinstance(receiver, ast.Attribute):
            receiver = receiver.value
        else:
            break
    return False


def _is_dedup_named_function_call(call: ast.Call) -> bool:
    """Return True if call's terminal name matches a per-patient dedup helper."""
    name: Optional[str] = None
    if isinstance(call.func, ast.Name):
        name = call.func.id
    elif isinstance(call.func, ast.Attribute):
        name = call.func.attr
    if name is None:
        return False
    return any(p.search(name) for p in _DEDUP_FN_PATTERNS)


def _has_dedup_text_marker(tree: ast.AST) -> bool:
    """Check string constants (docstrings included) for per-patient markers."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _DEDUP_TEXT_RE.search(node.value):
                return True
    return False


def _collect_dedup_vars(scope: ast.AST) -> Set[str]:
    """Variables assigned from a deduplication operation in *scope*.

    Tracks names bound to results of:
      - ``df.drop_duplicates([patient_id])``
      - ``df.groupby('patient_id').first()`` (and other reducers)
      - calls whose function name matches a dedup pattern
        (``link_patient_id_to_outcome`` etc).
    Also propagates one level via simple ``new = old`` assignments when
    ``old`` is already in the set.
    """
    dedup_vars: Set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            val = node.value
            is_dedup_source = False
            if isinstance(val, ast.Call):
                if (
                    _is_drop_duplicates_call(val)
                    or _is_groupby_reduce_chain(val)
                    or _is_dedup_named_function_call(val)
                ):
                    is_dedup_source = True
            elif isinstance(val, ast.Name) and val.id in dedup_vars:
                is_dedup_source = True
            elif isinstance(val, ast.Attribute):
                # ``new = old.tolist()`` — propagate if root name is dedup
                root = val
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in dedup_vars:
                    is_dedup_source = True
            if is_dedup_source:
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        dedup_vars.add(tgt.id)
                    elif isinstance(tgt, (ast.Tuple, ast.List)):
                        for elt in tgt.elts:
                            if isinstance(elt, ast.Name):
                                dedup_vars.add(elt.id)
    return dedup_vars


def _split_arg_root_name(call: ast.Call) -> Optional[str]:
    """Return the root variable name of the first positional argument of a
    ``train_test_split`` call. Walks through method calls (``.tolist()``)
    and subscripts (``df['col']``) to find the original Name."""
    if not call.args:
        return None
    arg = call.args[0]
    while True:
        if isinstance(arg, ast.Name):
            return arg.id
        if isinstance(arg, ast.Attribute):
            arg = arg.value
            continue
        if isinstance(arg, ast.Subscript):
            arg = arg.value
            continue
        if isinstance(arg, ast.Call):
            # ``df.something(...)`` — peel back the receiver
            if isinstance(arg.func, ast.Attribute):
                arg = arg.func.value
                continue
            return None
        return None


def _data_is_deduplicated_per_group(scope: ast.AST, df_var: Optional[str]) -> bool:
    """Return True if there is upstream evidence in *scope* that the data
    fed to ``train_test_split`` has been collapsed to one row per patient.

    Signals (any one suffices):
      a. A drop_duplicates / groupby-reducer / dedup-helper call appears.
      b. The variable feeding into the split was itself bound from such a call.
      c. A docstring or string literal in *scope* matches a per-patient marker
         (e.g. "Reduce every patient to a single outcome").
    """
    # Fast text marker check (cheap, runs first)
    if _has_dedup_text_marker(scope):
        return True

    # Any explicit dedup operation present in scope?
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            if (
                _is_drop_duplicates_call(node)
                or _is_groupby_reduce_chain(node)
                or _is_dedup_named_function_call(node)
            ):
                return True

    # Variable taint: was df_var bound from a dedup source?
    if df_var:
        dedup_vars = _collect_dedup_vars(scope)
        if df_var in dedup_vars:
            return True
    return False


@register
class SplitWithoutGroup(BaseRule):
    id = "R004"
    name = "split-without-group"
    severity = Severity.WARNING
    description = (
        "train_test_split called without groups= parameter in a context that "
        "appears to involve patient/subject data. Without grouping, the same "
        "patient may appear in both train and test, causing data leakage."
    )
    remediation = (
        "Use GroupShuffleSplit or pass groups= to train_test_split to ensure "
        "patient-level disjoint splits."
    )
    tags = ("leakage", "split")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._has_patient_context = False
        self._tree: Optional[ast.AST] = None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        fqn = call_name(node, self.import_map)
        if not fqn or not matches_any(fqn, _SPLIT_CALLS):
            self.generic_visit(node)
            return

        if not self._has_patient_context:
            self.generic_visit(node)
            return

        has_groups = any(kw.arg == "groups" for kw in node.keywords)
        if has_groups:
            self.generic_visit(node)
            return

        # Negative gate: suppress if upstream data has already been
        # deduplicated to one row per patient (B9 revision).
        df_var = _split_arg_root_name(node)
        scope = self._tree if self._tree is not None else node
        if _data_is_deduplicated_per_group(scope, df_var):
            self.generic_visit(node)
            return

        self.report(
            node,
            "train_test_split without `groups=` parameter in patient/subject "
            "context. Patients may appear in both train and test splits.",
        )
        self.generic_visit(node)

    def check(self, tree: ast.Module) -> list:
        self._diagnostics = []
        self._tree = tree
        self._has_patient_context = _has_patient_identifiers(tree)
        self.visit(tree)
        return self._diagnostics
