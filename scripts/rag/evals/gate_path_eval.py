#!/usr/bin/env python3
"""Track A — faithful gate-path Precision@5 eval.

WHY THIS EXISTS
---------------
Every published ``mean_labeled_P@5`` number (``labeled_precision_at_5.json``,
the W14 ``METRIC_CONTRACT.md`` ``0.494`` figure) was measured through the
OFFLINE ``rag_query`` hybrid path: dense + BM25 + tag overlap + severity + MMR,
WITH a hand-authored ``query_text`` per case. That is the path a human running
``scripts/review/llm_paper_audit.py`` exercises — it is NOT the path a gate
failure takes in production.

The SHIPPING gate retriever (``scripts/core/_gate_framework.py``
``build_report_envelope``) calls ``scripts.rag.retrieval.bm25.retrieve_for_failure``
with ONLY ``gate_name`` + issue codes, ``limit=5``, and NO free-text query.
There is no dense signal, no MMR, no query_text. The hybrid P@5 therefore
over-states what a gate failure actually surfaces in a JSON report's
``peer_review_context``.

Track A closes that measurement gap: it drives the real gate retriever over
the SAME 36 labeled cases (L01–L36) the hybrid ``mean_labeled_P@5`` uses, with
the SAME ground-truth relevance labels, and reports the gate-path P@5
side-by-side with the recorded hybrid P@5. The delta is the honest cost of the
gate path's BM25-only-no-query design.

FAITHFULNESS CONTRACT (must mirror _gate_framework.build_report_envelope)
-------------------------------------------------------------------------
1. Stage 1: ``retrieve_for_failure(gate_name, primary_codes, limit=5)`` where
   ``primary_codes`` is failure codes if any, else warning codes. NO query_text.
2. Stage 2 retry: if (a) there were failure codes, (b) there are warning codes,
   and (c) the stage-1 top hit's ``_retrieval_mode == "severity_fallback"``,
   re-run with ``failure_codes + warning_codes``. Replicated verbatim from
   ``_gate_framework.py`` lines ~278-297 so the eval cannot drift from the
   shipping retry semantics.

The labeled set (L01–L36) carries only ``failure_codes`` and no ``warning_codes``,
so the stage-2 retry condition cannot fire on today's set — but it is replicated
exactly so a future holdout that carries warning codes is scored on the real
path, not a simplified one.

GROUND TRUTH
------------
For each labeled query, the relevant set = the ``concern_id`` of every
``top5_at_label_time`` entry with ``relevant == true``. Off-scope probes
(``top5_at_label_time == []``, e.g. L19/L20) have an empty relevant set; any
returned hit is a false positive → P@5 = 0. These are kept in the run and
flagged ``off_scope: true`` so a non-zero return there is a loud regression.

    gate_path_P@5(case) = |{top-5 gate-path concern_ids} ∩ {relevant ids}| / 5

NOTE on the metric denominator: this matches the labeled file's own
``p_at_5 = sum(relevant=true)/5`` convention (fixed /5, NOT /len(returned)),
so the gate-path number is directly comparable to the recorded hybrid number.

CIRCULARITY CAVEAT (inherited)
------------------------------
The relevance labels are LLM self-eval (Claude Opus 4.7, same model family as
the retriever — see ``labeled_precision_at_5.json`` ``circularity_warning``).
Track A INHERITS that caveat verbatim: the ABSOLUTE gate-path P@5 is an
optimistic self-eval estimate, NOT a publication-grade Precision@5. Track A's
honest contribution is the gate-vs-offline DELTA on a fixed label set, not an
unbiased absolute number. Do NOT cite the absolute value externally without
independent human re-labeling (METRIC_CONTRACT.md §2, §4).

OUTPUT
------
Writes ``references/retrieval_eval/gate_path_precision_at_5_v1.json`` (a FRESH
eval artifact produced at runtime — this is NOT a hand-edit of an existing
references/*.json, it is a computed sidecar like the harness reports). Override
with ``--output``.

CLI
---
::

    python3 scripts/rag/evals/gate_path_eval.py
    python3 scripts/rag/evals/gate_path_eval.py \\
        --labeled references/retrieval_eval/labeled_precision_at_5.json \\
        --output references/retrieval_eval/gate_path_precision_at_5_v1.json

Exit codes: 0 on success, 2 on input error (missing/empty labeled set).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo root on sys.path so ``scripts.rag.*`` imports resolve when this file
# is invoked directly via ``python3 scripts/rag/evals/gate_path_eval.py``.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_LABELED = (
    REPO_ROOT / "references" / "retrieval_eval" / "labeled_precision_at_5.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "references"
    / "retrieval_eval"
    / "gate_path_precision_at_5_v1.json"
)

# Fixed-5 denominator, mirroring the labeled file's own p_at_5 convention so
# the gate-path number is directly comparable to the recorded hybrid number.
TOP_K = 5


def load_labeled_queries(path: Path) -> List[Dict[str, Any]]:
    """Load the L01–L36 labeled-query list from labeled_precision_at_5.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = data.get("labeled_queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError(
            f"no 'labeled_queries' list found in {path}"
        )
    return queries


def relevant_ids_for(case: Dict[str, Any]) -> set[str]:
    """Ground-truth relevant concern_ids for a labeled case.

    = the concern_id of every top5_at_label_time entry with relevant == true.
    Off-scope probes (empty top5) yield an empty set: any gate-path hit there
    is a false positive.
    """
    out: set[str] = set()
    for entry in case.get("top5_at_label_time", []) or []:
        if entry.get("relevant") is True:
            cid = entry.get("concern_id")
            if cid:
                out.add(cid)
    return out


def gate_path_retrieve(
    gate_name: str,
    failure_codes: List[str],
    warning_codes: Optional[List[str]] = None,
    *,
    top_k: int = TOP_K,
) -> List[Dict[str, Any]]:
    """Drive the SHIPPING gate retriever exactly as build_report_envelope does.

    Faithful replication of scripts/core/_gate_framework.py:~278-297 — BM25-only,
    no query_text, with the stage-2 severity_fallback retry.

    Args:
        gate_name: gate that "failed" (as written in mlgg_gates).
        failure_codes: failure issue codes for the case.
        warning_codes: warning issue codes (the gate path uses these only for
            the stage-2 retry and as a stage-1 fallback when there are no
            failures). The labeled set has none today; replicated for fidelity.
        top_k: top-K to retrieve (gate path is hard-coded to 5).

    Returns:
        The enriched concern dicts the gate would have placed in
        ``peer_review_context`` (pre-truncation), in gate order.
    """
    # Deferred import: keep module import cheap and mirror the gate path's own
    # in-function import of the retriever.
    from scripts.rag.retrieval.bm25 import retrieve_for_failure

    failure_codes = list(failure_codes or [])
    warning_codes = list(warning_codes or [])

    # Stage 1: failures-first (fallback to warnings if no failures). No query_text.
    primary_codes = failure_codes if failure_codes else warning_codes
    peer_results = retrieve_for_failure(gate_name, primary_codes, limit=top_k)

    # Stage 2 retry: failures existed AND stage 1 landed in severity_fallback
    # (no keyword hit on failure codes alone). Augment with warnings.
    # Mirrors _gate_framework.py lines ~287-297 verbatim.
    if (
        failure_codes
        and warning_codes
        and peer_results
        and peer_results[0].get("_retrieval_mode") == "severity_fallback"
    ):
        peer_results = retrieve_for_failure(
            gate_name,
            failure_codes + warning_codes,
            limit=top_k,
        )

    return peer_results


def evaluate_case(case: Dict[str, Any], *, top_k: int = TOP_K) -> Dict[str, Any]:
    """Score one labeled case on the gate path; echo the recorded hybrid P@5."""
    case_id = case.get("id", "<unknown>")
    gate_name = case.get("gate", "") or case.get("gate_name", "")
    failure_codes = list(case.get("failure_codes", []) or [])
    warning_codes = list(case.get("warning_codes", []) or [])  # absent today

    relevant = relevant_ids_for(case)
    off_scope = len(case.get("top5_at_label_time", []) or []) == 0

    results = gate_path_retrieve(
        gate_name, failure_codes, warning_codes, top_k=top_k
    )
    returned_ids = [r.get("concern_id") for r in results]
    retrieval_modes = sorted(
        {r.get("_retrieval_mode") for r in results if r.get("_retrieval_mode")}
    )

    n_relevant_in_topk = sum(1 for cid in returned_ids if cid in relevant)
    # Fixed /top_k denominator (matches the labeled file's p_at_5 convention).
    gate_p_at_5 = n_relevant_in_topk / top_k

    recorded_hybrid_p_at_5 = case.get("p_at_5")
    delta = (
        round(gate_p_at_5 - recorded_hybrid_p_at_5, 3)
        if isinstance(recorded_hybrid_p_at_5, (int, float))
        else None
    )

    return {
        "id": case_id,
        "dimension": case.get("dimension", ""),
        "gate": gate_name,
        "failure_codes": failure_codes,
        "off_scope": off_scope,
        "n_relevant_labeled": len(relevant),
        "n_returned": len(returned_ids),
        "n_relevant_in_topk": n_relevant_in_topk,
        "gate_path_p_at_5": round(gate_p_at_5, 3),
        "recorded_hybrid_p_at_5": recorded_hybrid_p_at_5,
        "delta_gate_minus_hybrid": delta,
        "gate_path_retrieval_modes": retrieval_modes,
        "gate_path_returned_ids": returned_ids,
        "labeled_relevant_ids": sorted(relevant),
    }


def aggregate(per_case: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Macro-average gate-path P@5 and the recorded-hybrid P@5 over all cases."""
    n = len(per_case)
    gate_vals = [c["gate_path_p_at_5"] for c in per_case]
    hybrid_vals = [
        c["recorded_hybrid_p_at_5"]
        for c in per_case
        if isinstance(c["recorded_hybrid_p_at_5"], (int, float))
    ]
    deltas = [
        c["delta_gate_minus_hybrid"]
        for c in per_case
        if c["delta_gate_minus_hybrid"] is not None
    ]
    n_severity_fallback = sum(
        1 for c in per_case if "severity_fallback" in c["gate_path_retrieval_modes"]
    )
    # Off-scope regression guard: off-scope cases must return P@5 == 0.
    off_scope_violations = [
        c["id"]
        for c in per_case
        if c["off_scope"] and c["gate_path_p_at_5"] > 0.0
    ]
    return {
        "n_cases": n,
        "mean_gate_path_p_at_5": (
            round(sum(gate_vals) / n, 3) if n else None
        ),
        "mean_recorded_hybrid_p_at_5": (
            round(sum(hybrid_vals) / len(hybrid_vals), 3) if hybrid_vals else None
        ),
        "mean_delta_gate_minus_hybrid": (
            round(sum(deltas) / len(deltas), 3) if deltas else None
        ),
        "n_cases_severity_fallback": n_severity_fallback,
        "off_scope_p_at_5_violations": off_scope_violations,
    }


def run(labeled_path: Path, *, top_k: int = TOP_K) -> Dict[str, Any]:
    """Run Track A over the labeled set; return the full result dict."""
    cases = load_labeled_queries(labeled_path)
    per_case = [evaluate_case(c, top_k=top_k) for c in cases]
    return {
        "schema_version": "gate-path-p5-v1",
        "track": "A — shipping gate retriever (BM25-only, no query_text)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labeled_source": str(labeled_path),
        "retriever": (
            "scripts.rag.retrieval.bm25.retrieve_for_failure "
            "(via build_report_envelope-faithful 2-stage path)"
        ),
        "top_k": top_k,
        "caveat": (
            "Relevance labels are LLM self-eval (Opus 4.7, same model family "
            "as the retriever). ABSOLUTE gate-path P@5 is an optimistic "
            "self-eval estimate, NOT publication-grade. Honest contribution is "
            "the gate-vs-offline DELTA on a fixed label set. See "
            "labeled_precision_at_5.json:circularity_warning and "
            "METRIC_CONTRACT.md sections 2 and 4."
        ),
        "per_case": per_case,
        "aggregate": aggregate(per_case),
    }


def _print_summary(result: Dict[str, Any]) -> None:
    agg = result["aggregate"]
    print("=" * 70)
    print("Track A — gate-path Precision@5 (shipping retriever, no query_text)")
    print("=" * 70)
    for c in result["per_case"]:
        d = c["delta_gate_minus_hybrid"]
        d_str = f"{d:+.3f}" if d is not None else "  n/a"
        flag = "  [OFF-SCOPE]" if c["off_scope"] else ""
        print(
            f"  [{c['id']:<38}] gate={c['gate_path_p_at_5']:.3f}  "
            f"hybrid={c['recorded_hybrid_p_at_5']}  "
            f"delta={d_str}{flag}"
        )
    print("-" * 70)
    print(
        f"  mean gate-path P@5 : {agg['mean_gate_path_p_at_5']}\n"
        f"  mean hybrid P@5    : {agg['mean_recorded_hybrid_p_at_5']} "
        f"(recorded in labeled file)\n"
        f"  mean delta (gate-hybrid): {agg['mean_delta_gate_minus_hybrid']}\n"
        f"  cases in severity_fallback: {agg['n_cases_severity_fallback']}"
        f"/{agg['n_cases']}"
    )
    if agg["off_scope_p_at_5_violations"]:
        print(
            "  WARNING off-scope P@5>0 (false-positive regression): "
            + ", ".join(agg["off_scope_p_at_5_violations"])
        )
    print("=" * 70)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Track A faithful gate-path Precision@5 eval.",
    )
    p.add_argument(
        "--labeled",
        type=Path,
        default=DEFAULT_LABELED,
        help=f"Labeled-query JSON (default: {DEFAULT_LABELED}).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output sidecar JSON (default: {DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=TOP_K,
        help="Top-K to retrieve and the P@K denominator (default 5).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    labeled_path = Path(args.labeled).expanduser().resolve()
    if not labeled_path.exists():
        print(f"ERROR: labeled set not found: {labeled_path}", file=sys.stderr)
        return 2
    try:
        result = run(labeled_path, top_k=args.top_k)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_summary(result)

    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
