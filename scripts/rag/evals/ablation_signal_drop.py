#!/usr/bin/env python3
"""Signal-ablation diagnostic for the MLGG hybrid retrieval pipeline (W11-I1).

W10-T2 found ``mean_tag_precision@5 = 0.353`` for the production hybrid path
vs ``0.436`` for ``bm25_only`` across 30 scenarios. The hybrid stack fuses
four ranking signals (dense / bm25 / tag_overlap / severity) and then runs
MMR diversity re-ranking on top. We do not yet know which stage is the
*dilutor* of tag precision.

This script runs SIX configurations against
``references/retrieval_eval/scenarios.json`` and reports
``mean_tag_precision@5``, ``coverage@5``, and ``hit@K`` for each, plus the
delta against the ``bm25_only`` control:

    A. bm25_only       — legacy harness path, control.
    B. hybrid_all      — current production hybrid (control).
    C. hybrid_no_dense — hybrid with ``WEIGHT_DENSE = 0``.
    D. hybrid_no_tag   — hybrid with ``WEIGHT_TAG_OVERLAP = 0``.
    E. hybrid_no_sev   — hybrid with ``WEIGHT_SEVERITY = 0``.
    F. hybrid_no_mmr   — hybrid with ``MMR_LAMBDA = 1.0`` (passthrough
                          branch in ``_mmr_rerank`` skips diversity penalty;
                          ``MMR_COSINE_FLOOR`` also raised to 1.01 for
                          belt-and-braces in case the passthrough path is
                          ever rewritten).

We monkey-patch ``scripts.rag.config`` attributes *between* runs and restore
the originals immediately after each invocation so order does not matter.

The script is READ-ONLY with respect to ``scripts/rag/retrieval/*.py`` and
the KB / scenarios JSON files. It writes only ``/tmp/W11_I1_ablation.md``
(markdown summary) and ``/tmp/W11_I1_ablation.json`` (machine-readable
companion).

Usage::

    python3 scripts/rag/evals/ablation_signal_drop.py
    python3 scripts/rag/evals/ablation_signal_drop.py --scenarios path.json
    python3 scripts/rag/evals/ablation_signal_drop.py --help

Exits ``0`` on success, ``2`` if scenarios cannot be loaded.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

# Anchor the repo root on sys.path so ``scripts.rag.*`` imports work when
# the script is invoked directly (``python3 scripts/rag/evals/...``).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_SCENARIOS = _REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
DEFAULT_MD_OUT = Path("/tmp/W11_I1_ablation.md")
DEFAULT_JSON_OUT = Path("/tmp/W11_I1_ablation.json")
DEFAULT_TOP_K = 5

# ---------------------------------------------------------------------------
# Config-patching context
# ---------------------------------------------------------------------------


@contextmanager
def _patched_config(overrides: Dict[str, Any]) -> Iterator[None]:
    """Temporarily overwrite ``scripts.rag.config`` attributes.

    Restores the originals on exit even if the body raises. The hybrid
    ranker reads its constants via ``config.WEIGHT_DENSE`` (etc.) every
    call, so the patch takes effect for the next ``hybrid_rank`` invocation
    without requiring a module reload.

    Args:
        overrides: Mapping of ``config`` attribute name -> override value.
            Attributes that are not present on the module are added and
            removed (rather than restored) on exit.
    """
    cfg = importlib.import_module("scripts.rag.config")
    sentinel = object()
    originals: Dict[str, Any] = {}
    for name in overrides:
        originals[name] = getattr(cfg, name, sentinel)
    try:
        for name, value in overrides.items():
            setattr(cfg, name, value)
        yield
    finally:
        for name, old in originals.items():
            if old is sentinel:
                if hasattr(cfg, name):
                    delattr(cfg, name)
            else:
                setattr(cfg, name, old)


# ---------------------------------------------------------------------------
# Single-config eval
# ---------------------------------------------------------------------------


def _evaluate_under_config(
    scenarios: List[Dict[str, Any]],
    *,
    config_name: str,
    overrides: Dict[str, Any],
    mode: str,
    top_k: int,
) -> Dict[str, Any]:
    """Run the harness's ``evaluate_scenario`` for every scenario.

    Args:
        scenarios: Parsed list from ``scenarios.json``.
        config_name: Label used in the report (e.g. ``hybrid_no_tag``).
        overrides: Config attributes to patch for this run. Empty dict for
            controls that need no patching.
        mode: ``"bm25_only"`` or ``"hybrid"`` — passed to
            ``harness.evaluate_scenario``.
        top_k: ``top_k`` passed to the harness.

    Returns:
        Aggregate metrics dict ready to be appended to the report.
    """
    # Deferred import so the monkey-patch ordering of test_ablation_smoke
    # (which only imports this module for ``--help``) does not need to
    # touch sentence-transformers either.
    from scripts.rag.evals import harness as harness_mod

    with _patched_config(overrides):
        per_scenario = [
            harness_mod.evaluate_scenario(s, top_k=top_k, mode=mode)
            for s in scenarios
        ]

    total = len(per_scenario)
    coverage_rate = sum(s["coverage"] for s in per_scenario) / total
    hit_rate = sum(s["hit_at_k"] for s in per_scenario) / total
    mean_precision = sum(s["tag_precision"] for s in per_scenario) / total
    return {
        "config": config_name,
        "mode": mode,
        "overrides": overrides,
        "total_scenarios": total,
        "mean_tag_precision_at_5": round(mean_precision, 4),
        "coverage_rate": round(coverage_rate, 4),
        "hit_at_k_rate": round(hit_rate, 4),
        "per_scenario": per_scenario,
    }


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------


def _build_configurations() -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return the ordered list of (label, mode, overrides) tuples.

    Each override is applied via :func:`_patched_config` and restored when
    the run completes. ``hybrid_no_mmr`` zeroes the diversity-penalty path
    by setting ``MMR_LAMBDA = 1.0`` (which triggers the passthrough branch
    in ``_mmr_rerank``) and also pushes ``MMR_COSINE_FLOOR`` above any
    achievable cosine, so even a future rewrite of the passthrough check
    would not apply a diversity penalty.

    For the four hybrid_minus_* configurations we re-balance the remaining
    active weights to sum to 1.0; this matches the free-text rescaling
    pattern in ``hybrid_rank`` and keeps ``_final_score`` comparable across
    runs. (Without rebalancing, a weight-zeroed run would always score
    lower in absolute terms, which would not change ranking order but is
    pedagogically confusing in the printed report.)
    """
    from scripts.rag import config as cfg

    # Rebalanced weight bundles (sum to 1.0; preserves nominal-weight
    # ratios among the remaining signals). The original constants are
    # WEIGHT_DENSE=0.5 / WEIGHT_BM25=0.3 / WEIGHT_TAG_OVERLAP=0.15 /
    # WEIGHT_SEVERITY=0.05 (sum = 1.0).
    def _rebalance(zeroed_key: str) -> Dict[str, float]:
        weights = {
            "WEIGHT_DENSE": cfg.WEIGHT_DENSE,
            "WEIGHT_BM25": cfg.WEIGHT_BM25,
            "WEIGHT_TAG_OVERLAP": cfg.WEIGHT_TAG_OVERLAP,
            "WEIGHT_SEVERITY": cfg.WEIGHT_SEVERITY,
        }
        weights[zeroed_key] = 0.0
        s = sum(weights.values())
        if s <= 0.0:
            return weights
        return {k: v / s for k, v in weights.items()}

    return [
        ("A_bm25_only", "bm25_only", {}),
        ("B_hybrid_all", "hybrid", {}),
        ("C_hybrid_no_dense", "hybrid", _rebalance("WEIGHT_DENSE")),
        ("D_hybrid_no_tag", "hybrid", _rebalance("WEIGHT_TAG_OVERLAP")),
        ("E_hybrid_no_sev", "hybrid", _rebalance("WEIGHT_SEVERITY")),
        (
            "F_hybrid_no_mmr",
            "hybrid",
            {
                # lam >= 1.0 triggers the passthrough branch in
                # _mmr_rerank: pure relevance ordering, no diversity
                # penalty, but the same top_k truncation.
                "MMR_LAMBDA": 1.0,
                # Belt-and-braces: also push the cosine floor above any
                # achievable similarity in case future code paths rely
                # on the floor independently of MMR_LAMBDA.
                "MMR_COSINE_FLOOR": 1.01,
                "MMR_SAME_PAPER_PENALTY": 0.0,
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _format_markdown(results: List[Dict[str, Any]]) -> str:
    """Render the ablation results as a markdown report.

    Includes the metrics table and a short interpretation guide. The
    interpretation paragraph at the bottom is fixed text (the actual
    diagnosis lives in the agent's report to the orchestrator).
    """
    # Locate bm25_only and hybrid_all so we can compute deltas.
    by_label = {r["config"]: r for r in results}
    bm25 = by_label.get("A_bm25_only")
    hybrid_all = by_label.get("B_hybrid_all")

    bm25_p = bm25["mean_tag_precision_at_5"] if bm25 else float("nan")
    hybrid_p = hybrid_all["mean_tag_precision_at_5"] if hybrid_all else float("nan")

    lines: List[str] = []
    lines.append("# W11-I1 — Hybrid signal ablation")
    lines.append("")
    lines.append(
        f"Scenarios: `references/retrieval_eval/scenarios.json` "
        f"(n={results[0]['total_scenarios']})"
    )
    lines.append("")
    lines.append(
        "| config | mode | mean_tag_p@5 | coverage | hit@K | "
        "delta_vs_bm25 | delta_vs_hybrid_all |"
    )
    lines.append(
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"
    )
    for r in results:
        p5 = r["mean_tag_precision_at_5"]
        d_bm25 = (
            f"{p5 - bm25_p:+.4f}" if bm25 is not None else "n/a"
        )
        d_hybrid = (
            f"{p5 - hybrid_p:+.4f}" if hybrid_all is not None else "n/a"
        )
        lines.append(
            f"| {r['config']} | {r['mode']} | {p5:.4f} | "
            f"{r['coverage_rate']:.4f} | {r['hit_at_k_rate']:.4f} | "
            f"{d_bm25} | {d_hybrid} |"
        )

    lines.append("")
    lines.append("## Reading the table")
    lines.append("")
    lines.append(
        "- `delta_vs_bm25` < 0 means the configuration is WORSE than "
        "the bm25_only baseline on mean_tag_precision@5."
    )
    lines.append(
        "- `delta_vs_hybrid_all` > 0 means REMOVING that signal IMPROVES "
        "over the current production hybrid. The signal with the largest "
        "positive delta is the dilutor."
    )
    lines.append(
        "- All runs use the same scenarios, the same KB, and the same "
        "top_k=5. The only thing that changes between rows is the patched "
        "config attribute; weights are re-balanced to sum to 1.0 so the "
        "absolute `_final_score` magnitudes stay comparable."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Argparse / main
# ---------------------------------------------------------------------------


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Signal-ablation diagnostic for the MLGG hybrid retrieval "
            "stack. Runs 6 configurations against the scenarios file and "
            "writes a markdown + JSON report to /tmp/."
        )
    )
    p.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIOS,
        help="Scenarios JSON (default references/retrieval_eval/scenarios.json).",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Top-K passed to each evaluator (default 5).",
    )
    p.add_argument(
        "--md-out",
        type=Path,
        default=DEFAULT_MD_OUT,
        help="Markdown report output (default /tmp/W11_I1_ablation.md).",
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help="JSON report output (default /tmp/W11_I1_ablation.json).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-config stdout summary (markdown still printed).",
    )
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)

    scenarios_path = args.scenarios.expanduser().resolve()
    if not scenarios_path.exists():
        print(
            f"ERROR: scenarios file not found: {scenarios_path}",
            file=sys.stderr,
        )
        return 2
    with scenarios_path.open("r", encoding="utf-8") as fh:
        scenarios_data = json.load(fh)
    scenarios = scenarios_data.get("scenarios", [])
    if not scenarios:
        print("ERROR: scenarios list is empty", file=sys.stderr)
        return 2

    configurations = _build_configurations()
    results: List[Dict[str, Any]] = []
    for label, mode, overrides in configurations:
        if not args.quiet:
            print(
                f"[ablation] {label} mode={mode} overrides={overrides}",
                file=sys.stderr,
            )
        results.append(
            _evaluate_under_config(
                scenarios,
                config_name=label,
                overrides=overrides,
                mode=mode,
                top_k=args.top_k,
            )
        )

    md = _format_markdown(results)
    # Print the markdown to stdout so `| tee` produces a clean .md file.
    print(md)

    md_out = args.md_out.expanduser().resolve()
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(md, encoding="utf-8")

    json_out = args.json_out.expanduser().resolve()
    json_out.parent.mkdir(parents=True, exist_ok=True)
    # Strip per_scenario from JSON when it gets large? Keep it — eval
    # post-mortems frequently need the per-scenario breakdown. ~30 rows
    # is small.
    json_out.write_text(
        json.dumps(
            {
                "scenarios_file": str(scenarios_path),
                "top_k": args.top_k,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not args.quiet:
        print(f"[ablation] wrote {md_out}", file=sys.stderr)
        print(f"[ablation] wrote {json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
