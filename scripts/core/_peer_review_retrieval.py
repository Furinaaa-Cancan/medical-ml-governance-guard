"""Peer Review Knowledge Base retrieval for MLGG RAG.

Provides functions to query the peer-review-kb.json knowledge base
by dimension, gate, tag, category, domain, severity, paper, and text.
Used by the /mlgg skill and gate scripts to cite real NC reviewer concerns.

This module is READ-ONLY — it never modifies the knowledge base.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_GENERIC_FIXES = frozenset({"Addressed in revision.", "Addressed in revision", ""})

_STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "are",
    "was", "were", "been", "being", "have", "has", "had", "not",
    "but", "can", "will", "would", "should", "could", "may",
    "also", "than", "then", "when", "where", "which", "what",
    "how", "why", "who", "its", "their", "our", "your", "any",
    "all", "each", "every", "some", "more", "most", "other",
    "only", "such", "into", "over", "after", "before", "between",
    "about", "using", "used", "based", "does",
})

# Synonym map: common problem descriptions → actual KB tags
TAG_SYNONYMS: Dict[str, List[str]] = {
    "fit_before_split": ["future_information_leakage", "target_leakage", "temporal_leakage", "data_leakage_via_imputation"],
    "preprocessing_leakage": ["future_information_leakage", "data_leakage_via_imputation", "normal_imputation_bias", "informative_missingness"],
    "data_leakage": ["future_information_leakage", "target_leakage", "temporal_leakage", "bidirectional_rnn_leakage", "data_leakage_via_correlated_phenotypes"],
    "no_calibration": ["missing_calibration", "calibration_plot_missing", "calibration_in_supplement", "calibration_in_supplement_only"],
    "no_ci": ["missing_ci", "no_bootstrap_ci", "suspiciously_narrow_ci"],
    "overfitting": ["overfitting", "overfitting_concern", "overfitting_risk", "overparameterized", "epv_violation", "extreme_class_imbalance"],
    "no_code": ["no_code_availability", "reproducibility", "code_as_pdf", "broken_github_link", "weights_not_shared"],
    "no_validation": ["no_external_validation", "internal_split_only", "same_cohort_validation", "single_center"],
    "missing_comparison": ["missing_baseline_comparison", "comparison_with_existing", "missing_competitor_comparison", "missing_benchmark_methods"],
    "sample_too_small": ["small_sample", "tiny_sample", "tiny_sample_size", "underpowered", "no_power_calculation"],
    "smote_leakage": ["class_imbalance", "extreme_class_imbalance", "smote_needed", "temporal_imbalance"],
    "class_imbalance": ["class_imbalance", "extreme_class_imbalance", "smote_needed", "temporal_imbalance", "low_incidence_suspicious"],
    "no_shap": ["shap_interpretation_shallow", "shap_presentation", "explainability_missing", "explainability_insufficient", "feature_importance", "shap_requested"],
    "no_dca": ["missing_dca", "dca_explanation_needed", "dca_assumptions_violated", "cancer_specific_dca"],
    "no_bootstrap": ["missing_ci", "no_bootstrap_ci", "suspiciously_narrow_ci", "single_split"],
    "temporal_leak": ["temporal_leakage", "temporal_split_missing", "future_data_used", "future_information_leakage", "bidirectional_rnn_leakage"],
    "label_leakage": ["target_leakage", "definition_variable", "feature_is_outcome_proxy", "circular_prediction", "outcome_defined_by_features"],
    "no_reproducibility": ["no_code_availability", "reproducibility", "irreproducible_methods", "code_as_pdf", "weights_not_shared", "broken_github_link"],
    "confounding": ["confounders", "missing_confounder", "confounders_undisclosed", "confounding_by_gender", "confounding_unadjusted", "covariate_adjustment_one_size_fits_all"],
    "overstatement": ["overstatement", "overclaimed", "overclaimed_novelty", "overclaimed_improvement", "overclaimed_public_health", "title_overstatement"],
}

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


def clear_cache() -> None:
    """Clear the in-memory KB cache. Call after KB regeneration."""
    global _kb_cache
    _kb_cache = None


def _has_detailed_fix(concern: Dict) -> bool:
    """Check if a concern has a detailed (non-generic) author response."""
    return concern.get("author_response", "") not in _GENERIC_FIXES


def _sort_by_severity(concerns: List[Dict]) -> List[Dict]:
    """Sort concerns by: severity first, then prefer detailed fixes."""
    return sorted(concerns, key=lambda c: (
        _SEVERITY_ORDER.get(c.get("severity", "LOW"), 9),
        0 if _has_detailed_fix(c) else 1,
    ))


def _enrich_concern(concern: Dict, entry: Dict) -> Dict:
    """Add paper-level metadata to a concern dict."""
    return {
        **concern,
        "_paper_id": entry.get("id"),
        "_paper_doi": entry.get("paper_doi"),
        "_paper_title": entry.get("paper_title"),
        "_year": entry.get("year"),
        "_domain": entry.get("domain"),
    }


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
            results.append(_enrich_concern(concern, entry))
    results = _sort_by_severity(results)
    return results[:limit]


# ─── Tag expansion ────────────────────────────────────────────


def _expand_tags(tags: List[str]) -> Set[str]:
    """Expand tags using synonym map for fuzzy matching."""
    expanded = set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        expanded.add(tag)
        if tag in TAG_SYNONYMS:
            expanded.update(TAG_SYNONYMS[tag])
    return expanded


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
    expand_synonyms: bool = True,
) -> List[Dict]:
    """Retrieve concerns matching given tags (with synonym expansion).

    Args:
        tags: List of tags to match
        match_any: If True, match ANY tag; if False, match ALL tags
        severity: Filter by severity
        limit: Maximum results
        kb_path: Optional custom KB path
        expand_synonyms: If True, expand tags using TAG_SYNONYMS map

    Returns:
        List of enriched concern dicts
    """
    tag_set = _expand_tags(tags) if expand_synonyms else set(t for t in tags if isinstance(t, str))
    if not tag_set:
        return []
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


def retrieve_by_paper(
    paper_id: str,
    severity: Optional[str] = None,
    limit: int = 50,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve all concerns from a specific paper.

    Args:
        paper_id: Paper ID (e.g., 'PR-001') or DOI fragment (e.g., 's41467-024-46663-4')

    Returns:
        List of enriched concern dicts from that paper
    """
    kb = _load_kb(kb_path)
    pid = paper_id.lower()
    return _collect_concerns(
        kb,
        lambda _, entry: entry.get("id", "").lower() == pid
                         or pid in entry.get("paper_doi", "").lower(),
        severity=severity,
        limit=limit,
    )


def retrieve_combined(
    dimension: Optional[int] = None,
    gate: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    domain: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns matching ALL specified filters (AND logic).

    Example: retrieve_combined(dimension=5, domain="oncology") returns
    only concerns that are BOTH dimension 5 AND from oncology papers.

    Args:
        dimension: MLGG dimension (1-12)
        gate: Gate name
        tags: List of tags (any match, with synonym expansion)
        category: Concern category
        domain: Clinical domain
        severity: Severity filter
        limit: Maximum results

    Returns:
        List of enriched concern dicts matching all specified filters
    """
    tag_set = _expand_tags(tags) if tags else None
    kb = _load_kb(kb_path)

    def _match(c, entry):
        if dimension is not None and c.get("mlgg_dimension") != dimension:
            return False
        if gate and gate not in c.get("mlgg_gates", []):
            return False
        if tag_set and not bool(set(c.get("tags", [])) & tag_set):
            return False
        if category and c.get("category") != category:
            return False
        if domain and entry.get("domain") != domain:
            return False
        return True

    return _collect_concerns(kb, _match, severity=severity, limit=limit)


def retrieve_by_text(
    query: str,
    severity: Optional[str] = None,
    limit: int = 5,
    kb_path: Optional[Path] = None,
    min_match_ratio: float = 0.4,
) -> List[Dict]:
    """Retrieve concerns by text matching on concern_text and tags.

    Searches for query terms in concern_text, author_response, tags,
    and category fields. Requires a minimum fraction of query terms
    to match to avoid spurious results from single-word overlaps.

    Args:
        query: Natural language description of the problem
        severity: Filter by severity
        limit: Maximum results
        kb_path: Optional custom KB path
        min_match_ratio: Minimum fraction of query terms that must match (0-1).

    Returns:
        List of enriched concern dicts ranked by match quality
    """
    terms = [t.lower().strip() for t in query.split()
             if len(t) > 2 and t.lower().strip() not in _STOPWORDS]

    if not terms:
        return []

    min_hits = max(1, int(len(terms) * min_match_ratio))
    kb = _load_kb(kb_path)

    scored = []
    for entry in kb.get("entries", []):
        for concern in entry.get("reviewer_concerns", []):
            if severity and concern.get("severity") != severity:
                continue

            text_parts = concern.get("concern_text", "") + " " + concern.get("author_response", "")
            tag_parts = " ".join(concern.get("tags", [])) + " " + concern.get("category", "")
            searchable = (text_parts + " " + tag_parts + " " + tag_parts).lower()

            hits = sum(1 for t in terms if t in searchable)
            if hits >= min_hits:
                enriched = _enrich_concern(concern, entry)
                enriched["_match_score"] = hits
                enriched["_match_ratio"] = hits / len(terms)
                scored.append(enriched)

    scored.sort(key=lambda c: (
        -c["_match_ratio"],
        -c["_match_score"],
        _SEVERITY_ORDER.get(c.get("severity", "LOW"), 9),
    ))
    return scored[:limit]


# ─── Stats & counts ──────────────────────────────────────────


def get_stats_summary(kb_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the pre-computed stats summary."""
    path = kb_path or _STATS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def count_concerns_with_tag(
    tag: str,
    expand_synonyms: bool = True,
    kb_path: Optional[Path] = None,
) -> int:
    """Count how many concerns have a specific tag (with optional synonym expansion).

    Args:
        tag: Tag to count
        expand_synonyms: If True, also count synonym-expanded tags
    """
    tags_to_check = _expand_tags([tag]) if expand_synonyms else {tag}
    kb = _load_kb(kb_path)
    count = 0
    for entry in kb.get("entries", []):
        for concern in entry.get("reviewer_concerns", []):
            if tags_to_check & set(concern.get("tags", [])):
                count += 1
    return count


# ─── Formatting ───────────────────────────────────────────────


def format_peer_context(
    concerns: List[Dict],
    max_display: int = 3,
    max_text_len: int = 150,
) -> str:
    """Format peer review concerns for display in gate output or agent response.

    Args:
        concerns: List of enriched concern dicts from retrieve_* functions
        max_display: Maximum concerns to display
        max_text_len: Max characters for concern text (CRITICAL gets 250)

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
        # CRITICAL concerns get more text
        text_limit = 250 if sev == "CRITICAL" else max_text_len
        text = c.get("concern_text", "")[:text_limit]
        fix = c.get("author_response", "")
        tags = ", ".join(c.get("tags", [])[:4])

        lines.append(f"  [{sev}] {cid} ({paper}, NC {year})")
        lines.append(f"    Concern: {text}...")
        if fix and fix not in _GENERIC_FIXES:
            lines.append(f"    Fix: {fix[:120]}...")
        lines.append(f"    Tags: {tags}")
        if i < max_display - 1:
            lines.append("")

    total = len(concerns)
    if total > max_display:
        lines.append(f"  ... and {total - max_display} more similar concerns in KB")

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
