"""Reproducible RAG retrieval eval -- single source of truth.

Run:
    python3 scripts/rag/evals/run_eval.py
    python3 scripts/rag/evals/run_eval.py --mode bm25_only
    python3 scripts/rag/evals/run_eval.py --scenarios path/to/custom.json
    python3 scripts/rag/evals/run_eval.py --output /tmp/myeval.md
    python3 scripts/rag/evals/run_eval.py \
        --diff references/retrieval_eval/post_wave7_baseline_hybrid.json

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
    expected_cps = set(scenario.get("expected_canonical_pattern_ids") or [])
    gate = scenario.get("gate_name") or scenario.get("mlgg_gate_hint")
    codes = scenario.get("failure_codes") or scenario.get("failure_codes_hint") or []
    query = scenario.get("query_text") or scenario.get("query") or ""
    if not query.strip() and gate:
        # W7-P1: a gate + failure codes alone must be enough to retrieve.
        # Use the SHARED synth helper so this matches the offline rag_query
        # path and harness.py exactly. Two changes vs the old bare join
        # f"{gate} {' '.join(codes)}": (1) snake_case -> space normalization,
        # and (2) the gate NAME is no longer folded into the query text (the
        # gate is passed as a filter param instead). Not a superset of the old.
        from scripts.rag._enrich import synthesize_query
        query = synthesize_query(codes, gate_name=gate)

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
    cps_returned = [h.get("canonical_pattern_id") for h in hits]
    matches: int | None
    if expected_tags and hits:
        matches = sum(
            1 for h in hits if expected_tags & set(h.get("tags") or [])
        )
        tag_prec: float | None = matches / len(hits)
    else:
        matches = None
        tag_prec = None

    # cp_hit_at_k: 1.0 if any expected CP appears in top-K, 0.0 if not,
    # None if scenario carries no expected CP gold (skipped from aggregate).
    # Stricter than tag-overlap — the RAG must retrieve a concern that
    # actually belongs to the canonical pattern the scenario targets,
    # which is the unit the gate consumers reason in.
    cp_hit: float | None
    if expected_cps and hits:
        cp_hit = 1.0 if any(cp in expected_cps for cp in cps_returned if cp) else 0.0
    else:
        cp_hit = None

    top1 = None
    if hits:
        # Explicit None check: a legitimate 0.0 score must be kept, so we
        # cannot use truthy-or (which would silently fall through to _score
        # or None and drop a real zero).
        top1 = hits[0].get("_final_score")
        if top1 is None:
            top1 = hits[0].get("_score")

    return {
        "id": _scenario_id(scenario),
        "mode": mode,
        "n_hits": len(hits),
        "top1_score": top1,
        "tag_precision_at_k": tag_prec,
        "ids_returned": ids,
        "cps_returned": cps_returned,
        "expected_tag_hits": matches,
        "cp_hit_at_k": cp_hit,
        "wall_ms": round(wall_ms, 1),
    }


def _bootstrap_ci(
    values: list[float], n_bootstrap: int = 1000, alpha: float = 0.05,
    seed: int = 20260517,
) -> tuple[float | None, float | None]:
    """Percentile-bootstrap (1-alpha) CI on a list of binary/proportion values.

    Added 2026-05-17 in response to MLGG-Bench v1.0.2 REVIEW.md M2 (per-slice
    n=10 needs CIs). Off-by-one fixed 2026-05-17 per INDEPENDENT_REVIEW.md
    finding B3 (R1+R8): the previous `int(alpha/2 * B)` truncation reported
    ~2.6/97.6 percentiles, not 2.5/97.5. Now uses `(B-1) * alpha/2` indexing
    + bounds-clamp (matches numpy.percentile with method='lower' on sorted
    samples) so e.g. B=1000, alpha=0.05 → lo_idx=12, hi_idx=987 → 2.5%/97.5%
    Hyndman-Fan rank position 7. Also clamps alpha so alpha=0 won't IndexError.

    Deterministic via fixed seed. Returns (lower, upper) rounded to 3 decimals,
    or (None, None) if values is empty. NOTE: this is scenario-bootstrap, NOT
    label-bootstrap — CIs assume gold labels are fixed; per REVIEW.md M4 and
    INDEPENDENT_REVIEW.md cardinal finding, label uncertainty likely dominates.
    """
    if not values:
        return (None, None)
    import random
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(n_bootstrap):
        sample_sum = 0.0
        for _ in range(n):
            sample_sum += values[rng.randint(0, n - 1)]
        means.append(sample_sum / n)
    means.sort()
    # Use (B-1) * alpha/2 indexing with bounds clamp; matches numpy method='lower'.
    # Clamp alpha to (0, 1) defensively so alpha=0 / alpha=1 do not IndexError.
    alpha_clamped = max(min(alpha, 0.999), 0.001)
    lo_idx = max(0, int((n_bootstrap - 1) * (alpha_clamped / 2)))
    hi_idx = min(n_bootstrap - 1, int((n_bootstrap - 1) * (1 - alpha_clamped / 2)))
    return (round(means[lo_idx], 3), round(means[hi_idx], 3))


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

    2026-05-17 addition: percentile-bootstrap 95% CIs on each mean metric
    (per REVIEW.md M2). NON-breaking: existing fields preserved; new
    fields are <metric>_ci95 = (lower, upper).
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
    cp_hits = [
        r["cp_hit_at_k"] for r in per_scenario if r.get("cp_hit_at_k") is not None
    ]
    n_cp_evaluable = len(cp_hits)
    return {
        "n_scenarios": n_total,
        "n_evaluable": n_evaluable,
        "n_with_expected_tags": n_evaluable,  # backward-compat alias
        "coverage_rate": round(coverage_rate, 3),
        "mean_hit_at_k": (
            round(sum(hits_at_k) / len(hits_at_k), 3) if hits_at_k else None
        ),
        "mean_hit_at_k_ci95": _bootstrap_ci(hits_at_k),
        "mean_tag_precision_at_k": (
            sum(tag_precs) / len(tag_precs) if tag_precs else None
        ),
        "mean_tag_precision_at_k_ci95": _bootstrap_ci(tag_precs),
        "mean_cp_hit_at_k": (
            round(sum(cp_hits) / n_cp_evaluable, 3) if cp_hits else None
        ),
        "mean_cp_hit_at_k_ci95": _bootstrap_ci(cp_hits),
        "n_cp_evaluable": n_cp_evaluable,
        "mean_top1_score": (
            sum(top1_scores) / len(top1_scores) if top1_scores else None
        ),
        "n_zero_hits": sum(1 for r in per_scenario if r["n_hits"] == 0),
        "wall_ms_total": round(sum(r["wall_ms"] for r in per_scenario), 1),
    }


def _row_id(row: dict) -> str | None:
    """Resolve row id, tolerating future schema rename to scenario_id (W11-F5)."""
    return row.get("id") or row.get("scenario_id")


def _render_diff_section(current, baseline_data):
    """Show per-scenario delta vs baseline.

    Highlights:
      * scenarios that gained hit@K (P@K improvement)
      * scenarios that lost hit@K (P@K regression)
      * scenarios that became / stopped being evaluable

    W9-C2: aggregate-only deltas can hide compositional shifts -- e.g.
    mean P@K dropping 0.600 -> 0.538 between baselines simply because
    15 newly-evaluable scenarios are harder. Per-scenario delta makes
    that visible so a future change that shrinks evaluable while raising
    mean P@K cannot masquerade as an improvement.

    W11-F5: also echo baseline aggregate metrics at the top so the reader
    can spot compositional shifts (newly_evaluable + newly_zero mass
    changing while per-scenario rows look unchanged).
    """
    baseline_by_id: dict[str, dict] = {}
    for r in baseline_data.get("per_scenario", []):
        rid = _row_id(r)
        if rid is None:
            print(
                "diff: skipping row without id/scenario_id",
                file=sys.stderr,
            )
            continue
        baseline_by_id[rid] = r

    lines = ["", "## Per-scenario delta vs baseline", ""]

    # W11-F5: echo baseline aggregate so compositional shifts are visible
    b_agg = baseline_data.get("aggregate") or {}
    agg_echoes: list[str] = []
    for key in (
        "mean_precision_at_5",
        "mean_top1_score",
        "mean_tag_precision",
        "mean_tag_precision_at_k",
        "mean_hit_at_k",
        "coverage_rate",
    ):
        if key in b_agg and b_agg[key] is not None:
            val = b_agg[key]
            try:
                agg_echoes.append(f"{key}={float(val):.3f}")
            except (TypeError, ValueError):
                agg_echoes.append(f"{key}={val}")
    if agg_echoes:
        lines.append(f"_Baseline aggregate_: {', '.join(agg_echoes)}")
        lines.append("")

    lines.append("| id | baseline P@K | current P@K | delta | status |")
    lines.append("|----|-------------:|------------:|------:|--------|")
    changes = {
        "improved": 0,
        "regressed": 0,
        "newly_evaluable": 0,
        "newly_zero": 0,
        "unchanged": 0,
    }
    missing_in_baseline = 0
    for cur in current:
        cur_id = _row_id(cur)
        if cur_id is None:
            print(
                "diff: skipping row without id/scenario_id",
                file=sys.stderr,
            )
            continue
        baseline = baseline_by_id.get(cur_id)
        if baseline is None:
            missing_in_baseline += 1
            continue
        b_p = baseline.get("tag_precision_at_k")
        c_p = cur.get("tag_precision_at_k")
        if b_p is None and c_p is not None:
            changes["newly_evaluable"] += 1
            status = "[+] newly evaluable"
        elif b_p is not None and c_p is None:
            changes["newly_zero"] += 1
            status = "[-] newly zero-hit"
        elif b_p is None and c_p is None:
            changes["unchanged"] += 1
            status = "."
        elif b_p == c_p:
            changes["unchanged"] += 1
            status = "."
        else:
            delta = (c_p or 0) - (b_p or 0)
            if delta > 0:
                changes["improved"] += 1
                status = f"[+] +{delta:.2f}"
            else:
                changes["regressed"] += 1
                status = f"[-] {delta:.2f}"
        b_str = f"{b_p:.2f}" if b_p is not None else "-"
        c_str = f"{c_p:.2f}" if c_p is not None else "-"
        d_str = (
            f"{(c_p or 0) - (b_p or 0):+.2f}"
            if (b_p is not None and c_p is not None)
            else "-"
        )
        lines.append(
            f"| `{cur_id}` | {b_str} | {c_str} | {d_str} | {status} |"
        )
    lines.append("")
    lines.append(
        f"**Summary**: {changes['improved']} improved, "
        f"{changes['regressed']} regressed, "
        f"{changes['newly_evaluable']} newly evaluable, "
        f"{changes['newly_zero']} newly zero-hit, "
        f"{changes['unchanged']} unchanged."
    )
    if missing_in_baseline:
        lines.append(
            f"_Note: {missing_in_baseline} current scenario(s) not present "
            f"in baseline -- excluded from delta table._"
        )
    return lines


def render_markdown(
    per_scenario, agg, *, mode, scenarios_path, diff_baseline=None
) -> str:
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
    if diff_baseline is not None:
        lines.extend(_render_diff_section(per_scenario, diff_baseline))
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
    parser.add_argument(
        "--diff",
        type=Path,
        default=None,
        help=(
            "Compare per-scenario results vs the supplied baseline.json. "
            "Markdown report includes a delta table (W9-C2)."
        ),
    )
    parser.add_argument(
        "--diff-required",
        action="store_true",
        help=(
            "When set, treat unreadable/missing --diff baseline as a hard "
            "error (exit 2). Default: warn to stderr and continue. (W11-F5)"
        ),
    )
    args = parser.parse_args(argv)

    if args.output is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        args.output = Path(f"/tmp/rag_eval_{args.mode}_{ts}.md")

    # W11-F5: load --diff baseline up-front so --diff-required can fail-fast
    # without waiting for the (slow) scoring pass to finish.
    diff_baseline = None
    if args.diff is not None:
        try:
            diff_baseline = json.loads(args.diff.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            if args.diff_required:
                print(
                    f"error: --diff-required set but baseline "
                    f"{args.diff} could not be loaded: {exc}",
                    file=sys.stderr,
                )
                return 2
            print(
                f"warning: could not load --diff baseline {args.diff}: {exc}",
                file=sys.stderr,
            )
            diff_baseline = None

    scenarios = load_scenarios(args.scenarios)
    per_scenario = [
        score_one(s, mode=args.mode, top_k=args.top_k) for s in scenarios
    ]
    agg = aggregate(per_scenario)

    md = render_markdown(
        per_scenario,
        agg,
        mode=args.mode,
        scenarios_path=args.scenarios,
        diff_baseline=diff_baseline,
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
