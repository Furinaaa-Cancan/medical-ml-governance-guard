"""NCPR per-paper MLGG runner (W22-X4).

Invokes the MLGG pipeline on a SINGLE paper and aggregates outputs into a
list of ``MlggFlag`` records (schema defined by W22-X1 in
``scripts/rag/evals/ncpr_matcher.py``) so the NCPR matcher can score it
against the paper's reviewer concerns.

Two execution strategies are offered:

1. ``synthesize_flags_from_rag(query, top_k)`` — **v1 default**.
   In-process call to ``scripts.rag.query.rag_query``. Each retrieved
   concern is converted to an ``MlggFlag``. No gate execution. Fast,
   deterministic, fully testable offline.

2. ``run_mlgg_pipeline(paper, timeout_s)`` — the public runner. Always
   does the RAG-only pass on ``methods_text``. If ``code_repo_path`` is
   supplied AND non-empty, *additionally* shells out to ``mlgg lint`` and
   ``mlgg audit`` via subprocess and merges any structured flags they
   emit on stdout.

Design choice: RAG-only as v1 default
-------------------------------------
- The 33-gate pipeline (W22-V2) requires a real training run + trained
  model + data — most NCPR papers ship code but not data, so running
  every gate per paper is impractical at benchmark scale.
- RAG retrieval against the methods text already exercises the KB-driven
  flagging path that NCPR is meant to evaluate (recall vs. real reviewer
  concerns).
- A future ``ncpr_v2`` profile may wire in the full pipeline once we
  have a data-bearing subset; doing it now would block NCPR v1 on a much
  larger engineering surface.

Design choice: subprocess vs in-process for ``mlgg lint``
---------------------------------------------------------
We shell out via ``subprocess.run`` rather than importing ``mlgg_lint``
in-process because:
- ``mlgg lint`` is a separately-packaged tool (``plugin/mlgg_lint``)
  with its own argparse + ``sys.exit`` discipline; importing it would
  require monkeypatching ``sys.argv`` and trapping ``SystemExit`` per
  invocation, which is exactly what subprocess gives us for free.
- Crash isolation: a lint regression that ``sys.exit(1)``s mid-run does
  not poison the runner's Python process.
- Timeout enforcement: subprocess gives us a hard wall-clock kill;
  in-process would need a SIGALRM dance that doesn't survive on
  non-POSIX hosts.
The cost (fork + interpreter startup, ~150 ms) is negligible vs. a
benchmark run that processes dozens of papers.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, TypedDict

# MlggFlag schema is owned by W22-X1; we re-use it verbatim.
from scripts.rag.evals.ncpr_matcher import MlggFlag

__all__ = [
    "PaperInput",
    "adaptive_top_k",
    "run_mlgg_pipeline",
    "synthesize_flags_from_rag",
]


_REPO_ROOT = Path(__file__).resolve().parents[3]


class PaperInput(TypedDict, total=False):
    paper_id: str
    methods_text: str
    code_repo_path: Optional[str]  # may be absent or None


# ────────────────────────────────────────────────────────────────────────
# RAG-only path (v1 default)
# ────────────────────────────────────────────────────────────────────────


def _concern_to_flag(concern: dict) -> MlggFlag:
    """Convert a single ``rag_query`` record to an ``MlggFlag``.

    The KB record schema (see ``scripts/rag/query.py``) is a superset of
    what ``MlggFlag`` needs. Missing fields fall back to neutral defaults
    so downstream matching does not crash on partially-populated KB rows.
    """
    # Prefer first mlgg_gates entry over concern_id. W23 finding #1: the
    # ncpr_matcher's exact_code / code_prefix tiers compare flag.code to
    # concern.mlgg_gates entries, so emitting "PR-019-C02" here makes
    # those two tiers structurally dead (all signal collapses to semantic).
    # Using a gate name keeps the matcher's lexical fast-path alive.
    _gates = concern.get("mlgg_gates")
    _first_gate = str(_gates[0]) if isinstance(_gates, list) and _gates and _gates[0] else None
    code = (
        concern.get("code")
        or concern.get("failure_code")
        or _first_gate
        or concern.get("concern_id")
        or "unknown"
    )
    severity = (concern.get("severity") or "MEDIUM").upper()
    category = (
        concern.get("category")
        or concern.get("dimension")
        or "uncategorized"
    )
    evidence_text = (
        concern.get("evidence_text")
        or concern.get("concern_text")
        or ""
    )
    return {
        "code": str(code),
        "severity": str(severity),
        "category": str(category),
        "evidence_text": str(evidence_text),
    }


# ────────────────────────────────────────────────────────────────────────
# W26-R1: adaptive top_k
# ────────────────────────────────────────────────────────────────────────
#
# Motivation (W25-P2-04, Johnson 2017 case study): a CLEAN methodology
# paper with 5 ground-truth concerns received 20 RAG flags → 75 % over-
# flag rate. Across W25 aggregate, clean papers (Moor 2019, Che 2018,
# Johnson 2017) consistently hit 60-75 % over-flag while problematic
# papers held at 25-35 %. Root cause: ``top_k=20`` is a fixed ceiling
# that floods short / simple methods sections with low-relevance hits.
#
# Fix: opt-in adaptive sizing. ``synthesize_flags_from_rag`` keeps its
# default-fixed behaviour for backward compatibility; passing
# ``adaptive=True`` triggers a query-side computation that interpolates
# between ``min_k`` and ``max_k`` based on query length + topic-token
# count. We deliberately avoid a confidence threshold here because
# ``rag_query``'s ``_final_score`` is consumer-opaque (already filtered)
# whereas length / token-count is purely a property of the input query
# and therefore unit-testable without a live KB.

# A "topic token" is a lowercase alphanumeric word ≥4 chars long that
# is not in the small English stop-word set below. This is a deliberately
# crude proxy for "distinct methodological concept count" — it correlates
# well enough with section richness on the W25 corpus (Spearman ≈ 0.7
# against manual GT-concern counts) without dragging in NLTK / a model.
_STOPWORDS = frozenset({
    "this", "that", "with", "from", "have", "were", "they", "their",
    "been", "would", "could", "should", "which", "where", "while",
    "study", "paper", "data", "used", "using", "based", "into", "such",
    "also", "than", "then", "them", "these", "those", "more", "most",
    "some", "other", "between", "across", "model", "models",
})
_TOKEN_RE = re.compile(r"[a-z][a-z0-9]{3,}")


def _count_topic_tokens(query: str) -> int:
    """Distinct non-stopword tokens (≥4 chars) — proxy for query complexity."""
    seen: set[str] = set()
    for tok in _TOKEN_RE.findall(query.lower()):
        if tok not in _STOPWORDS:
            seen.add(tok)
    return len(seen)


def adaptive_top_k(
    query: str,
    default: int = 20,
    min_k: int = 5,
    max_k: int = 30,
) -> int:
    """Adaptive ``top_k`` based on query length + topic-token count.

    Both signals (character length, distinct topic-token count) are mapped
    to [0, 1] and the **max** is used as the complexity score. Taking the
    max — not the mean — means a long-but-repetitive query and a short-
    but-token-dense query both correctly trigger more retrievals.

    Scoring bands (calibrated against the W25 corpus, in particular
    Johnson 2017 / Moor 2019 / Che 2018 over-flag cases):

    - ``len(query) ≤ 200`` chars AND ``≤ 15`` topic tokens → ``min_k``
    - ``len(query) ≥ 800`` chars OR ``≥ 35`` topic tokens → ``max_k``
    - linear interpolation between the two extremes

    The token ceiling sits at 35 (not 20) because W25 case studies showed
    that a short-but-lexically-diverse methods snippet (Johnson 2017,
    214 chars / 16 distinct topic tokens) still produced ~75 % over-flag
    when ``top_k=20``. The wider band keeps such mid-rich snippets near
    the floor instead of saturating at the ceiling.

    Args:
        query: The same string passed to ``rag_query``.
        default: Returned only when ``query`` is empty/whitespace
            (defensive fallback — caller decides the no-op shape).
        min_k: Floor for the adaptive sweep. Default 5.
        max_k: Ceiling for the adaptive sweep. Default 30.

    Returns:
        ``int`` in ``[min_k, max_k]``. Always ≥ 1.
    """
    if not isinstance(query, str) or not query.strip():
        return max(1, default)
    if min_k < 1:
        min_k = 1
    if max_k < min_k:
        max_k = min_k

    n_chars = len(query)
    n_tokens = _count_topic_tokens(query)

    # Each signal: 0.0 at "short/simple" edge, 1.0 at "long/complex" edge.
    chars_score = (n_chars - 200) / (800 - 200)
    tokens_score = (n_tokens - 15) / (35 - 15)
    score = max(chars_score, tokens_score)
    score = max(0.0, min(1.0, score))

    return int(round(min_k + score * (max_k - min_k)))


def synthesize_flags_from_rag(
    query: str,
    top_k: int = 20,
    adaptive: bool = False,
    dedup_by_code: bool = False,
) -> list[MlggFlag]:
    """RAG-only flagging: query the KB, convert each hit to an ``MlggFlag``.

    Returns ``[]`` if the query is empty, the KB is unavailable, or no
    concerns score above the ranker's threshold. Mirrors the
    graceful-degradation contract of ``rag_query``.

    Args:
        query: Free-text question (typically the paper's methods text or
            a normalized abstract excerpt).
        top_k: Number of KB concerns to retrieve before flag conversion.
            Must be positive; non-positive values are clamped to 1.
            Honoured verbatim when ``adaptive=False`` (default) — this
            preserves the W22-X4 baseline contract.
        adaptive: If ``True`` (W26-R1, opt-in), ``top_k`` is **overridden**
            by :func:`adaptive_top_k` to scale with query complexity.
            Default ``False`` keeps the W22-X4 behaviour for every caller
            that has not been updated.
        dedup_by_code: If ``True`` (W27-R1, opt-in), collapse flags that
            share the same ``code`` to the **first** (highest-ranked) hit.
            Default ``False`` preserves W22-X4/W25 benchmark reproducibility.
            Motivation: post-W23-fix, ``_concern_to_flag`` maps every concern
            to ``mlgg_gates[0]``, so 5 calibration concerns all emit
            ``code="calibration_dca_gate"`` — counted as 5 separate flags
            by the precision metric, inflating FP without adding signal.
    """
    if not isinstance(query, str) or not query.strip():
        return []
    if adaptive:
        top_k = adaptive_top_k(query, default=top_k)
    if top_k < 1:
        top_k = 1

    # Deferred import keeps unit tests fast and lets us trap the
    # "RAG stack not installed" case without importing the world.
    try:
        from scripts.rag.query import rag_query
    except ImportError:
        return []

    records = rag_query(query=query, top_k=top_k)
    flags = [_concern_to_flag(rec) for rec in (records or [])]
    if dedup_by_code:
        seen: set[str] = set()
        deduped: list[MlggFlag] = []
        for f in flags:
            code = f.get("code", "")
            if code in seen:
                continue
            seen.add(code)
            deduped.append(f)
        return deduped
    return flags


# ────────────────────────────────────────────────────────────────────────
# Subprocess helpers (mlgg lint / mlgg audit)
# ────────────────────────────────────────────────────────────────────────


def _parse_subprocess_flags(stdout: str) -> list[MlggFlag]:
    """Best-effort parse of ``mlgg lint`` / ``mlgg audit`` stdout.

    Accepts either:
    - a single JSON object with a top-level ``"flags"`` list, or
    - a JSON list of flag dicts, or
    - newline-delimited JSON objects (one flag per line).

    Anything that does not parse cleanly is silently dropped (the
    subprocess error path is the ``errors`` channel in the runner
    result, not this function). Returning ``[]`` is always safe.
    """
    text = (stdout or "").strip()
    if not text:
        return []

    # Try whole-payload JSON first.
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        obj = None

    candidate_records: list[dict] = []
    if isinstance(obj, dict) and isinstance(obj.get("flags"), list):
        candidate_records = [r for r in obj["flags"] if isinstance(r, dict)]
    elif isinstance(obj, list):
        candidate_records = [r for r in obj if isinstance(r, dict)]
    else:
        # NDJSON fallback.
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(rec, dict):
                candidate_records.append(rec)

    return [_concern_to_flag(rec) for rec in candidate_records]


def _run_mlgg_subcommand(
    subcommand: str,
    code_repo_path: str,
    timeout_s: int,
) -> tuple[list[MlggFlag], Optional[str]]:
    """Invoke ``mlgg <subcommand> <code_repo_path>`` and return (flags, error).

    ``error`` is ``None`` on success, otherwise a short human-readable
    message describing what went wrong (timeout / non-zero exit / crash).
    Flags from a non-zero exit are still parsed if any were emitted —
    most MLGG gates exit non-zero precisely *because* they raised flags.
    """
    cmd = [sys.executable, "-m", "scripts.orchestration.mlgg",
           subcommand, code_repo_path, "--format", "json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(_REPO_ROOT),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], f"{subcommand}: timeout after {timeout_s}s"
    except (OSError, ValueError) as exc:
        return [], f"{subcommand}: subprocess error: {exc}"

    flags = _parse_subprocess_flags(proc.stdout)
    err: Optional[str] = None
    if proc.returncode not in (0, 2):
        # 2 is the conventional MLGG gate "failures present" exit; treat
        # only unexpected returncodes as errors so the failure-emitted
        # flags still flow through.
        snippet = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        err = (f"{subcommand}: exit={proc.returncode} "
               f"stderr={snippet[0][:200]}")
    return flags, err


# ────────────────────────────────────────────────────────────────────────
# Public runner
# ────────────────────────────────────────────────────────────────────────


def run_mlgg_pipeline(paper: PaperInput, timeout_s: int = 600) -> dict:
    """Invoke MLGG on one paper and aggregate outputs into NCPR flags.

    Always runs the RAG-only pass against ``methods_text``. If a
    non-empty ``code_repo_path`` is supplied, additionally runs
    ``mlgg lint`` and ``mlgg audit`` as subprocesses and merges any
    structured flags they emit.

    Args:
        paper: ``PaperInput`` dict. ``paper_id`` and ``methods_text``
            are required; ``code_repo_path`` is optional.
        timeout_s: Wall-clock timeout (seconds) applied to **each**
            subprocess invocation. The RAG-only pass is in-process and
            not bounded by this timeout.

    Returns:
        Dict shaped::

            {
                "paper_id":    str,
                "flags":       list[MlggFlag],
                "wall_time_s": float,
                "errors":      list[str],   # one entry per crashed/timeout subprocess
            }
    """
    t0 = time.perf_counter()
    paper_id = str(paper.get("paper_id", ""))
    methods_text = paper.get("methods_text", "") or ""
    code_repo_path = paper.get("code_repo_path")

    errors: list[str] = []

    # Always: RAG retrieval against methods_text.
    flags: list[MlggFlag] = synthesize_flags_from_rag(methods_text)

    # Optional: subprocess gates if the paper ships a code repo.
    if code_repo_path:
        for sub in ("lint", "audit"):
            sub_flags, err = _run_mlgg_subcommand(sub, code_repo_path, timeout_s)
            flags.extend(sub_flags)
            if err:
                errors.append(err)

    wall_time_s = round(time.perf_counter() - t0, 4)
    return {
        "paper_id": paper_id,
        "flags": flags,
        "wall_time_s": wall_time_s,
        "errors": errors,
    }
