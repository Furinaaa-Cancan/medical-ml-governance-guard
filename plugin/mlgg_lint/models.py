"""Data models for diagnostics, locations, and rule metadata."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class Severity(enum.Enum):
    """Diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Location:
    """Source code location for a diagnostic."""

    file: str
    line: int
    col: int
    end_line: Optional[int] = None
    end_col: Optional[int] = None

    def __str__(self) -> str:
        pos = f"{self.file}:{self.line}:{self.col}"
        if self.end_line is not None:
            pos += f"-{self.end_line}:{self.end_col}"
        return pos


@dataclass
class Diagnostic:
    """A single finding from a rule check."""

    rule_id: str
    rule_name: str
    severity: Severity
    message: str
    location: Location
    remediation: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": str(self.severity),
            "message": self.message,
            "location": {
                "file": self.location.file,
                "line": self.location.line,
                "col": self.location.col,
            },
        }
        if self.location.end_line is not None:
            d["location"]["end_line"] = self.location.end_line
            d["location"]["end_col"] = self.location.end_col
        if self.remediation:
            d["remediation"] = self.remediation
        if self.details:
            d["details"] = self.details
        return d
