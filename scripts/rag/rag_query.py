"""High-level RAG query API and CLI for the MLGG peer-review KB.

This module is the **public** entry point of the ``scripts/rag/`` package
(Agent A6 of the shared RAG design). All other modules in the package
(``config``, ``embeddings``, ``index.builder``, ``retrieval.dense``,
``retrieval.bm25``, ``retrieval.hybrid``) are internal and should not be
imported directly by callers outside the package.

Two ways to use it:

* **Programmatic** -- ``from scripts.rag.rag_query import rag_query``::

      results = rag_query("no calibration in evaluation",
                          gate="evaluation_quality_gate",
                          top_k=5)

* **Command line**::

      python3 scripts/rag/rag_query.py "your question" \\
          [--gate <gate_name>] [--codes a,b,c] \\
          [--top-k N] [--format json|table]

Exit codes (CLI):
    * ``0`` -- success, including the "no results / KB unavailable" case
      (which prints a clear message but does not error out).
    * ``2`` -- argparse usage error (missing query, bad ``--top-k``, etc.).

Design contract:
    Shared signatures (see ``/tmp/mlgg_rag_design.md``) MUST be honored
    because other agents (A7, A8, A9) depend on them. The thin-wrapper
    discipline -- ``rag_query`` just adds graceful error handling around
    ``retrieval.hybrid.hybrid_rank`` -- keeps the ranking logic in a single
    place.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Ensure the repo root is on sys.path so ``scripts.rag.*`` imports work when
# this file is invoked directly via ``python3 scripts/rag/rag_query.py ...``
# (rather than as ``python3 -m scripts.rag.rag_query``).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rag_query(
    query: str,
    gate: Optional[str] = None,
    failure_codes: Optional[list[str]] = None,
    top_k: int = 5,
) -> list[dict]:
    """Return ranked peer-review concerns relevant to ``query``.

    Thin wrapper around ``retrieval.hybrid.hybrid_rank`` that handles two
    graceful-degradation cases the CLI and gate-integration layer rely on:

    1. **Empty / whitespace-only query** -- returns ``[]`` instead of letting
       the downstream ranker raise.
    2. **KB / embeddings unavailable** -- if the underlying ranker cannot be
       imported (e.g. ``sentence_transformers`` missing) or the KB file is
       absent on disk, returns ``[]`` rather than propagating the
       ``ImportError`` / ``FileNotFoundError``. Callers that need to detect
       this (e.g. the CLI) can inspect the return value -- an empty list is
       the documented "no useful answer" sentinel.

    All other exceptions from the ranker are allowed to propagate, since they
    indicate genuine bugs (e.g. malformed KB records, NaN in embeddings).

    Args:
        query: Free-text user query, or a synthesized failure description
            from ``_gate_integration``. Must be non-empty after stripping
            whitespace; otherwise an empty list is returned.
        gate: Optional MLGG gate name (e.g. ``"leakage_gate"``) used by the
            hybrid ranker to filter / boost concerns tagged with that gate.
        failure_codes: Optional list of MLGG rule codes (e.g.
            ``["MLGG-E02"]``). Used by the hybrid ranker for tag-overlap
            scoring.
        top_k: Maximum number of concerns to return. Must be positive;
            silently clamped to ``1`` if a non-positive value is passed in,
            to mirror the CLI's argparse-level validation behavior.

    Returns:
        A list of concern records (see the schema in
        ``/tmp/mlgg_rag_design.md``) sorted by ``_final_score`` descending.
        Possibly empty. Each record is a fresh dict; callers may mutate it.
    """
    # Defensive normalization. The downstream ranker's contract requires a
    # non-empty query, so we surface the "nothing to ask" case as an empty
    # result rather than an exception.
    if not isinstance(query, str) or not query.strip():
        return []
    if top_k < 1:
        top_k = 1

    # Deferred import: keeps ``--help`` cheap and avoids loading
    # sentence_transformers when the caller never actually runs a query.
    # Also lets us trap the "RAG stack not available" case without crashing.
    try:
        from scripts.rag.retrieval.hybrid import hybrid_rank
    except ImportError:
        return []

    try:
        return hybrid_rank(
            query=query,
            gate=gate,
            failure_codes=failure_codes,
            top_k=top_k,
        )
    except FileNotFoundError:
        # KB file missing on disk -- treat as "no answer available" rather
        # than a hard error, so CLI / gate-integration callers can degrade
        # gracefully.
        return []


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _parse_codes(raw: Optional[str]) -> Optional[list[str]]:
    """Parse the comma-separated ``--codes`` argument.

    Args:
        raw: Raw string from argparse (e.g. ``"MLGG-E02,MLGG-M01"``) or
            ``None`` if the flag was omitted.

    Returns:
        A list of stripped, non-empty codes, or ``None`` if ``raw`` was
        ``None`` / empty after splitting.
    """
    if raw is None:
        return None
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    return codes or None


def _truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len`` chars, appending an ellipsis when cut.

    Used for the table output so the ``concern_text`` column stays readable.
    """
    if text is None:
        return ""
    text = str(text).replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"  # single-char ellipsis


def _render_table(results: list[dict]) -> str:
    """Render ranking results as a fixed-width text table.

    The columns are sized for an ~120-char terminal: id (16), paper (10),
    severity (8), score (6), concern preview (~70).

    Args:
        results: List of concern dicts returned by ``rag_query``.

    Returns:
        A printable multiline string. Empty results yield a single-line
        "no results" notice rather than a header-only table.
    """
    if not results:
        return "(no matching concerns found)"

    headers = ("concern_id", "paper_id", "severity", "score", "concern_text")
    widths = (18, 10, 9, 7, 100)
    sep = "  "

    lines: list[str] = []
    header_row = sep.join(h.ljust(w) for h, w in zip(headers, widths))
    lines.append(header_row)
    lines.append(sep.join("-" * w for w in widths))

    for rec in results:
        score = rec.get("_final_score")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
        row = sep.join((
            str(rec.get("concern_id", "")).ljust(widths[0]),
            str(rec.get("paper_id", "")).ljust(widths[1]),
            str(rec.get("severity", "")).ljust(widths[2]),
            score_str.ljust(widths[3]),
            _truncate(rec.get("concern_text", ""), widths[4]),
        ))
        lines.append(row)

    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for the CLI.

    Factored out so tests can introspect the parser without spawning a
    subprocess.
    """
    parser = argparse.ArgumentParser(
        prog="rag_query.py",
        description=(
            "Query the MLGG peer-review RAG layer. Returns ranked reviewer "
            "concerns relevant to a free-text question, optionally filtered "
            "by gate and MLGG rule codes."
        ),
    )
    parser.add_argument(
        "query",
        help="Free-text question, e.g. 'no calibration in evaluation'.",
    )
    parser.add_argument(
        "--gate",
        default=None,
        help="Optional MLGG gate name (e.g. leakage_gate) to filter / boost.",
    )
    parser.add_argument(
        "--codes",
        default=None,
        help="Comma-separated MLGG rule codes, e.g. 'MLGG-E02,MLGG-M01'.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of concerns to return (default: 5).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format. 'table' (default) for humans, 'json' for tools.",
    )
    return parser


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Notes:
        ``ArgumentParser`` is constructed and ``parse_args`` is called at the
        very top of ``main()`` so ``--help`` exits cleanly with code 0 and
        emits a ``usage:`` line on stdout. This satisfies the
        ``tests/test_stress_gate_cli.py::TestAllScriptsHelp`` contract.

    Args:
        argv: Optional list of CLI arguments (excluding ``sys.argv[0]``).
            ``None`` means use ``sys.argv[1:]``.

    Returns:
        Exit code (``0`` on success, ``2`` on argparse error -- raised by
        ``parse_args``).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.top_k < 1:
        parser.error("--top-k must be a positive integer")

    failure_codes = _parse_codes(args.codes)

    results = rag_query(
        query=args.query,
        gate=args.gate,
        failure_codes=failure_codes,
        top_k=args.top_k,
    )

    if args.format == "json":
        # ``default=str`` is a defensive fallback for any numpy scalars that
        # might survive the ranker's float() coercion. The KB itself is pure
        # JSON-serializable Python.
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    else:
        print(_render_table(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
