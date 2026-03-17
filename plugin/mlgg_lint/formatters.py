"""Output formatters: text, JSON, SARIF."""

from __future__ import annotations

import json
import sys
from typing import List

from mlgg_lint.models import Diagnostic, Severity

# ANSI colors
_RST = "\033[0m"
_RED = "\033[91m"
_YEL = "\033[93m"
_CYA = "\033[96m"
_DIM = "\033[2m"
_BOLD = "\033[1m"

_SEV_COLOR = {
    Severity.ERROR: _RED,
    Severity.WARNING: _YEL,
    Severity.INFO: _CYA,
}


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def format_text(diagnostics: List[Diagnostic], color: bool | None = None) -> str:
    """Human-readable one-line-per-diagnostic output."""
    if color is None:
        color = _is_tty()
    lines: list[str] = []
    for d in diagnostics:
        loc = d.location
        sev = str(d.severity).upper()
        if color:
            c = _SEV_COLOR.get(d.severity, "")
            line = (
                f"{_DIM}{loc.file}:{loc.line}:{loc.col}{_RST} "
                f"{c}{_BOLD}{sev}{_RST} "
                f"{_DIM}{d.rule_id}{_RST} "
                f"{d.message}"
            )
        else:
            line = f"{loc.file}:{loc.line}:{loc.col} {sev} {d.rule_id} {d.message}"
        lines.append(line)

    if not diagnostics:
        summary = "No issues found."
        if color:
            summary = f"\033[92m{summary}{_RST}"
        lines.append(summary)
    else:
        errs = sum(1 for d in diagnostics if d.severity == Severity.ERROR)
        warns = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
        infos = sum(1 for d in diagnostics if d.severity == Severity.INFO)
        parts = []
        if errs:
            parts.append(f"{errs} error(s)")
        if warns:
            parts.append(f"{warns} warning(s)")
        if infos:
            parts.append(f"{infos} info(s)")
        summary = f"\nFound {', '.join(parts)}."
        if color:
            summary = f"\n{_BOLD}{summary}{_RST}"
        lines.append(summary)

    return "\n".join(lines)


def format_json(diagnostics: List[Diagnostic]) -> str:
    """Machine-readable JSON array output for agent consumption."""
    return json.dumps(
        [d.to_dict() for d in diagnostics],
        indent=2,
        ensure_ascii=False,
    )


def format_sarif(diagnostics: List[Diagnostic]) -> str:
    """SARIF 2.1.0 output for IDE integration."""
    from mlgg_lint.rules import get_all_rules

    all_rules = get_all_rules()

    rules_sarif = []
    rule_index: dict[str, int] = {}
    for idx, (rid, cls) in enumerate(sorted(all_rules.items())):
        rule_index[rid] = idx
        rules_sarif.append({
            "id": cls.id,
            "name": cls.name,
            "shortDescription": {"text": cls.description[:200]},
            "fullDescription": {"text": cls.description},
            "helpUri": f"https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard#rules",
            "defaultConfiguration": {
                "level": _sarif_level(cls.severity),
            },
            "properties": {
                "tags": list(cls.tags),
            },
        })

    results = []
    for d in diagnostics:
        loc = d.location
        result = {
            "ruleId": d.rule_id,
            "ruleIndex": rule_index.get(d.rule_id, 0),
            "level": _sarif_level(d.severity),
            "message": {"text": d.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": loc.file},
                        "region": {
                            "startLine": loc.line,
                            "startColumn": loc.col + 1,  # SARIF is 1-based
                        },
                    }
                }
            ],
        }
        if loc.end_line is not None:
            result["locations"][0]["physicalLocation"]["region"]["endLine"] = loc.end_line
            result["locations"][0]["physicalLocation"]["region"]["endColumn"] = (loc.end_col or 0) + 1
        if d.remediation:
            result["fixes"] = [
                {"description": {"text": d.remediation}}
            ]
        results.append(result)

    sarif = {
        "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "mlgg-lint",
                        "version": "0.1.0",
                        "informationUri": "https://github.com/Furinaaa-Cancan/medical-ml-leakage-guard",
                        "rules": rules_sarif,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2, ensure_ascii=False)


def _sarif_level(severity: Severity) -> str:
    return {
        Severity.ERROR: "error",
        Severity.WARNING: "warning",
        Severity.INFO: "note",
    }.get(severity, "note")
