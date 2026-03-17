"""Rule registry — auto-discovers rule classes from r*.py modules."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Type

from mlgg_lint.rules.base import BaseRule

_REGISTRY: Dict[str, Type[BaseRule]] = {}


def _discover() -> None:
    """Import all r*.py modules in this package to trigger registration."""
    import mlgg_lint.rules as pkg

    for info in pkgutil.iter_modules(pkg.__path__, prefix=pkg.__name__ + "."):
        if info.name.rsplit(".", 1)[-1].startswith("r"):
            importlib.import_module(info.name)


def register(cls: Type[BaseRule]) -> Type[BaseRule]:
    """Decorator to register a rule class."""
    _REGISTRY[cls.id] = cls
    return cls


def get_all_rules() -> Dict[str, Type[BaseRule]]:
    """Return all registered rule classes, keyed by rule ID."""
    if not _REGISTRY:
        _discover()
    return dict(_REGISTRY)


def get_enabled_rules(disabled: set[str] | None = None) -> List[Type[BaseRule]]:
    """Return rule classes that are not in the disabled set."""
    all_rules = get_all_rules()
    disabled = disabled or set()
    return [cls for rid, cls in sorted(all_rules.items()) if rid not in disabled]
