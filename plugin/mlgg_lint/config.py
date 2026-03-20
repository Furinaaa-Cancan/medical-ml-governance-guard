"""Configuration loading from .mlgg-lint.toml files."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

CONFIG_FILENAME = ".mlgg-lint.toml"
_MAX_CONFIG_BYTES = 1 * 1024 * 1024  # 1 MB


@dataclass
class LintConfig:
    """Resolved configuration for a lint run."""

    severity_threshold: str = "info"
    disabled_rules: Set[str] = field(default_factory=set)
    rule_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> LintConfig:
        section = raw.get("mlgg-lint", {})
        if not isinstance(section, dict):
            return cls()
        cfg = cls()
        cfg.severity_threshold = str(section.get("severity-threshold", "info")).lower()
        rules = section.get("rules", {})
        if not isinstance(rules, dict):  # F11: guard against malformed structure
            return cfg
        for rule_id, value in rules.items():
            rid = str(rule_id).upper()
            if value is False:
                cfg.disabled_rules.add(rid)
            elif isinstance(value, dict):
                cfg.rule_overrides[rid] = value
        return cfg

    def is_rule_enabled(self, rule_id: str) -> bool:
        return rule_id.upper() not in self.disabled_rules


def find_config(start: Path) -> Optional[Path]:
    """Walk upward from *start* looking for .mlgg-lint.toml."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config(path: Optional[Path] = None, start: Optional[Path] = None) -> LintConfig:
    """Load and parse config.  Returns defaults when no file is found."""
    if path is None and start is not None:
        path = find_config(start)
    if path is None:
        return LintConfig()
    if tomllib is None:
        return LintConfig()
    # F10: Guard against oversized config files
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            return LintConfig()
    except OSError:
        return LintConfig()
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return LintConfig()
    return LintConfig.from_dict(raw)
