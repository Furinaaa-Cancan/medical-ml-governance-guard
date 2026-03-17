"""Shared AST helpers — import resolution, call matching, variable taint tracking."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ── Import alias resolution ──────────────────────────────────────────────────

@dataclass
class ImportMap:
    """Tracks import aliases so ``import sklearn.preprocessing as pp``
    allows recognising ``pp.StandardScaler`` as ``sklearn.preprocessing.StandardScaler``.
    """

    # local_name -> fully qualified name
    aliases: Dict[str, str] = field(default_factory=dict)
    # "from X import Y" — local Y -> fully qualified X.Y
    from_imports: Dict[str, str] = field(default_factory=dict)

    def resolve(self, name: str) -> str:
        """Resolve a dotted name like ``pp.StandardScaler`` to its full path."""
        parts = name.split(".", 1)
        head = parts[0]
        # from X import Y — head IS the local name
        if head in self.from_imports:
            base = self.from_imports[head]
            if len(parts) > 1:
                return f"{base}.{parts[1]}"
            return base
        # import X as alias
        if head in self.aliases:
            base = self.aliases[head]
            if len(parts) > 1:
                return f"{base}.{parts[1]}"
            return base
        return name


def build_import_map(tree: ast.Module) -> ImportMap:
    """Scan top-level imports and build an alias map."""
    im = ImportMap()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                im.aliases[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                fqn = f"{module}.{alias.name}" if module else alias.name
                im.from_imports[local] = fqn
    return im


# ── Call matching ─────────────────────────────────────────────────────────────

def call_name(node: ast.Call, im: ImportMap) -> Optional[str]:
    """Return the fully-qualified name of a Call node, or None."""
    raw = _attr_chain(node.func)
    if raw is None:
        return None
    return im.resolve(raw)


def _attr_chain(node: ast.expr) -> Optional[str]:
    """``a.b.c`` -> ``"a.b.c"``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def matches_any(fqn: str, patterns: Set[str]) -> bool:
    """Check if *fqn* ends with any of the given patterns.

    ``matches_any("sklearn.preprocessing.StandardScaler", {"StandardScaler"})``
    → True.
    """
    for pat in patterns:
        if fqn == pat or fqn.endswith(f".{pat}"):
            return True
    return False


# ── Method call matching on objects ───────────────────────────────────────────

def is_method_call(node: ast.Call, method_name: str) -> Optional[str]:
    """If *node* is ``obj.method_name(...)``, return ``obj`` name. Else None."""
    if isinstance(node.func, ast.Attribute) and node.func.attr == method_name:
        obj = _attr_chain(node.func.value)
        return obj
    return None


# ── Variable taint tracking ──────────────────────────────────────────────────

TRAIN_HINTS = {"train", "tr", "training"}
TEST_HINTS = {"test", "te", "testing", "holdout"}
VALID_HINTS = {"valid", "val", "validation", "dev"}


def classify_var_name(name: str) -> Optional[str]:
    """Heuristic classification based on variable name substrings.

    Returns ``"train"``, ``"test"``, ``"valid"``, or ``None``.
    """
    lower = name.lower()
    for hint in TEST_HINTS:
        if hint in lower:
            return "test"
    for hint in VALID_HINTS:
        if hint in lower:
            return "valid"
    for hint in TRAIN_HINTS:
        if hint in lower:
            return "train"
    return None


@dataclass
class TaintTracker:
    """Simple single-assignment taint tracker.

    Records which variables hold train/test/valid data based on
    ``train_test_split`` return unpacking and variable name heuristics.
    """

    # var_name -> "train" | "test" | "valid" | "full"
    taints: Dict[str, str] = field(default_factory=dict)
    # line number where the first split call occurs
    split_line: Optional[int] = None

    def record_split(self, targets: List[str], line: int) -> None:
        """Record a train_test_split unpacking."""
        if self.split_line is None:
            self.split_line = line
        for name in targets:
            taint = classify_var_name(name) or "unknown"
            self.taints[name] = taint

    def record_assignment(self, name: str, taint: Optional[str] = None) -> None:
        if taint:
            self.taints[name] = taint
        elif name not in self.taints:
            cls = classify_var_name(name)
            if cls:
                self.taints[name] = cls

    def get_taint(self, name: str) -> Optional[str]:
        return self.taints.get(name)

    def is_test_or_valid(self, name: str) -> bool:
        t = self.get_taint(name)
        return t in ("test", "valid")

    def has_split_occurred(self, line: int) -> bool:
        return self.split_line is not None and line > self.split_line


def extract_tuple_targets(node: ast.AST) -> List[str]:
    """Extract variable names from a tuple/list unpacking target."""
    names: List[str] = []
    if isinstance(node, ast.Tuple) or isinstance(node, ast.List):
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
                names.append(elt.value.id)
    elif isinstance(node, ast.Name):
        names.append(node.id)
    return names


def get_call_first_arg_name(node: ast.Call) -> Optional[str]:
    """Return the name of the first positional argument if it's a simple Name."""
    if node.args:
        return _attr_chain(node.args[0])
    return None
