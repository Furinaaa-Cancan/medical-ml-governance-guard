#!/usr/bin/env python3
"""
End-to-end evaluation harness for peer-review-kb retrieval.

Consumes a scenarios file (see references/retrieval_eval/scenarios.json)
where each scenario declares:

    gate_name          — the gate that would have failed
    failure_codes[]    — issue codes surfaced by that gate
    expected_categories[] — categories the reviewer would expect to see
    expected_tags[]    — tags the reviewer would expect to see
    query_text         — (optional) free-text query, used by hybrid mode

For each scenario it runs a retrieval call and scores the top-K
(default 5) results against the expectations:

    coverage = 1 if ANY of top-K concerns' category ∈ expected_categories
    precision = |top-K tags ∩ expected_tags| / |expected_tags|
    hit@K   = 1 if ANY top-K concern has ≥1 expected tag

This is NOT a unit test of retrieval internals — those live in
tests/test_peer_review_retrieval*.py. This answers the harder
question: "does the retrieval actually surface what a reviewer
would expect when a gate fails?"

## Retrieval-path modes (W3 measurement-path fix, 2026-05-17)

The harness supports two retrieval-path modes:

* ``bm25_only`` — direct ``retrieve_for_failure`` call. Measures
  BM25 keyword-overlap recall. Useful for BM25-specific debugging.
  THIS IS THE LEGACY DEFAULT — what every historical E1/H14/W3 P@5
  number measured.

* ``hybrid`` (DEFAULT) — production-path retrieval via the public
  ``rag_query`` API (dense + BM25 + tag overlap + severity + MMR).
  Measures what real users experience when a gate fails.

W3 (Wave 4) finding: the harness defaulted to ``bm25_only`` while
production users got ``hybrid_rank``. All published P@5 numbers
were therefore evaluating the wrong path. Default flipped to
``hybrid``; ``bm25_only`` retained for debugging.

## Mode comparison baseline (W3 Wave 4, 2026-05-17)

Mean tag_precision@5 across the canonical scenarios is captured in
the harness's --report JSON. Run both modes and compare:

    python3 scripts/rag/evals/harness.py --mode bm25_only \
        --report /tmp/eval_bm25_only.json
    python3 scripts/rag/evals/harness.py --mode hybrid \
        --report /tmp/eval_hybrid.json

The deltas live in the W3 diagnosis doc; numbers are not pinned in
this docstring because the KB and synonym tables move independently.

Run:
    python3 scripts/rag/evals/harness.py \
        --scenarios references/retrieval_eval/scenarios.json \
        --report /tmp/retrieval_eval_report.json \
        --baseline references/retrieval_eval/baseline.json \
        --strict

Strict mode fails (exit 2) if any scenario regresses below its baseline
coverage / hit@K / precision. Without --baseline the harness only
prints current numbers, which is useful for a first run.
"""
from __future__ import annotations

import argparse
import json
import sys as _sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure the repo root is on sys.path so ``scripts.rag.*`` imports work when
# this file is invoked directly via
# ``python3 scripts/rag/evals/harness.py``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
DEFAULT_KB = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

# Default retrieval mode. W3 found that the legacy ``bm25_only`` default
# measured the wrong path; production users get ``hybrid``. New default
# matches the production path so future evals are not misleading.
DEFAULT_MODE = "hybrid"
SUPPORTED_MODES = ("bm25_only", "hybrid")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    # NOTE: default=None (not DEFAULT_KB) so we can distinguish
    # "user explicitly passed --kb" from "fell through to default".
    # The default is materialized in main() after the mode-mismatch
    # warning check. (W14-F3.)
    p.add_argument("--kb", type=Path, default=None,
                   help="Override KB path (bm25_only mode only; the hybrid "
                        "path resolves the KB via scripts.rag.config). "
                        "Passing --kb with --mode hybrid warns to stderr "
                        "since the flag is a no-op on that path.")
    p.add_argument("--mode", choices=SUPPORTED_MODES, default=DEFAULT_MODE,
                   help="Retrieval path to evaluate. Default 'hybrid' "
                        "matches the production user experience (rag_query "
                        "→ hybrid_rank: dense + BM25 + tag + severity + "
                        "MMR). 'bm25_only' is the legacy path retained "
                        "for BM25-specific debugging — W3 (2026-05-17) "
                        "found it had been the misleading default.")
    p.add_argument("--report", type=Path,
                   help="Optional JSON report output path")
    p.add_argument("--baseline", type=Path,
                   help="Optional baseline JSON; --strict regresses against "
                        "it. If the path is given but does not exist the "
                        "harness exits 2 (W14-F3, mirrors W11-F5 --diff).")
    p.add_argument("--top-k", type=int, default=5,
                   help="Top-K to retrieve per scenario (default 5)")
    p.add_argument("--strict", action="store_true",
                   help="Exit 2 if any scenario regresses or misses hit@K")
    p.add_argument("--verbose", action="store_true",
                   help="Print per-scenario top-K details")
    args = p.parse_args()

    # ── Fail-loud validation (W14-F3) ──────────────────────────────
    # 1. --baseline: if explicitly given, the path MUST exist. The
    #    pre-W14 behavior printed "BASELINE: ... missing" to stdout
    #    then exited 0, hiding CI config drift the same way that
    #    bit run_eval --diff (fixed in W11-F5).
    if args.baseline is not None:
        baseline_resolved = Path(args.baseline).expanduser().resolve()
        if not baseline_resolved.exists():
            p.error(
                f"--baseline path does not exist: {baseline_resolved}"
            )

    # 2. --kb: if explicitly given AND mode is hybrid, warn to stderr.
    #    The hybrid path resolves the KB via scripts.rag.config and
    #    ignores --kb entirely; pre-W14 we silently accepted the flag
    #    so users thought they were targeting a custom KB but were
    #    actually hitting the prebuilt index.
    #    Also: if --kb path is missing, fail loud regardless of mode
    #    (this catches the W13-A0 universal fail-loud probe).
    if args.kb is not None:
        kb_resolved = Path(args.kb).expanduser().resolve()
        if not kb_resolved.exists():
            p.error(f"--kb path does not exist: {kb_resolved}")
        if args.mode == "hybrid":
            print(
                "WARN: --kb is ignored in --mode hybrid (uses prebuilt "
                "dense index resolved via scripts.rag.config). Use "
                "--mode bm25_only to load a custom KB.",
                file=_sys.stderr,
            )
    # Materialize the default after validation so downstream code
    # always sees a real path.
    if args.kb is None:
        args.kb = DEFAULT_KB

    return args


def _retrieve_bm25_only(
    scenario: Dict[str, Any],
    *,
    kb_path: Path,
    top_k: int,
) -> List[Dict[str, Any]]:
    """Legacy BM25-only retrieval path.

    Calls ``retrieve_for_failure`` directly. Measures BM25 keyword-
    overlap recall — useful for BM25-specific debugging but does NOT
    reflect what production users experience (W3 finding).
    """
    # Deferred import: avoids loading sentence_transformers on import
    # of this module when only bm25 mode is used, and keeps the
    # hybrid-import deferred symmetrically.
    from scripts.rag.retrieval.bm25 import retrieve_for_failure
    return retrieve_for_failure(
        scenario["gate_name"],
        scenario.get("failure_codes", []),
        limit=top_k,
        kb_path=kb_path,
    )


def _retrieve_hybrid(
    scenario: Dict[str, Any],
    *,
    top_k: int,
) -> List[Dict[str, Any]]:
    """Production-path retrieval via the public ``rag_query`` API.

    Uses ``query_text`` if present (H10 scenarios provide it). Falls
    back to a gate + code descriptor so legacy scenarios without a
    free-text query still get a meaningful dense signal.

    Note: ``rag_query`` resolves the KB via ``scripts.rag.config``
    rather than an explicit path. The ``--kb`` flag therefore only
    affects ``bm25_only`` mode. This is intentional — the production
    user's retrieval never takes an ad-hoc KB path either.
    """
    from scripts.rag.query import rag_query

    query_text = scenario.get("query_text") or scenario.get("query") or ""
    if not query_text.strip():
        # Synthesize a minimal descriptor so the dense signal is non-empty.
        # Mirrors what gate_rag_bridge does when a gate fails without a
        # human-authored query.
        gate = scenario.get("gate_name", "")
        codes = scenario.get("failure_codes", [])
        query_text = f"{gate} {' '.join(codes)}".strip()

    return rag_query(
        query=query_text,
        gate=scenario["gate_name"],
        failure_codes=scenario.get("failure_codes", []),
        top_k=top_k,
    )


def evaluate_scenario(
    scenario: Dict[str, Any],
    *,
    kb_path: Path = DEFAULT_KB,
    top_k: int = 5,
    mode: str = DEFAULT_MODE,
) -> Dict[str, Any]:
    """Evaluate a single scenario against the chosen retrieval path.

    Args:
        scenario: Scenario dict (see module docstring for the schema).
        kb_path: KB path. Only honored in ``bm25_only`` mode; the
            ``hybrid`` mode resolves the KB via ``scripts.rag.config``.
        top_k: Number of top results to retrieve and score.
        mode: ``"hybrid"`` (default, production path) or ``"bm25_only"``
            (legacy debug path).

    Returns:
        A per-scenario result dict with coverage / hit@K / tag_precision
        plus a top-K summary.
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"mode must be one of {SUPPORTED_MODES}, got {mode!r}"
        )

    gate = scenario["gate_name"]
    expected_cats = set(scenario.get("expected_categories", []))
    expected_tags = set(scenario.get("expected_tags", []))

    if mode == "bm25_only":
        results = _retrieve_bm25_only(
            scenario, kb_path=kb_path, top_k=top_k,
        )
    else:  # hybrid
        results = _retrieve_hybrid(scenario, top_k=top_k)

    hit_categories: List[str] = []
    hit_tags: List[str] = []
    retrieved_summary: List[Dict[str, Any]] = []

    for r in results:
        cat = r.get("category")
        tags = [t for t in r.get("tags", []) if isinstance(t, str)]
        if cat in expected_cats:
            hit_categories.append(cat)
        for t in tags:
            if t in expected_tags:
                hit_tags.append(t)
        retrieved_summary.append({
            "concern_id": r.get("concern_id"),
            "paper_id": r.get("_paper_id") or r.get("paper_id"),
            "severity": r.get("severity"),
            "category": cat,
            "tags": tags,
            # bm25 path tags this; hybrid path leaves it None. Both are fine.
            "retrieval_mode": r.get("_retrieval_mode"),
            # Hybrid-only scoring metadata (handy for debugging).
            "final_score": r.get("_final_score"),
            "dense_score": r.get("_dense_score"),
            "bm25_score": r.get("_bm25_score"),
        })

    coverage = 1.0 if hit_categories else 0.0
    hit_at_k = 1.0 if hit_tags else 0.0
    # Precision = fraction of expected tags that appeared in top-K.
    # Compute against unique expected tags (not total occurrences) so
    # the number is bounded in [0,1] and easy to interpret.
    unique_hits = set(hit_tags) & expected_tags
    tag_precision = (
        len(unique_hits) / len(expected_tags) if expected_tags else 0.0
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "description": scenario.get("description", ""),
        "gate_name": gate,
        "mode": mode,
        "retrieved_count": len(results),
        "coverage": coverage,
        "hit_at_k": hit_at_k,
        "tag_precision": round(tag_precision, 3),
        "matched_expected_categories": sorted(set(hit_categories)),
        "matched_expected_tags": sorted(unique_hits),
        "top_k_summary": retrieved_summary,
    }


def print_human_summary(
    report: Dict[str, Any], *, verbose: bool = False,
) -> None:
    print("=" * 70)
    mode = report.get("mode", "?")
    print(f"Retrieval eval harness — peer-review-kb   [mode={mode}]")
    print("=" * 70)
    for r in report["scenarios"]:
        mark_cov = "OK" if r["coverage"] >= 1.0 else "MISS"
        mark_hit = "OK" if r["hit_at_k"] >= 1.0 else "MISS"
        print(f"\n  [{r['scenario_id']}] gate={r['gate_name']}")
        print(f"    retrieved: {r['retrieved_count']}  "
              f"coverage(category): {r['coverage']:.0f} [{mark_cov}]  "
              f"hit@K(tag): {r['hit_at_k']:.0f} [{mark_hit}]  "
              f"tag_precision: {r['tag_precision']:.3f}")
        if r["matched_expected_categories"]:
            print(f"    matched category : {r['matched_expected_categories']}")
        if r["matched_expected_tags"]:
            print(f"    matched tags     : {r['matched_expected_tags']}")
        if verbose:
            for i, c in enumerate(r["top_k_summary"], 1):
                print(f"      {i}. {c['concern_id']} ({c['paper_id']}, "
                      f"{c['severity']}) [{c['category']}] "
                      f"mode={c['retrieval_mode']}")
                print(f"         tags: {c['tags'][:6]}")
    agg = report["aggregate"]
    print("\n" + "-" * 70)
    print(f"  Aggregate: coverage={agg['coverage_rate']:.2f} "
          f"hit@K={agg['hit_at_k_rate']:.2f} "
          f"mean_tag_precision={agg['mean_tag_precision']:.3f} "
          f"scenarios={agg['total_scenarios']}")
    print("=" * 70)


def check_regression(
    current: Dict[str, Any],
    baseline: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a list of regression entries. Empty list = no regression."""
    regressions: List[Dict[str, Any]] = []
    baseline_by_id = {s["scenario_id"]: s for s in baseline["scenarios"]}
    for s in current["scenarios"]:
        b = baseline_by_id.get(s["scenario_id"])
        if b is None:
            # New scenario → no baseline to regress against, skip.
            continue
        if s["coverage"] < b["coverage"]:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "coverage",
                "baseline": b["coverage"],
                "current": s["coverage"],
            })
        if s["hit_at_k"] < b["hit_at_k"]:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "hit_at_k",
                "baseline": b["hit_at_k"],
                "current": s["hit_at_k"],
            })
        # Allow tag_precision to move slightly (floor at baseline − 0.05)
        # to avoid noise from minor KB rewording that shifts token matches.
        if s["tag_precision"] < b["tag_precision"] - 0.05:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "tag_precision",
                "baseline": b["tag_precision"],
                "current": s["tag_precision"],
            })
    return regressions


def main() -> int:
    args = parse_args()

    scenarios_path = Path(args.scenarios).expanduser().resolve()
    if not scenarios_path.exists():
        print(f"ERROR: scenarios file not found: {scenarios_path}",
              file=_sys.stderr)
        return 2
    with scenarios_path.open("r", encoding="utf-8") as fh:
        scenarios_data = json.load(fh)
    scenarios = scenarios_data.get("scenarios", [])
    if not scenarios:
        print("ERROR: scenarios list is empty", file=_sys.stderr)
        return 2

    kb_path = Path(args.kb).expanduser().resolve()

    per_scenario = [
        evaluate_scenario(
            s, kb_path=kb_path, top_k=args.top_k, mode=args.mode,
        )
        for s in scenarios
    ]
    total = len(per_scenario)
    coverage_rate = sum(s["coverage"] for s in per_scenario) / total
    hit_rate = sum(s["hit_at_k"] for s in per_scenario) / total
    mean_precision = (
        sum(s["tag_precision"] for s in per_scenario) / total
    )
    report = {
        "scenarios_file": str(scenarios_path),
        "kb_path": str(kb_path),
        "top_k": args.top_k,
        "mode": args.mode,
        "scenarios": per_scenario,
        "aggregate": {
            "total_scenarios": total,
            "coverage_rate": round(coverage_rate, 3),
            "hit_at_k_rate": round(hit_rate, 3),
            "mean_tag_precision": round(mean_precision, 3),
        },
    }

    print_human_summary(report, verbose=args.verbose)

    # Optional: persist.
    if args.report:
        out = Path(args.report).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Optional: regression check against baseline.
    # Path existence is enforced in parse_args() (W14-F3) so by the
    # time we get here, args.baseline is either None or a real file.
    regressions: List[Dict[str, Any]] = []
    if args.baseline:
        baseline_path = Path(args.baseline).expanduser().resolve()
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            regressions = check_regression(report, baseline)
            if regressions:
                print("\nREGRESSIONS vs baseline:")
                for r in regressions:
                    print(f"  [{r['scenario_id']}] {r['metric']}: "
                          f"{r['baseline']} → {r['current']}")
        except Exception as exc:
            print(f"ERROR: baseline unreadable: {exc}",
                  file=_sys.stderr)
            return 2

    if args.strict:
        # Fail-closed conditions: any regression, or any scenario missing
        # hit@K entirely (if baseline didn't exist, we still enforce the
        # minimum "at least 1 top-K concern matched an expected tag").
        if regressions:
            return 2
        for s in per_scenario:
            if s["hit_at_k"] < 1.0:
                print(f"\nSTRICT FAIL: scenario '{s['scenario_id']}' has "
                      f"hit@K=0 — top-{args.top_k} concerns matched no "
                      f"expected tag.", file=_sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
