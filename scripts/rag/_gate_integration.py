"""Gate integration hook for the MLGG RAG layer.

This module is the bridge between the 33 fail-closed governance gates and
the hybrid RAG ranker.  When a gate fails it calls
:func:`rag_context_for_failure` with the gate name and the symbolic
``failure_codes`` it emitted; this module synthesizes a free-text query,
delegates to :func:`scripts.rag._hybrid_ranker.hybrid_rank`, and returns
ranked reviewer concerns ready to render in the gate's ``report.json``
under the ``peer_review_context`` key.

The companion :func:`format_for_gate_report` renders those concerns as a
compact markdown snippet suitable for direct embedding in human-facing
gate reports.

Design contract: see ``/tmp/mlgg_rag_design.md`` (Agent A7 of 10).
"""

from __future__ import annotations

from typing import Any, Optional

from scripts.rag._hybrid_ranker import hybrid_rank


# Maximum number of reviewer-quote / author-response characters to embed
# verbatim in the markdown rendering.  Longer texts are truncated with an
# ellipsis so a gate report stays scannable; the full text is still
# available through the returned ``list[dict]`` payload.
_MAX_QUOTE_CHARS = 600
_MAX_RESPONSE_CHARS = 400


def _synthesize_query(
    failure_codes: list[str],
    query_hint: Optional[str],
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

    Returns:
        A whitespace-trimmed query string with underscores normalised to
        spaces.  Returns an empty string when both inputs are empty.
    """

    code_text = " ".join(failure_codes or [])
    raw = f"{code_text} {query_hint or ''}".strip()
    # Normalise snake_case → space-separated for better embedding quality.
    return raw.replace("_", " ").strip()


def rag_context_for_failure(
    gate_name: str,
    failure_codes: list[str],
    query_hint: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve ranked reviewer concerns relevant to a gate failure.

    Synthesises a query from ``failure_codes`` (plus an optional
    ``query_hint``), then delegates to
    :func:`scripts.rag._hybrid_ranker.hybrid_rank` with a gate filter so
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
            matching :data:`scripts.rag._rag_config.DEFAULT_TOP_K`.

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

    query = _synthesize_query(failure_codes, query_hint)
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


def format_for_gate_report(concerns: list[dict]) -> str:
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
            list yields a single-line "no related concerns" placeholder.

    Returns:
        A markdown string (no trailing newline) suitable for embedding
        verbatim in a gate report.
    """

    if not concerns:
        return "_No related peer-review concerns retrieved._"

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
        if response:
            block_lines.extend(["", f"   **Author response:** {response}"])
        block_lines.extend(
            [
                "",
                f"   _score: {score_str} · match: {reasons}_",
            ]
        )
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)
