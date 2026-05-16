"""Reproducible RAG retrieval eval -- single source of truth.

Run:
    python3 scripts/rag/evals/run_eval.py
    python3 scripts/rag/evals/run_eval.py --mode bm25_only
    python3 scripts/rag/evals/run_eval.py --scenarios path/to/custom.json
    python3 scripts/rag/evals/run_eval.py --output /tmp/myeval.md

Output:
    /tmp/rag_eval_<mode>_<timestamp>.md  (default, or whatever --output)
    JSON sidecar at same path with .json extension

Purpose:
    Replace narrative P@5 claims in agent reports with reproducible
    numbers. Any agent/human can re-run and get the SAME result to
    within sampling variance. Eliminates the "ghost regression" class
    of bug surfaced by W3 vs H14 disagreement.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


DEFAULT_SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"


def load_scenarios(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "scenarios" in data:
        return data["scenarios"]
    if isinstance(data, list):
        return data
    raise ValueError(f"unrecognized scenarios.json shape in {path}")


def _scenario_id(scenario: dict) -> str | None:
    """scenarios.json uses scenario_id; fall back to id for forward-compat."""
    return scenario.get("scenario_id") or scenario.get("id")


def score_one(scenario: dict, *, mode: str, top_k: int = 5) -> dict:
    """Score one scenario; return per-scenario metrics dict.

    Returns:
        {
            "id": str,
            "mode": str,
            "n_hits": int,
            "top1_score": float | None,
            "tag_precision_at_k": float | None,
            "ids_returned": list[str],
            "expected_tag_hits": int | None,
            "wall_ms": float,
        }
    """
    expected_tags = set(
        scenario.get("expected_tags")
        or scenario.get("expected_relevant_tags")
        or scenario.get("expected_categories")
        or []
    )
    gate = scenario.get("gate_name") or scenario.get("mlgg_gate_hint")
    codes = scenario.get("failure_codes") or scenario.get("failure_codes_hint") or []
    query = scenario.get("query_text") or scenario.get("query") or ""
    if not query.strip() and gate:
        # W7-P1: mirror scripts/rag/evals/harness.py (and gate_rag_bridge):
        # a gate + failure codes alone must be enough to retrieve. Without
        # this fallback, rag_query's empty-query guard short-circuits to []
        # and the scenario is silently dropped (n_hits=0, wall_ms=0), which
        # diverges from the production gate→RAG bridge path.
        query = f"{gate} {' '.join(codes)}".strip()

    t0 = time.perf_counter()
    if mode == "bm25_only":
        from scripts.rag.retrieval.bm25 import retrieve_for_failure

        hits = (
            retrieve_for_failure(gate, codes, limit=top_k) if (gate and codes) else []
        )
    else:  # hybrid (default -- matches production path)
        from scripts.rag import rag_query

        hits = rag_query(
            query,
            gate=gate,
            failure_codes=codes if codes else None,
            top_k=top_k,
        )
    wall_ms = (time.perf_counter() - t0) * 1000

    ids = [h.get("concern_id") for h in hits]
    matches: int | None
    if expected_tags and hits:
        matches = sum(
            1 for h in hits if expected_tags & set(h.get("tags") or [])
        )
        tag_prec: float | None = matches / len(hits)
    else:
        matches = None
        tag_prec = None

    top1 = None
    if hits:
        top1 = hits[0].get("_final_score") or hits[0].get("_score")

    return {
        "id": _scenario_id(scenario),
        "mode": mode,
        "n_hits": len(hits),
        "top1_score": top1,
        "tag_precision_at_k": tag_prec,
        "ids_returned": ids,
        "expected_tag_hits": matches,
        "wall_ms": round(wall_ms, 1),
    }


def aggregate(per_scenario: list[dict]) -> dict:
    """Aggregate per-scenario metrics.

    Wave 5 P2:
      * mean_hit_at_k is the PRIMARY metric (A2 finding): tag_precision@K
        penalises MMR-driven diversity because it rewards "stay in tag
        cluster". hit@K is binary per scenario -- did any expected tag
        appear in top-K at all? -- which is what gate consumers care
        about.
      * coverage_rate = n_evaluable / n_total (A4 finding): guards
        against ghost-improvement where a future change shrinks the
        evaluable set while raising mean P@K.
    """
    tag_precs = [
        r["tag_precision_at_k"]
        for r in per_scenario
        if r["tag_precision_at_k"] is not None
    ]
    # hit@K: 1.0 if any expected tag matched (binary per scenario), then mean.
    hits_at_k = [
        1.0 if (r.get("expected_tag_hits") or 0) > 0 else 0.0
        for r in per_scenario
        if r["tag_precision_at_k"] is not None
    ]
    top1_scores = [
        r["top1_score"]
        for r in per_scenario
        if isinstance(r["top1_score"], (int, float))
    ]
    n_evaluable = len(tag_precs)
    n_total = len(per_scenario)
    coverage_rate = (n_evaluable / n_total) if n_total else 0.0
    return {
        "n_scenarios": n_total,
        "n_evaluable": n_evaluable,
        "n_with_expected_tags": n_evaluable,  # backward-compat alias
        "coverage_rate": round(coverage_rate, 3),
        "mean_hit_at_k": (
            round(sum(hits_at_k) / len(hits_at_k), 3) if hits_at_k else None
        ),
        "mean_tag_precision_at_k": (
            sum(tag_precs) / len(tag_precs) if tag_precs else None
        ),
        "mean_top1_score": (
            sum(top1_scores) / len(top1_scores) if top1_scores else None
        ),
        "n_zero_hits": sum(1 for r in per_scenario if r["n_hits"] == 0),
        "wall_ms_total": round(sum(r["wall_ms"] for r in per_scenario), 1),
    }


def render_markdown(per_scenario, agg, *, mode, scenarios_path) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mean_hit = agg.get("mean_hit_at_k")
    mean_tp = agg["mean_tag_precision_at_k"]
    mean_top1 = agg["mean_top1_score"]
    coverage = agg.get("coverage_rate", 0.0)
    n_eval = agg.get("n_evaluable", agg.get("n_with_expected_tags", 0))
    n_total = agg["n_scenarios"]

    mean_hit_line = (
        f"- **PRIMARY** mean hit@K: **{mean_hit:.3f}** "
        f"(coverage = {coverage:.2f}, n_evaluable={n_eval}/{n_total})"
        if mean_hit is not None
        else "- **PRIMARY** mean hit@K: N/A"
    )
    mean_tp_line = (
        f"- SECONDARY mean tag_precision@K: **{mean_tp:.3f}** "
        f"(diversity-aware caveat: MMR lowers this by design; "
        f"prefer hit@K for headline)"
        if mean_tp is not None
        else "- SECONDARY mean tag_precision@K: N/A"
    )
    mean_top1_line = (
        f"- mean top1 score: **{mean_top1:.3f}**"
        if mean_top1 is not None
        else "- mean top1 score: N/A"
    )
    lines = [
        f"# RAG eval report -- {ts}",
        "",
        f"- mode: `{mode}`",
        f"- scenarios source: `{scenarios_path}`",
        f"- n_scenarios: {n_total} "
        f"(n_evaluable={n_eval}, coverage_rate={coverage:.3f})",
        mean_hit_line,
        mean_tp_line,
        mean_top1_line,
        f"- zero-hit scenarios: {agg['n_zero_hits']}",
        f"- wall time: {agg['wall_ms_total']:.0f}ms",
        "",
        "## Per-scenario",
        "",
        "| id | n_hits | top1 | hit@K | tag_p@K | wall_ms |",
        "|----|-------:|-----:|------:|--------:|--------:|",
    ]
    for r in per_scenario:
        top1 = (
            f"{r['top1_score']:.3f}"
            if isinstance(r["top1_score"], (int, float))
            else "-"
        )
        tp = (
            f"{r['tag_precision_at_k']:.3f}"
            if r["tag_precision_at_k"] is not None
            else "-"
        )
        if r["tag_precision_at_k"] is None:
            hit_cell = "-"
        else:
            hit_cell = "1" if (r.get("expected_tag_hits") or 0) > 0 else "0"
        lines.append(
            f"| `{r['id']}` | {r['n_hits']} | {top1} | {hit_cell} | "
            f"{tp} | {r['wall_ms']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## Coverage-drop guard",
            "",
            f"Coverage = N_evaluable / N_total = {coverage:.2f} "
            f"({n_eval}/{n_total})",
            "(If this drops between runs, mean P@K may rise artificially; "
            "investigate before celebrating.)",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_eval.py",
        description=(
            "Reproducible RAG retrieval eval -- single source of truth. "
            "Runs every scenario in references/retrieval_eval/scenarios.json "
            "and writes markdown + JSON sidecar reports."
        ),
    )
    parser.add_argument("--mode", choices=["bm25_only", "hybrid"], default="hybrid")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="markdown output path; JSON sidecar written alongside",
    )
    args = parser.parse_args(argv)

    if args.output is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        args.output = Path(f"/tmp/rag_eval_{args.mode}_{ts}.md")

    scenarios = load_scenarios(args.scenarios)
    per_scenario = [
        score_one(s, mode=args.mode, top_k=args.top_k) for s in scenarios
    ]
    agg = aggregate(per_scenario)
    md = render_markdown(
        per_scenario, agg, mode=args.mode, scenarios_path=args.scenarios
    )

    args.output.write_text(md)
    json_path = args.output.with_suffix(".json")
    json_path.write_text(
        json.dumps({"aggregate": agg, "per_scenario": per_scenario}, indent=2)
    )

    print(f"markdown: {args.output}")
    print(f"json:     {json_path}")
    print(f"mean hit@K (PRIMARY):       {agg['mean_hit_at_k']}")
    print(f"mean tag_precision@K (sec): {agg['mean_tag_precision_at_k']}")
    print(f"coverage_rate:              {agg['coverage_rate']} "
          f"(n_evaluable={agg['n_evaluable']}/{agg['n_scenarios']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
