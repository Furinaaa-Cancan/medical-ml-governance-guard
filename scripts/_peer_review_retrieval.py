"""Peer Review Knowledge Base retrieval for MLGG RAG.

Provides functions to query the peer-review-kb.json knowledge base
by dimension, gate, tag, category, domain, and severity. Used by
the /mlgg skill and gate scripts to cite real NC reviewer concerns.

This module is READ-ONLY — it never modifies the knowledge base.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_KB_PATH = Path(__file__).resolve().parent.parent / "references" / "peer_reviews" / "peer-review-kb.json"
_STATS_PATH = Path(__file__).resolve().parent.parent / "references" / "peer_reviews" / "peer-review-kb-stats.json"

_kb_cache: Optional[Dict[str, Any]] = None


def _load_kb(kb_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and cache the peer review knowledge base."""
    global _kb_cache
    if _kb_cache is not None and kb_path is None:
        return _kb_cache
    path = kb_path or _KB_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if kb_path is None:
        _kb_cache = data
    return data


def _sort_by_severity(concerns: List[Dict]) -> List[Dict]:
    """Sort concerns by severity: CRITICAL > HIGH > MEDIUM > LOW."""
    return sorted(concerns, key=lambda c: _SEVERITY_ORDER.get(c.get("severity", "LOW"), 9))


def _collect_concerns(
    kb: Dict[str, Any],
    filter_fn,
    severity: Optional[str] = None,
    limit: int = 5,
) -> List[Dict]:
    """Collect concerns from all papers matching a filter function."""
    results = []
    for entry in kb.get("entries", []):
        for concern in entry.get("reviewer_concerns", []):
            if not filter_fn(concern, entry):
                continue
            if severity and concern.get("severity") != severity:
                continue
            enriched = {
                **concern,
                "_paper_id": entry.get("id"),
                "_paper_doi": entry.get("paper_doi"),
                "_paper_title": entry.get("paper_title"),
                "_year": entry.get("year"),
                "_domain": entry.get("domain"),
            }
            results.append(enriched)
    results = _sort_by_severity(results)
    return results[:limit] if limit else results


# ─── Public retrieval functions ───────────────────────────────


def retrieve_by_dimension(
    dim: int,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve peer review concerns for a given MLGG dimension (1-12).

    Args:
        dim: MLGG dimension number (1=Data Integrity, 5=Statistical Validity, etc.)
        severity: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)
        limit: Maximum results to return
        kb_path: Optional custom KB path for testing

    Returns:
        List of enriched concern dicts sorted by severity
    """
    kb = _load_kb(kb_path)
    return _collect_concerns(
        kb,
        lambda c, _: c.get("mlgg_dimension") == dim,
        severity=severity,
        limit=limit,
    )


def retrieve_by_gate(
    gate_name: str,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns linked to a specific MLGG gate.

    Args:
        gate_name: Gate script name (e.g., 'leakage_gate', 'calibration_dca_gate')
        severity: Filter by severity
        limit: Maximum results

    Returns:
        List of enriched concern dicts
    """
    kb = _load_kb(kb_path)
    return _collect_concerns(
        kb,
        lambda c, _: gate_name in c.get("mlgg_gates", []),
        severity=severity,
        limit=limit,
    )


def retrieve_by_tags(
    tags: List[str],
    match_any: bool = True,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns matching given tags.

    Args:
        tags: List of tags to match
        match_any: If True, match ANY tag; if False, match ALL tags
        severity: Filter by severity
        limit: Maximum results

    Returns:
        List of enriched concern dicts
    """
    tag_set = set(tags)
    kb = _load_kb(kb_path)

    def _match(c, _):
        c_tags = set(c.get("tags", []))
        return bool(c_tags & tag_set) if match_any else tag_set.issubset(c_tags)

    return _collect_concerns(kb, _match, severity=severity, limit=limit)


def retrieve_by_category(
    category: str,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns by category (e.g., 'evaluation_metrics', 'data_leakage')."""
    kb = _load_kb(kb_path)
    return _collect_concerns(
        kb,
        lambda c, _: c.get("category") == category,
        severity=severity,
        limit=limit,
    )


def retrieve_by_domain(
    domain: str,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns from papers in a specific clinical domain."""
    kb = _load_kb(kb_path)
    return _collect_concerns(
        kb,
        lambda _, entry: entry.get("domain") == domain,
        severity=severity,
        limit=limit,
    )


def get_stats_summary(kb_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the pre-computed stats summary."""
    path = kb_path or _STATS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def count_concerns_with_tag(tag: str, kb_path: Optional[Path] = None) -> int:
    """Count how many concerns have a specific tag."""
    kb = _load_kb(kb_path)
    count = 0
    for entry in kb.get("entries", []):
        for concern in entry.get("reviewer_concerns", []):
            if tag in concern.get("tags", []):
                count += 1
    return count


# ─── Formatting ───────────────────────────────────────────────


def format_peer_context(concerns: List[Dict], max_display: int = 3) -> str:
    """Format peer review concerns for display in gate output or agent response.

    Args:
        concerns: List of enriched concern dicts from retrieve_* functions
        max_display: Maximum concerns to display

    Returns:
        Formatted string with peer review citations
    """
    if not concerns:
        return "  No matching peer review examples found."

    lines = []
    for i, c in enumerate(concerns[:max_display]):
        cid = c.get("concern_id", "?")
        paper = c.get("_paper_id", "?")
        year = c.get("_year", "?")
        sev = c.get("severity", "?")
        text = c.get("concern_text", "")[:120]
        fix = c.get("author_response", "")[:80]
        tags = ", ".join(c.get("tags", [])[:3])

        lines.append(f"  [{sev}] {cid} ({paper}, NC {year})")
        lines.append(f"    Concern: {text}...")
        if fix:
            lines.append(f"    Fix: {fix}...")
        lines.append(f"    Tags: {tags}")
        if i < max_display - 1:
            lines.append("")

    total = len(concerns)
    if total > max_display:
        lines.append(f"  ... and {total - max_display} more similar concerns")

    return "\n".join(lines)


def format_gate_peer_context(gate_name: str, kb_path: Optional[Path] = None) -> str:
    """Generate peer review context string for a specific gate failure.

    Args:
        gate_name: Name of the failed gate

    Returns:
        Formatted string suitable for appending to gate summary output
    """
    concerns = retrieve_by_gate(gate_name, limit=10, kb_path=kb_path)
    if not concerns:
        return ""

    header = (
        f"\n📚 Peer Review Context ({len(concerns)} similar issues in NC papers):\n"
    )
    body = format_peer_context(concerns, max_display=3)
    return header + body
