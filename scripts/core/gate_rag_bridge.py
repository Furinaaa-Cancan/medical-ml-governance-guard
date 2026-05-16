"""Bridge from MLGG gates to the RAG layer.

Synthesizes a query from a gate failure, delegates to
:func:`scripts.rag.retrieval.hybrid.hybrid_rank`, and renders the result
as markdown for the gate's ``report.json``.

This module lives in :mod:`scripts.core` (next to the gate framework)
rather than inside :mod:`scripts.rag`, so the dependency direction stays
one-way: gates know about RAG, RAG does not know about gates.  When a
gate fails it calls :func:`rag_context_for_failure` with the gate name
and the symbolic ``failure_codes`` it emitted; the returned ranked
reviewer concerns are ready to embed in the gate's ``report.json``
under the ``peer_review_context`` key.

The companion :func:`format_for_gate_report` renders those concerns as a
compact markdown snippet suitable for direct embedding in human-facing
gate reports.

Design contract: see ``/tmp/mlgg_rag_design.md`` (Agent A7 of 10).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from scripts.rag.retrieval.hybrid import hybrid_rank


# Maximum number of reviewer-quote / author-response characters to embed
# verbatim in the markdown rendering.  Longer texts are truncated with an
# ellipsis so a gate report stays scannable; the full text is still
# available through the returned ``list[dict]`` payload.
_MAX_QUOTE_CHARS = 600
_MAX_RESPONSE_CHARS = 400

# H19 LLM-loop eval found: when a concern surfaces only through fallback
# signals (severity-only / gate-only / bm25-inactive padding) AND its
# final fused score sits below this floor, the markdown previously gave
# the synthesis-LLM (production Claude) no visual cue that the hit was
# weak. Citing such entries as "peer-review precedent" is a known
# failure mode. Tunable later; 0.05 chosen because hybrid_rank's
# severity-only fallback rows score in the 0.01–0.04 band.
_WEAK_MATCH_SCORE_FLOOR = 0.05
_WEAK_MATCH_HEDGE = (
    "   _(weak match — severity/gate-fallback only, not a semantic hit; "
    "do not cite as precedent.)_"
)
# Substrings (lowercased) marking a match-reason as fallback-only.
# Kept narrow on purpose: anything that genuinely reflects a semantic
# or lexical hit (dense_*, bm25_top_*, tag_overlap, canonical_pattern)
# must NOT match here, or strong concerns would be hedged.
_FALLBACK_REASON_MARKERS = (
    "fallback",
    "severity_only",
    "gate_only",
    "bm25_inactive",
)

# H19 W5 LLM-loop eval found: when 2+ concerns from the same paper
# surface in the same render (e.g. PR-EXP-0084-C04 + PR-EXP-0084-C08),
# the synthesis-LLM tends to weave them into a single narrative arc
# even though they are *independent* reviewer concerns. Worst case: a
# resolved + unresolved concern pair gets blended and the unresolved
# half is silently elided. The marker line below is injected at the
# top of each affected block so the LLM has an explicit visual cue
# that the concerns must stay separate.
_SAME_PAPER_MARKER_TEMPLATE = (
    "_(Independent concern from same paper as: {siblings}. "
    "Do NOT merge their narratives.)_"
)


def _is_weak_match(concern: dict) -> bool:
    """Return True if a concern was retrieved by fallback signals only.

    A concern is "weak" when (a) its fused ``_final_score`` is below
    :data:`_WEAK_MATCH_SCORE_FLOOR`, AND (b) every entry in
    ``_match_reasons`` is a fallback marker (severity-only, gate-only,
    bm25-inactive, or any reason containing "fallback"). Both conditions
    must hold; a low-scoring but semantically-matched concern (e.g.
    score 0.03 from ``dense_top_5``) is not hedged because the synthesis
    LLM can legitimately weigh the dense signal.

    The hedge exists because H19 evaluation showed Claude citing these
    padding rows as peer-review precedent — they are filler that keeps
    ``top_k`` populated, not real precedent.

    Args:
        concern: A single concern record as rendered by
            :func:`format_for_gate_report`.

    Returns:
        ``True`` iff the concern should carry the weak-match hedge line.
        Empty ``_match_reasons`` returns ``False`` (absence of provenance
        is not evidence of fallback).
    """

    score = concern.get("_final_score", 0.0)
    try:
        if float(score) >= _WEAK_MATCH_SCORE_FLOOR:
            return False
    except (TypeError, ValueError):
        # Non-numeric scores: treat as missing → cannot confirm weak.
        return False

    reasons = concern.get("_match_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    if not reasons:
        # No provenance recorded → don't speculate; leave un-hedged.
        return False
    return all(
        any(marker in str(r).lower() for marker in _FALLBACK_REASON_MARKERS)
        for r in reasons
    )


def _synthesize_query(
    failure_codes: list[str],
    query_hint: Optional[str],
    gate_name: Optional[str] = None,
) -> str:
    """Build a free-text query string from failure codes and an optional hint.

    Underscores in failure codes (e.g. ``missing_calibration``) are turned
    into spaces because the embedding model was trained on natural-language
    text, not snake_case tokens; this materially improves dense recall.

    Args:
        failure_codes: Symbolic failure tokens emitted by a gate, e.g.
            ``["missing_calibration", "no_ci"]``.  May be empty.
        query_hint: Optional free-text hint from the caller, typically a
            short human description of the failing scenario.
        gate_name: Fallback source for the synthesised query when both
            ``failure_codes`` and ``query_hint`` are empty.  Required by
            ``hybrid_rank`` which rejects empty queries (cosine of a
            zero vector is meaningless).

    Returns:
        A whitespace-trimmed query string with underscores normalised to
        spaces.  Guaranteed non-empty when ``gate_name`` is supplied.
    """

    code_text = " ".join(failure_codes or [])
    raw = f"{code_text} {query_hint or ''}".strip()
    # Normalise snake_case → space-separated for better embedding quality.
    synthesised = raw.replace("_", " ").strip()
    if synthesised:
        return synthesised
    # Empty-input fallback: use the gate name itself.  Without this the
    # caller would hit ``ValueError`` inside ``vector_search`` (cosine
    # cannot rank against an empty query), violating the contract in
    # ``rag_context_for_failure`` that the gate filter alone is usable.
    if gate_name:
        return gate_name.replace("_", " ").strip()
    return ""


def rag_context_for_failure(
    gate_name: str,
    failure_codes: list[str],
    query_hint: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve ranked reviewer concerns relevant to a gate failure.

    Synthesises a query from ``failure_codes`` (plus an optional
    ``query_hint``), then delegates to
    :func:`scripts.rag.retrieval.hybrid.hybrid_rank` with a gate filter so
    only concerns whose ``mlgg_gates`` include ``gate_name`` participate.

    Args:
        gate_name: The MLGG gate identifier (e.g.
            ``"evaluation_quality_gate"``).  Forwarded to the ranker as
            the ``gate=`` filter.
        failure_codes: Symbolic failure tokens emitted by the gate.  Used
            both to synthesise the query and forwarded to the ranker for
            its canonical-pattern / tag-overlap signals.
        query_hint: Optional free-text hint that augments the query.  Use
            this when the failure codes alone are too sparse to embed
            well (e.g. ``"on the held-out cohort"``).
        top_k: Maximum number of concerns to return.  Defaults to 5,
            matching :data:`scripts.rag.config.DEFAULT_TOP_K`.

    Returns:
        A list of up to ``top_k`` concern records (see the schema in
        ``/tmp/mlgg_rag_design.md``) sorted by ``_final_score`` descending.
        Each record carries the ranker's scoring metadata
        (``_dense_score``, ``_bm25_score``, ``_final_score``,
        ``_match_reasons``) so callers can surface provenance.

    Notes:
        - This function performs no KB writes (read-only by design).
        - When ``failure_codes`` is empty and ``query_hint`` is ``None``,
          the synthesised query is empty; the ranker is still invoked so
          the ``gate=`` filter alone can surface gate-relevant concerns.
    """

    query = _synthesize_query(failure_codes, query_hint, gate_name=gate_name)
    return hybrid_rank(
        query,
        gate=gate_name,
        failure_codes=failure_codes,
        top_k=top_k,
    )


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` chars with an ellipsis suffix.

    Args:
        text: Source string.  ``None``-like values are coerced to ``""``.
        limit: Maximum number of characters to keep.

    Returns:
        ``text`` unchanged if shorter than ``limit``, otherwise the first
        ``limit`` characters followed by ``"..."``.
    """

    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "..."


def _format_reasons(reasons: Any) -> str:
    """Render a list of match-reason strings as a comma-separated string.

    Args:
        reasons: The ``_match_reasons`` field from a concern record.  May
            be a list, tuple, or any other value; non-iterables are
            stringified verbatim.

    Returns:
        A human-readable comma-separated representation, or ``"-"`` when
        no reasons are available.
    """

    if not reasons:
        return "-"
    if isinstance(reasons, (list, tuple)):
        return ", ".join(str(r) for r in reasons)
    return str(reasons)


def format_for_gate_report(
    concerns: list[dict],
    gate_name: Optional[str] = None,
) -> str:
    """Render concern records as a markdown snippet for a gate report.

    The output is designed to drop directly under a
    ``### Peer-review context`` heading in a gate's ``report.json`` /
    rendered markdown.  Each concern becomes one block containing the
    bolded ``concern_id`` + ``severity``, the original reviewer quote,
    the author response (if present), and the ranker's ``_final_score``
    plus ``_match_reasons`` line for provenance.

    Args:
        concerns: Concern records as returned by
            :func:`rag_context_for_failure` (or any caller that honours
            the shared schema in ``/tmp/mlgg_rag_design.md``).  An empty
            list yields a single-line "no related concerns" placeholder
            UNLESS ``gate_name`` resolves to a registry entry with
            ``rag_optional=True`` — in which case the empty string is
            returned instead of the placeholder.
        gate_name: Optional MLGG gate identifier. When supplied AND the
            named gate is flagged ``rag_optional`` (infra/aggregation/meta
            gates that have no peer-review precedent by design), an empty
            ``concerns`` list renders as ``""`` rather than the misleading
            "no concerns retrieved" placeholder. Honest silence > false
            placeholder. Registry lookup failures fall through to the
            default placeholder behaviour, so this argument never raises.

    Returns:
        A markdown string (no trailing newline) suitable for embedding
        verbatim in a gate report. Returns ``""`` for empty-concerns +
        ``rag_optional`` gate; the default "no concerns" placeholder
        otherwise.
    """

    if not concerns:
        if gate_name:
            # Lazy import: avoids a circular dep at module-load time
            # (_gate_registry has historically been pulled into RAG-side
            # code paths). Registry lookup failures fall through to the
            # default placeholder — silence on lookup error would hide
            # legitimately-empty peer-review domains.
            try:
                from scripts.core._gate_registry import get_gate_spec

                spec = get_gate_spec(gate_name)
                if spec is not None and getattr(spec, "rag_optional", False):
                    return ""
            except Exception:  # noqa: BLE001 — registry lookup must not crash report rendering
                pass
        return "_No related peer-review concerns retrieved._"

    # H19 W5: pre-scan for paper_ids that appear more than once across
    # the rendered set so we can mark each affected block as
    # related-but-independent. Concerns without a paper_id are ignored
    # (they cannot share lineage we can name).
    paper_counts = Counter(
        c.get("paper_id") for c in concerns if c.get("paper_id")
    )
    same_paper_ids = {p for p, n in paper_counts.items() if n > 1}

    blocks: list[str] = []
    for idx, c in enumerate(concerns, start=1):
        concern_id = c.get("concern_id", "UNKNOWN")
        severity = c.get("severity", "UNKNOWN")
        quote = _truncate(c.get("concern_text", ""), _MAX_QUOTE_CHARS)
        response = _truncate(c.get("author_response", ""), _MAX_RESPONSE_CHARS)
        final_score = c.get("_final_score")
        reasons = _format_reasons(c.get("_match_reasons"))

        try:
            score_str = f"{float(final_score):.3f}"
        except (TypeError, ValueError):
            score_str = "n/a"

        block_lines = [
            f"{idx}. **{concern_id}** — _{severity}_",
            "",
            f"   > {quote}" if quote else "   > _(no reviewer quote captured)_",
        ]

        # H19 W5: prepend the same-paper marker so the synthesis-LLM
        # sees it *before* the concern body, eliminating the risk of
        # an unmarked block being narrated first and then retro-
        # interpreted. Siblings list is deterministic (input order)
        # for stable diffs.
        paper_id = c.get("paper_id")
        if paper_id in same_paper_ids:
            siblings = [
                other.get("concern_id", "UNKNOWN")
                for other in concerns
                if other.get("paper_id") == paper_id
                and other.get("concern_id") != concern_id
            ]
            if siblings:
                marker = _SAME_PAPER_MARKER_TEMPLATE.format(
                    siblings=", ".join(siblings)
                )
                # Insert *above* the header so visually it reads as a
                # framing note for the whole block.
                block_lines.insert(0, marker)
                block_lines.insert(1, "")
        if response:
            # "(as reported)" disclaimer prevents the gate reader from
            # treating the authors' rebuttal as ground truth. Many KB
            # entries have resolved=true but author response is
            # vague/deflected (Q5+A10 found ~10-13% mislabeled). Per A7.
            block_lines.extend(["", f"   **Author response (as reported):** {response}"])
        block_lines.extend(
            [
                "",
                f"   _score: {score_str} · match: {reasons}_",
            ]
        )
        # H19: append a visible hedge so synthesis-LLMs do not cite
        # fallback-padded rows as peer-review precedent. The line is
        # italicised + parenthesised to match the existing provenance
        # line's typographic weight.
        if _is_weak_match(c):
            block_lines.append(_WEAK_MATCH_HEDGE)
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)
