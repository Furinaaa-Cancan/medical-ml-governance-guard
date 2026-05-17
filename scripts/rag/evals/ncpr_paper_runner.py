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
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, TypedDict

# MlggFlag schema is owned by W22-X1; we re-use it verbatim.
from scripts.rag.evals.ncpr_matcher import MlggFlag

__all__ = [
    "PaperInput",
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


def synthesize_flags_from_rag(query: str, top_k: int = 20) -> list[MlggFlag]:
    """RAG-only flagging: query the KB, convert each hit to an ``MlggFlag``.

    Returns ``[]`` if the query is empty, the KB is unavailable, or no
    concerns score above the ranker's threshold. Mirrors the
    graceful-degradation contract of ``rag_query``.

    Args:
        query: Free-text question (typically the paper's methods text or
            a normalized abstract excerpt).
        top_k: Number of KB concerns to retrieve before flag conversion.
            Must be positive; non-positive values are clamped to 1.
    """
    if not isinstance(query, str) or not query.strip():
        return []
    if top_k < 1:
        top_k = 1

    # Deferred import keeps unit tests fast and lets us trap the
    # "RAG stack not installed" case without importing the world.
    try:
        from scripts.rag.query import rag_query
    except ImportError:
        return []

    records = rag_query(query=query, top_k=top_k)
    return [_concern_to_flag(rec) for rec in (records or [])]


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
