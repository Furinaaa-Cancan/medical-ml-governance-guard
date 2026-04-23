"""Peer Review Knowledge Base retrieval for MLGG RAG.

Provides functions to query the peer-review-kb.json knowledge base
by dimension, gate, tag, category, domain, severity, paper, and text.
Used by the /mlgg skill and gate scripts to cite real NC reviewer concerns.

This module is READ-ONLY — it never modifies the knowledge base.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Tag/text tokenizer: split on any non-alphanumeric-non-underscore run,
# then further split on `_` since tags are snake_case. Used by
# retrieve_for_failure to match keywords against tokens rather than raw
# substrings — substring matching falsely linked short tokens like `idi`
# to unrelated tags such as `confounding_by_comorbidity` (`comorb-idi-ty`).
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Control bytes the KB text is allowed to contain when rendered to a
# terminal or markdown: ordinary whitespace (tab \x09, LF \x0a, CR \x0d).
# Everything else in the [0x00-0x1f, 0x7f] range is stripped — especially
# ESC (\x1b) which would let a malicious concern body inject ANSI color
# escapes or cursor-movement sequences into gate output. Reviewer-concern
# text in an NC paper KB should not need these.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def _sanitize_text(value: Any, *, max_len: Optional[int] = None) -> str:
    """Coerce KB text to a clean, truncated string safe for terminal /
    markdown output. Non-strings become empty. Control bytes (including
    ANSI ESC) are stripped. Length-capped when max_len is given.
    """
    if not isinstance(value, str):
        return ""
    out = _CONTROL_CHAR_RE.sub("", value)
    if max_len is not None and len(out) > max_len:
        out = out[:max_len]
    return out


def _sanitize_tags(values: Any, *, max_items: int = 4) -> List[str]:
    """Sanitize a list of tag strings. Non-list → empty. Non-string
    items dropped. Control bytes stripped. Truncated to max_items.
    """
    if not isinstance(values, list):
        return []
    clean: List[str] = []
    for v in values:
        if isinstance(v, str):
            clean.append(_CONTROL_CHAR_RE.sub("", v))
        if len(clean) >= max_items:
            break
    return clean


def _tokenize(text: str) -> Set[str]:
    """Tokenize a lowercased string into a set of alphanumeric tokens,
    splitting on underscores and non-word characters."""
    return {tok for tok in _TOKEN_SPLIT.split(text.lower()) if tok}

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
    # Discharge-finalized ICD / post-index code / POA-absent failure codes
    # from leakage_gate. Failure-code tokens (discharge, finalized, icd,
    # feature) do not overlap any KB tag, so without these synonyms the
    # retrieval falls back to severity-only ranking and scenario precision
    # sits at 0.167 (baseline captured 2026-04-23). Entries below map the
    # failure codes — and a handful of adjacent phrasings reviewers use —
    # onto the KB tag family that actually describes outcome-in-feature
    # and temporal leakage.
    "discharge_finalized_icd_as_feature": [
        "feature_is_outcome_proxy", "future_information_leakage",
        "outcome_defined_by_features", "circular_prediction",
        "target_leakage", "temporal_leakage", "definition_variable",
    ],
    "discharge_finalized_icd": [
        "feature_is_outcome_proxy", "future_information_leakage",
        "outcome_defined_by_features", "circular_prediction",
    ],
    "suspicious_feature_names": [
        "feature_is_outcome_proxy", "outcome_defined_by_features",
        "target_leakage", "definition_variable",
    ],
    "immortal_time_bias_pattern": [
        "future_information_leakage", "temporal_leakage",
        "survivor_bias", "target_leakage",
    ],
    "post_index_code": [
        "feature_is_outcome_proxy", "future_information_leakage",
        "temporal_leakage", "future_data_used",
    ],
    "poa_absent": [
        "feature_is_outcome_proxy", "outcome_defined_by_features",
        "target_leakage",
    ],
    "no_reproducibility": ["no_code_availability", "reproducibility", "irreproducible_methods", "code_as_pdf", "weights_not_shared", "broken_github_link"],
    "confounding": ["confounders", "missing_confounder", "confounders_undisclosed", "confounding_by_gender", "confounding_unadjusted", "covariate_adjustment_one_size_fits_all"],
    "overstatement": ["overstatement", "overclaimed", "overclaimed_novelty", "overclaimed_improvement", "overclaimed_public_health", "title_overstatement"],
}

_KB_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "case-studies" / "peer-review-kb.json"
_STATS_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "case-studies" / "peer-review-kb-stats.json"

_kb_cache: Optional[Dict[str, Any]] = None


class KBMalformedError(ValueError):
    """Raised when peer-review-kb.json has a structural shape that
    retrieval cannot safely process. Callers (notably
    _gate_framework.py) are expected to catch this and degrade the
    peer_review_context to an empty list with status=kb_unavailable,
    so a broken KB never crashes a gate's report envelope.
    """


def _validate_kb_shape(data: Any) -> None:
    """Minimum shape contract. We don't validate every field here —
    retrieval functions handle missing concern-level fields defensively.
    This guard only rejects shapes that would make the top-level
    traversal itself raise (dict.get on a list, list iteration on a
    dict, etc.).
    """
    if not isinstance(data, dict):
        raise KBMalformedError(
            f"KB root must be a JSON object, got {type(data).__name__}"
        )
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise KBMalformedError(
            f"KB 'entries' must be a list, got {type(entries).__name__}"
        )
    # Sampling check: non-dict entries would crash retrieval loops the
    # moment they iterate .get("reviewer_concerns"). Fail loudly.
    for idx, entry in enumerate(entries[:5]):
        if not isinstance(entry, dict):
            raise KBMalformedError(
                f"KB entries[{idx}] must be a dict, got {type(entry).__name__}"
            )


def _load_kb(kb_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and cache the peer review knowledge base.

    Caching policy (intentional — do not "fix" without discussion):

    - Default path (kb_path is None): cache hit/populate. Production
      callers hit a single `_KB_PATH` and benefit from one JSON parse
      amortized across 33 gates × N runs.
    - Custom path (kb_path given): always re-read, never cache. Tests
      pass custom paths to avoid poisoning production cache; caching
      per-path would let stale fixtures leak across tests and would
      also mask mid-test file edits. If a future use case needs
      persistent custom-path caching, reach for a keyed LRU — do not
      widen this branch.

    Raises:
        FileNotFoundError: KB file missing.
        KBMalformedError: KB is not valid JSON, or root shape fails the
            retrieval contract (dict with 'entries' list of dicts).
    """
    global _kb_cache
    if _kb_cache is not None and kb_path is None:
        return _kb_cache
    path = kb_path or _KB_PATH
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise KBMalformedError(f"KB is not valid JSON: {exc}") from exc
    _validate_kb_shape(data)
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


# Tokens that carry no signal when decoding issue codes. Chosen from observed
# gate outputs (clinical_floor_sensitivity_not_met, baseline_improvement_
# insufficient, mechanism_assessment_required, etc.). Keep this list minimal.
_CODE_TOKEN_STOPWORDS = frozenset({
    "not", "met", "required", "missing", "invalid", "insufficient",
    "unsupported", "recommended", "reported", "failed", "empty",
    "undocumented", "unknown", "assessment", "evidence", "policy",
    "spec", "value", "field", "type", "error",
})


def _issue_code_keywords(codes: List[str]) -> Set[str]:
    """Split snake_case / UPPER_CASE issue codes into a keyword set suitable
    for tag-overlap scoring. Filters common stopwords and 1-2 char fragments.

    Also applies TAG_SYNONYMS expansion when a whole issue code (or its
    snake_case form) is a known synonym key — this lets issue codes like
    `fit_before_split_detected` pull in the KB tag family
    `future_information_leakage / data_leakage_via_imputation`, which the
    bare token split would never reach.

    Examples:
      ['clinical_floor_sensitivity_not_met', 'clinical_floor_ppv_not_met']
        → {'clinical', 'floor', 'sensitivity', 'ppv'}
      ['baseline_improvement_insufficient']
        → {'baseline', 'improvement'}
      ['fit_before_split_detected']  (synonym key present)
        → {'fit', 'before', 'split', 'detected', 'future', 'information',
           'leakage', 'target', 'temporal', 'data', 'imputation'}
    """
    kws: Set[str] = set()
    # Collect the normalized whole-code forms we can probe against synonyms:
    # the raw code lowercased (with hyphens as underscores), plus the code
    # minus common trailing verbs ("_detected" / "_missing" / "_failed" / ...)
    # since issue codes often encode the observation as a suffix.
    _TRAILING_VERBS = (
        "_detected", "_missing", "_failed", "_required",
        "_not_met", "_insufficient", "_unreported",
        "_exceeded", "_below_threshold", "_not_tested",
    )
    synonym_probes: Set[str] = set()
    for code in codes:
        if not isinstance(code, str):
            continue
        norm = code.lower().replace("-", "_")
        synonym_probes.add(norm)
        for suffix in _TRAILING_VERBS:
            if norm.endswith(suffix):
                synonym_probes.add(norm[: -len(suffix)])
        for tok in norm.split("_"):
            if len(tok) >= 3 and tok not in _CODE_TOKEN_STOPWORDS:
                kws.add(tok)

    # Synonym expansion: for each probe that matches a TAG_SYNONYMS key,
    # add the sub-tokens of each target tag to the keyword set. We tokenize
    # the synonym targets too so matching still uses the set-membership
    # path in _score (word-level, not substring).
    for probe in synonym_probes:
        synonyms = TAG_SYNONYMS.get(probe)
        if not synonyms:
            continue
        for tag in synonyms:
            for tok in _tokenize(str(tag)):
                if len(tok) >= 3 and tok not in _CODE_TOKEN_STOPWORDS:
                    kws.add(tok)
    return kws


def retrieve_for_failure(
    gate_name: str,
    issue_codes: List[str],
    limit: int = 5,
    kb_path: Optional[Path] = None,
) -> List[Dict]:
    """Retrieve concerns for a gate failure, ranked by issue-code relevance.

    Bug fix 2026-04-17: `retrieve_by_gate` surfaces up to 5 concerns mapped to
    a gate and sorts them by severity only, which surfaces CRITICAL-severity
    topically-irrelevant concerns ahead of HIGH-severity on-target ones. For
    a clinical_metrics_gate failure on `clinical_floor_ppv_not_met`, this
    returned PR-001-C02 (target_leakage) ahead of lower-severity PPV-specific
    concerns. Precision was ~20% against failure semantics.

    This function scores each candidate by (tag-keyword-overlap, concern-text-
    keyword-overlap) extracted from the actual issue codes, and ranks tag
    overlap 3× higher. Falls back to severity-only ranking when no scored
    matches exist (so RAG never goes empty just because of keyword mismatch).

    Args:
        gate_name: Gate script name (as written in mlgg_gates field).
        issue_codes: List of failure/warning codes from the gate's report.
        limit: Max results.
        kb_path: Optional KB path for tests.

    Returns:
        Enriched concern dicts, ranked by (score desc, severity rank asc).
    """
    kb = _load_kb(kb_path)

    # Collect ALL candidates first (no limit), then re-rank.
    candidates = _collect_concerns(
        kb,
        lambda c, _: gate_name in c.get("mlgg_gates", []),
        limit=10_000,
    )
    if not candidates:
        return []

    def _tag_result(results: List[Dict], mode: str) -> List[Dict]:
        """Annotate each result with the retrieval mode that surfaced it.
        Consumers (gate envelope, CLI formatter, audit logs) can tell
        whether a cited concern is a keyword match or just a severity-
        sorted fallback — which matters for how strongly to rely on it."""
        return [{**c, "_retrieval_mode": mode} for c in results]

    keywords = _issue_code_keywords(issue_codes or [])
    if not keywords:
        return _tag_result(candidates[:limit], "severity_fallback")

    def _score(c: Dict) -> int:
        tag_tokens: Set[str] = set()
        for t in (c.get("tags") or []):
            tag_tokens |= _tokenize(str(t))
        tag_overlap = sum(1 for kw in keywords if kw in tag_tokens)
        text_tokens = _tokenize((c.get("concern_text") or "")[:600])
        text_overlap = sum(1 for kw in keywords if kw in text_tokens)
        return 3 * tag_overlap + text_overlap

    def _sev_rank(c: Dict) -> int:
        return _SEVERITY_ORDER.get(c.get("severity", ""), 99)

    scored = [(c, _score(c)) for c in candidates]
    # Stable sort by (-score, sev_rank). Scored ties broken by severity.
    scored.sort(key=lambda pair: (-pair[1], _sev_rank(pair[0])))
    ranked = [c for c, s in scored]

    # If nothing scored above 0 on keywords, fall back to severity-only
    # (the old behavior) so reports are never empty just because of
    # vocabulary mismatch.
    if scored[0][1] == 0:
        return _tag_result(candidates[:limit], "severity_fallback")
    return _tag_result(ranked[:limit], "keyword_match")


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

    # Use ceil so a 3-term query with ratio=0.4 actually requires 2/3 (≥40%),
    # not 1/3 (33%). int() truncated below the declared floor.
    min_hits = max(1, math.ceil(len(terms) * min_match_ratio))
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
        cid = _sanitize_text(c.get("concern_id", "?"), max_len=40) or "?"
        paper = _sanitize_text(c.get("_paper_id", "?"), max_len=20) or "?"
        year = _sanitize_text(str(c.get("_year", "?")), max_len=10) or "?"
        sev = _sanitize_text(c.get("severity", "?"), max_len=16) or "?"
        # CRITICAL concerns get more text
        text_limit = 250 if sev == "CRITICAL" else max_text_len
        text = _sanitize_text(c.get("concern_text", ""), max_len=text_limit)
        fix = _sanitize_text(c.get("author_response", ""), max_len=120)
        tags = ", ".join(_sanitize_tags(c.get("tags", []), max_items=4))

        lines.append(f"  [{sev}] {cid} ({paper}, NC {year})")
        lines.append(f"    Concern: {text}...")
        if fix and fix not in _GENERIC_FIXES:
            lines.append(f"    Fix: {fix}...")
        lines.append(f"    Tags: {tags}")
        if i < max_display - 1:
            lines.append("")

    total = len(concerns)
    if total > max_display:
        lines.append(f"  ... and {total - max_display} more similar concerns in KB")

    return "\n".join(lines)


def format_gate_peer_context(
    gate_name: str,
    issue_codes: Optional[List[str]] = None,
    kb_path: Optional[Path] = None,
) -> str:
    """Generate peer review context string for a specific gate failure.

    Args:
        gate_name: Name of the failed gate.
        issue_codes: Optional failure codes from the gate. When provided,
            uses the same issue-code-aware ranking as the JSON envelope
            (`retrieve_for_failure`). Without codes, falls back to
            severity-only ranking via `retrieve_by_gate` so callers that
            don't track codes still work.
        kb_path: Optional KB path for tests.

    Returns:
        Formatted string suitable for appending to gate summary output.
    """
    if issue_codes:
        concerns = retrieve_for_failure(gate_name, issue_codes, limit=10, kb_path=kb_path)
    else:
        concerns = retrieve_by_gate(gate_name, limit=10, kb_path=kb_path)
    if not concerns:
        return ""

    header = (
        f"\n📚 Peer Review Context ({len(concerns)} similar issues in NC papers):\n"
    )
    body = format_peer_context(concerns, max_display=3)
    return header + body
