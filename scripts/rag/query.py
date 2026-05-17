"""High-level RAG query API and CLI for the MLGG peer-review KB.

This module is the **public** entry point of the ``scripts/rag/`` package.
All other modules in the package (``config``, ``embeddings``,
``index.builder``, ``retrieval.dense``, ``retrieval.bm25``,
``retrieval.hybrid``) are internal and should not be imported directly by
callers outside the package.

Two ways to use it:

* **Programmatic** -- ``from scripts.rag.query import rag_query``::

      results = rag_query("no calibration in evaluation",
                          gate="evaluation_quality_gate",
                          top_k=5)

* **Command line**::

      python3 scripts/rag/query.py "your question" \\
          [--gate <gate_name>] [--codes a,b,c] \\
          [--top-k N] [--format json|table]

Exit codes (CLI):
    * ``0`` -- success, including the "no results / KB unavailable" case
      (which prints a clear message but does not error out).
    * ``2`` -- argparse usage error (missing query, bad ``--top-k``, etc.).

Design contract:
    The thin-wrapper discipline -- ``rag_query`` just adds graceful error
    handling around ``retrieval.hybrid.hybrid_rank`` -- keeps the ranking
    logic in a single place. Callers depend on the ``rag_query`` function
    signature staying stable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Ensure the repo root is on sys.path so ``scripts.rag.*`` imports work when
# this file is invoked directly via ``python3 scripts/rag/query.py ...``
# (rather than as ``python3 -m scripts.rag.query``).
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
    min_score: float = 0.0,
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
            from :mod:`scripts.core.gate_rag_bridge`. Must be non-empty
            after stripping whitespace; otherwise an empty list is
            returned.
        gate: Optional MLGG gate name (e.g. ``"leakage_gate"``) used by the
            hybrid ranker to filter / boost concerns tagged with that gate.
        failure_codes: Optional list of MLGG rule codes (e.g.
            ``["MLGG-E02"]``). Used by the hybrid ranker for tag-overlap
            scoring.
        top_k: Maximum number of concerns to return. Must be positive;
            silently clamped to ``1`` if a non-positive value is passed in,
            to mirror the CLI's argparse-level validation behavior.
        min_score: W27-R2 opt-in confidence floor. Records whose
            ``_final_score`` is below this threshold are dropped from the
            returned list. Default ``0.0`` disables filtering (back-compat
            with W22-X4 callers and the W25 benchmark snapshots). Records
            without a numeric ``_final_score`` are kept unconditionally
            (defensive: the ranker is the score authority; absence means
            the caller's contract pre-dates scoring, not low confidence).

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
        results = hybrid_rank(
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

    if min_score > 0.0 and results:
        results = [
            r for r in results
            if not isinstance(r.get("_final_score"), (int, float))
            or float(r["_final_score"]) >= min_score
        ]
    return results


def prewarm(*, force_rebuild: bool = False) -> dict:
    """Pre-load model + index so the first real query has steady-state latency.

    The E4 cache+perf eval flagged a ~228 ms first-query latency vs ~12 ms
    steady-state. Latency-sensitive callers (gate runners, web UI) should call
    this once at service start to eat the cold cost upfront rather than
    paying it on the first user-facing query.

    Returns:
        A dict with timing + state keys:

        * ``model_load_ms`` -- wall-clock to materialize the SentenceTransformer
          singleton (near-zero on second call).
        * ``index_load_ms`` -- wall-clock to load or rebuild the embedding
          index. Below ~1 s typically means the npz cache was hit.
        * ``warm_query_ms`` -- wall-clock of a tiny throw-away query that
          exercises the full hybrid-rank path, so the BM25 + dense retrievers
          are also warm. The probe text is derived from the first loaded
          record's ``concern_text`` (truncated to 40 chars), with a literal
          ``"calibration"`` fallback if the record has no usable text. This
          keeps the probe valid even if the KB topic mix changes (H6).
        * ``n_concerns`` -- number of concern records in the loaded index.
        * ``cache_was_warm`` -- ``True`` if the embeddings npz cache file
          existed on disk **before** ``build_or_load_index`` was called. This
          is more authoritative than a pure timing heuristic: it directly
          reflects whether the on-disk artifact was reused, regardless of
          how long the load happened to take on a slow filesystem (H6).

    Idempotent: the second call hits the model singleton and the on-disk
    index cache, so it should complete in tens of milliseconds.

    Args:
        force_rebuild: Forwarded to ``build_or_load_index`` when supported,
            to ignore the on-disk cache and re-embed. Default ``False``.
    """
    import time

    t0 = time.perf_counter()
    from scripts.rag.embeddings import get_model
    get_model()
    model_load_ms = (time.perf_counter() - t0) * 1000

    # Authoritative cache signal: snapshot file-existence BEFORE the loader
    # has a chance to (re)write it. We deliberately use the canonical config
    # path so we observe the same artifact the builder reads/writes.
    from scripts.rag import config as _rag_config
    cache_existed_pre = _rag_config.EMBEDDINGS_CACHE.exists()

    t0 = time.perf_counter()
    from scripts.rag.index.builder import build_or_load_index
    # Defensive: tolerate older signatures that may not yet accept
    # ``force_rebuild``. Keeps prewarm() robust across in-flight refactors.
    import inspect
    sig = inspect.signature(build_or_load_index)
    kwargs = {"force_rebuild": force_rebuild} if "force_rebuild" in sig.parameters else {}
    _emb, recs = build_or_load_index(**kwargs)
    index_load_ms = (time.perf_counter() - t0) * 1000

    # Derive the probe text from the actual loaded records rather than
    # hardcoding "calibration". This keeps prewarm() robust if the KB ever
    # drops calibration-themed concerns (H6 finding).
    probe_text = ""
    if recs:
        probe_text = (recs[0].get("concern_text", "") or "").strip()[:40]
    if not probe_text:
        probe_text = "calibration"  # ultimate fallback for empty/None text

    t0 = time.perf_counter()
    _ = rag_query(probe_text, top_k=1)
    warm_query_ms = (time.perf_counter() - t0) * 1000

    # cache_was_warm is True when the npz existed before we asked the builder
    # to do anything AND the loader returned quickly (timing corroboration
    # catches the "file existed but was stale and got rebuilt" edge case,
    # since rebuilds dominate wall time at ~30-60s).
    cache_was_warm = cache_existed_pre and index_load_ms < 5000.0

    return {
        "model_load_ms": round(model_load_ms, 1),
        "index_load_ms": round(index_load_ms, 1),
        "warm_query_ms": round(warm_query_ms, 1),
        "n_concerns": len(recs),
        "cache_was_warm": cache_was_warm,
    }


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


def _render_explain(results: list[dict]) -> str:
    """Render the per-rank ``_mmr_breakdown`` audit dict for ``--explain``.

    Emits one line per result with the four fields the MMR reranker
    attaches: ``relevance``, ``max_sim``, ``blocker_id``, ``blocker_reason``.
    Output is plain text destined for stderr so it never pollutes the
    stdout JSON / table contract that programmatic callers consume.

    ADR: see ``docs/adr/0001_mmr_breakdown_consumer.md`` (W11-I2) for
    the SHIP rationale -- this is the one canonical consumer of
    ``_mmr_breakdown`` and therefore freezes its schema.

    Args:
        results: List of concern dicts as returned by ``rag_query``.
            Each is expected to carry the post-MMR keys ``_mmr_score``
            and ``_mmr_breakdown``; entries missing the breakdown are
            rendered with a ``no_breakdown`` placeholder so callers can
            still see the rank order during partial-rollout windows.

    Returns:
        Multiline string. Empty results yield a single ``(no results)``
        notice so ``--explain`` always emits at least one informative
        line.
    """
    if not results:
        return "(no results -- nothing to explain)"

    lines: list[str] = ["mmr_breakdown (rank=relevance, max_sim, blocker):"]
    for rank, rec in enumerate(results, start=1):
        cid = rec.get("concern_id", "<unknown>")
        bd = rec.get("_mmr_breakdown")
        if not isinstance(bd, dict):
            lines.append(
                f"  rank={rank} concern_id={cid} -- no_breakdown "
                f"(pre-W9-B2 record or non-MMR path)"
            )
            continue
        relevance = bd.get("relevance", 0.0)
        max_sim = bd.get("max_sim", 0.0)
        blocker_id = bd.get("blocker_id")
        blocker_reason = bd.get("blocker_reason", "none")
        try:
            rel_s = f"{float(relevance):.3f}"
        except (TypeError, ValueError):
            rel_s = str(relevance)
        try:
            sim_s = f"{float(max_sim):.3f}"
        except (TypeError, ValueError):
            sim_s = str(max_sim)
        lines.append(
            f"  rank={rank} concern_id={cid} relevance={rel_s} "
            f"max_sim={sim_s} blocker_id={blocker_id} "
            f"blocker_reason={blocker_reason}"
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for the CLI.

    Factored out so tests can introspect the parser without spawning a
    subprocess.
    """
    parser = argparse.ArgumentParser(
        prog="scripts/rag/query.py",
        description=(
            "Query the MLGG peer-review RAG layer. Returns ranked reviewer "
            "concerns relevant to a free-text question, optionally filtered "
            "by gate and MLGG rule codes."
        ),
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
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
    parser.add_argument(
        "--prewarm",
        action="store_true",
        help=(
            "Pre-load the embedding model + KB index and print a JSON status "
            "dict, then exit 0. Use at service start to eat cold-cache "
            "latency upfront. When set, the positional 'query' is optional."
        ),
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "After the normal results, also emit the MMR per-rank breakdown "
            "to stderr: relevance, max_sim, blocker_id, blocker_reason. "
            "Use when a result's rank surprises you and you need to see "
            "whether MMR diversity (cosine near-dup or same-paper penalty) "
            "demoted it. The stdout JSON/table contract is unchanged. "
            "ADR: docs/adr/0001_mmr_breakdown_consumer.md."
        ),
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

    if args.prewarm:
        status = prewarm()
        print(json.dumps(status, ensure_ascii=False))
        return 0

    if args.query is None:
        parser.error("query is required unless --prewarm is supplied")

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

    # ``--explain`` writes to stderr (ADR-0001) so the stdout JSON / table
    # contract that programmatic callers depend on stays unchanged. Off by
    # default, free when off.
    if args.explain:
        print(_render_explain(results), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
