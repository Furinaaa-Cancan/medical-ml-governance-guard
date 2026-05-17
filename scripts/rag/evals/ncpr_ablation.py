#!/usr/bin/env python3
"""NCPR-v2 component ablation harness (W23-C4).

Sibling-level analogue of W11-I1's signal ablation (which dissects
retrieval-stage weights). Where W11-I1 asks "which ranking signal is
the dilutor inside hybrid retrieval?", this harness asks the
*benchmark-level* question: when we put the whole NCPR pipeline on the
holdout, **what does each component contribute?** Is end-to-end better
than just dropping retrieval into the matcher? Does the semantic
matcher pay rent? Does category fallback help recall?

Why this exists (NCPR v2 wave)
------------------------------
NCPR v2 (W23-B1) hardens the v1 benchmark but does NOT change the
matcher precedence (exact_code > code_prefix > semantic > category) or
the RAG synth top-K. The pipeline as a whole is now solid; the next
question is internal accounting — which slice of the pipeline is doing
the work?

Ablation grid (defaults)
------------------------
``full``               full pipeline + matcher + scoring (baseline).
``retrieval_only``     skip MLGG-style flag synthesis; pass raw RAG
                       records straight through to the scorer with the
                       weakest sensible flag shape.
``no_semantic_match``  matcher restricted to ``exact_code`` +
                       ``code_prefix`` (semantic + category disabled).
``no_category_match``  matcher restricted to non-``category`` types
                       (exact_code + code_prefix + semantic only).
``top_k_5``            full pipeline, ``synthesize_flags_from_rag``
                       top_k=5.
``top_k_10``           top_k=10.
``top_k_30``           top_k=30.

Each config returns one dict:
``{weighted_f1, recall, precision, category_coverage}`` (macro means).
The report writer prints a markdown table with deltas vs ``full``.

Stub-fallback contract
----------------------
Every sibling import is wrapped in ``try / except ImportError`` with a
documented, deterministic stub. The same pattern as W22-X6's
orchestrator; mirrors that module's ``_STUBBED`` accumulator so a
caller can see when any ablation row was produced against a stub
rather than the real sibling (which would silently lie about deltas).

Hard rules honored
------------------
* NEW files only (this module + its test).
* No package installs; pure-stdlib + numpy if the real matcher loads.
* No mutation of holdout / KB on disk.
* All file writes go through Path.write_text + parents=True.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

__all__ = [
    "DEFAULT_CONFIGS",
    "run_ablation",
    "write_ablation_report",
    "_STUBBED",
]


# ── Default ablation grid ───────────────────────────────────────────────────

DEFAULT_CONFIGS: list[str] = [
    "full",
    "retrieval_only",
    "no_semantic_match",
    "no_category_match",
    "top_k_5",
    "top_k_10",
    "top_k_30",
]


# ── Sibling imports with stubs ──────────────────────────────────────────────
#
# Each ``try / except ImportError`` either binds the real sibling or a
# documented stub. ``_STUBBED`` accumulates the stub names so the
# report can flag any run that exercised a stub.

_STUBBED: list[str] = []

try:
    from scripts.rag.evals.ncpr_matcher import match_all as _real_match_all  # type: ignore  # noqa: E501
except ImportError:  # pragma: no cover - exercised only when X1 missing
    _STUBBED.append("ncpr_matcher")
    _real_match_all = None  # type: ignore[assignment]

try:
    from scripts.rag.evals.ncpr_severity_score import (  # type: ignore
        per_paper_score as _per_paper_score,
    )
except ImportError:  # pragma: no cover
    _STUBBED.append("ncpr_severity_score")

    def _per_paper_score(  # type: ignore[no-redef]
        paper_id: str,
        flags: list[dict],
        concerns: list[dict],
        embed_fn: Optional[Callable] = None,
    ) -> dict:
        """Stub: uniform-severity cardinal P/R/F1 from a fresh stub match.

        Mirrors run_ncpr_benchmark._per_paper_score's stub: keeps the
        orchestrator wiring exercisable, but does not weight by severity.
        """
        # Local mini-match: exact code only — keeps the stub honest.
        matched = 0
        used_concerns: set[int] = set()
        for f in flags:
            code = (f.get("code") or "").strip().lower()
            if not code:
                continue
            for i, c in enumerate(concerns):
                if i in used_concerns:
                    continue
                gates = [(g or "").strip().lower()
                         for g in c.get("mlgg_gates") or []]
                if code in gates:
                    matched += 1
                    used_concerns.add(i)
                    break
        n_c, n_f = len(concerns), len(flags)
        recall = matched / n_c if n_c else 0.0
        precision = matched / n_f if n_f else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return {
            "paper_id": paper_id,
            "n_flags": n_f,
            "n_concerns": n_c,
            "matcher": "stub",
            "totals": {
                "wTP": float(matched),
                "wFN": float(n_c - matched),
                "wFP": float(n_f - matched),
                "wPrecision": precision,
                "wRecall": recall,
                "weighted_f1": f1,
            },
            "per_severity": {},
            "paper_excluded": n_c == 0,
        }

try:
    from scripts.rag.evals.ncpr_category_coverage import (  # type: ignore
        category_coverage as _category_coverage,
    )
except ImportError:  # pragma: no cover
    _STUBBED.append("ncpr_category_coverage")

    _STUB_CATS = ("evaluation", "design", "reporting", "external_val", "leakage")

    def _category_coverage(  # type: ignore[no-redef]
        flags: list[dict],
        concerns: list[dict],
    ) -> dict:
        """Stub: fraction of 5 categories where both sides have items."""
        flag_cats = {(f.get("category") or "").strip().lower() for f in flags}
        concern_cats = {
            (c.get("dimension") or c.get("category") or "").strip().lower()
            for c in concerns
        }
        cov = {c: (c in flag_cats and c in concern_cats) for c in _STUB_CATS}
        return {
            "coverage_per_category": cov,
            "coverage_rate": sum(cov.values()) / len(_STUB_CATS),
            "missed_categories": sorted(
                c for c in _STUB_CATS
                if c in concern_cats and c not in flag_cats
            ),
        }

try:
    from scripts.rag.evals.ncpr_paper_runner import (  # type: ignore
        synthesize_flags_from_rag as _synthesize_flags_from_rag,
    )
except ImportError:  # pragma: no cover
    _STUBBED.append("ncpr_paper_runner")

    def _synthesize_flags_from_rag(  # type: ignore[no-redef]
        query: str, top_k: int = 20
    ) -> list[dict]:
        """Stub: emit zero flags so ablation row is meaningfully zero."""
        return []


# ── Ablation-specific match_all wrappers ────────────────────────────────────
#
# We do NOT mutate the real matcher; instead we filter its output to
# simulate dropping a match type. For ``no_semantic_match`` we drop
# matched_pairs of type {semantic, category}; for ``no_category_match``
# we drop only category. The scorer then treats the dropped pairs as
# false-negatives (concerns) and false-positives (flags), which is
# exactly what disabling that match type at the matcher would produce.
#
# Why filter rather than re-implement: the real matcher's precedence
# logic is complex (best-pair de-duplication per concern, per spec
# §3.4); re-implementing a "matcher minus type X" risks subtle
# divergence from the production scoring contract. Filtering keeps the
# ablation a strict subset of the real matcher's output.


def _make_match_filter(
    drop_types: tuple[str, ...],
) -> Optional[Callable]:
    """Return a ``match_all`` wrapper that hides certain match types.

    Args:
        drop_types: Match-type names to *suppress* (e.g.
            ``("semantic", "category")``). Suppressed pairs are removed
            from ``matched_pairs``; the corresponding flag and concern
            indices are added back to ``unmatched_*`` so the scorer
            sees them as misses.

    Returns:
        ``None`` if the real matcher is unavailable — caller must fall
        back to the stub scorer which does not honour this knob.
    """
    if _real_match_all is None:
        return None

    def _wrapped(flags, concerns, embed_fn=None):
        try:
            raw = _real_match_all(flags, concerns, embed_fn=embed_fn)
        except TypeError:
            raw = _real_match_all(flags, concerns)
        kept_pairs = []
        for p in raw.get("matched_pairs", []) or []:
            mtype = p.get("type") if isinstance(p, dict) else None
            if mtype in drop_types:
                continue
            kept_pairs.append(p)
        kept_flag_idx = {
            p.get("flag_idx") for p in kept_pairs if isinstance(p, dict)
        }
        kept_concern_idx = {
            p.get("concern_idx") for p in kept_pairs if isinstance(p, dict)
        }
        n_f = len(flags)
        n_c = len(concerns)
        return {
            "matched_pairs": kept_pairs,
            "unmatched_flags": [
                j for j in range(n_f) if j not in kept_flag_idx
            ],
            "unmatched_concerns": [
                i for i in range(n_c) if i not in kept_concern_idx
            ],
            "matcher": f"filtered:{','.join(drop_types) or 'none'}",
        }

    return _wrapped


# ── Config -> per-paper invocation strategy ────────────────────────────────


def _per_paper_with_matcher(
    paper_id: str,
    flags: list[dict],
    concerns: list[dict],
    matcher: Optional[Callable],
) -> dict:
    """Score one paper, optionally injecting a filtered matcher.

    Routes through the real ``per_paper_score`` whenever possible so
    severity weighting is honoured. The matcher injection point is
    ``scripts.rag.evals.ncpr_matcher.match_all`` — we temporarily
    monkey-patch the module attribute around the scoring call. This
    mirrors how W11-I1 patches ``scripts.rag.config`` between
    invocations: minimum surface change, restored on exit.

    If the real severity scorer is unavailable (stub branch), the
    matcher swap is a no-op — the stub doesn't go through X1 at all,
    so the ablation row collapses to the stub's behaviour. The report
    surfaces this via ``_STUBBED``.
    """
    if matcher is None or "ncpr_severity_score" in _STUBBED:
        return _per_paper_score(paper_id, flags, concerns)

    import scripts.rag.evals.ncpr_matcher as _x1_mod  # type: ignore
    sentinel = object()
    original = getattr(_x1_mod, "match_all", sentinel)
    try:
        _x1_mod.match_all = matcher  # type: ignore[attr-defined]
        return _per_paper_score(paper_id, flags, concerns)
    finally:
        if original is sentinel:  # pragma: no cover - defensive
            if hasattr(_x1_mod, "match_all"):
                delattr(_x1_mod, "match_all")
        else:
            _x1_mod.match_all = original  # type: ignore[attr-defined]


def _retrieval_only_flags(query: str, top_k: int) -> list[dict]:
    """Bypass the MLGG flag-shape mapping; pass raw RAG records through.

    The RAG retriever returns concern-like dicts; ``ncpr_paper_runner``
    normally re-shapes each into an ``MlggFlag`` with a synthesized
    ``code`` so the matcher's exact_code / code_prefix steps can fire.
    The ``retrieval_only`` config strips that synthesis: each flag
    keeps only ``evidence_text`` + ``category`` (best-effort), with no
    code. Result: the matcher's exact_code / code_prefix paths can
    never fire on these flags, leaving only semantic + category — i.e.
    the contribution attributable to *retrieval alone*, without the
    MLGG flag-synthesis layer.

    Implementation: query the same RAG pathway (or stub) and degrade
    the records, rather than reaching into the retriever directly.
    Keeps the ablation insulated from retriever signature drift.
    """
    if not isinstance(query, str) or not query.strip():
        return []
    raw = _synthesize_flags_from_rag(query, top_k=top_k)
    degraded: list[dict] = []
    for r in raw or []:
        degraded.append({
            "code": "",  # forces matcher to skip exact / prefix paths
            "severity": (r.get("severity") or "MEDIUM"),
            "category": (r.get("category") or "uncategorized"),
            "evidence_text": (r.get("evidence_text") or ""),
        })
    return degraded


def _evaluate_one_config(
    *,
    config: str,
    holdout: list[dict],
    kb_index: dict[str, list[dict]],
) -> dict:
    """Run all papers through one config, return the headline metric dict.

    Macro-averages across papers (each paper counts equally), matching
    NCPR v1/v2 spec §5.
    """
    top_k = 20
    matcher: Optional[Callable] = None
    flag_synth: Callable[[str, int], list[dict]] = _synthesize_flags_from_rag

    if config == "full":
        pass
    elif config == "retrieval_only":
        flag_synth = _retrieval_only_flags
    elif config == "no_semantic_match":
        matcher = _make_match_filter(("semantic", "category"))
    elif config == "no_category_match":
        matcher = _make_match_filter(("category",))
    elif config == "top_k_5":
        top_k = 5
    elif config == "top_k_10":
        top_k = 10
    elif config == "top_k_30":
        top_k = 30
    else:
        raise ValueError(
            f"unknown ablation config: {config!r} "
            f"(known: {DEFAULT_CONFIGS})"
        )

    f1s: list[float] = []
    precisions: list[float] = []
    recalls: list[float] = []
    coverages: list[float] = []
    n_papers_scored = 0
    for paper in holdout:
        paper_id = str(
            paper.get("paper_id")
            or paper.get("id")
            or paper.get("paper_doi")
            or "<unknown>"
        )
        # Look up concerns from the supplied KB index. Empty -> excluded.
        concerns = kb_index.get(paper_id, []) or []
        if not concerns:
            doi = paper.get("paper_doi") or paper.get("doi")
            if doi:
                concerns = kb_index.get(str(doi), []) or []

        query = _paper_query_text(paper)
        flags = flag_synth(query, top_k)

        score = _per_paper_with_matcher(paper_id, flags, concerns, matcher)
        if score.get("paper_excluded"):
            continue
        n_papers_scored += 1
        totals = score.get("totals", {}) or {}
        f1s.append(float(totals.get("weighted_f1", 0.0)))
        precisions.append(float(totals.get("wPrecision", 0.0)))
        recalls.append(float(totals.get("wRecall", 0.0)))

        cov = _category_coverage(flags, concerns)
        coverages.append(float(cov.get("coverage_rate", 0.0)))

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "weighted_f1": _mean(f1s),
        "recall": _mean(recalls),
        "precision": _mean(precisions),
        "category_coverage": _mean(coverages),
        "n_papers": n_papers_scored,
    }


def _paper_query_text(paper: dict) -> str:
    """Mirror run_ncpr_benchmark._paper_query_text — pick methods_text first.

    Duplicating the helper here (rather than importing) keeps the
    ablation harness's import graph tight enough that
    ``run_ncpr_benchmark``'s argparse machinery does not run on import.
    """
    for key in ("methods_text", "abstract", "summary"):
        v = paper.get(key)
        if isinstance(v, str) and v.strip():
            return v
    parts = [str(paper.get(k, "")) for k in ("title", "paper_title", "paper_id")]
    return " ".join(p for p in parts if p).strip()


def _build_kb_index(kb_entries: list[dict]) -> dict[str, list[dict]]:
    """Index peer-review-kb entries by paper_id + DOI for O(1) lookup."""
    idx: dict[str, list[dict]] = {}
    for entry in kb_entries or []:
        concerns = list(entry.get("reviewer_concerns", []) or [])
        for key in ("paper_id", "id", "paper_doi", "doi"):
            v = entry.get(key)
            if isinstance(v, str) and v:
                idx.setdefault(v, concerns)
    return idx


# ── Public API ──────────────────────────────────────────────────────────────


def run_ablation(
    holdout: list,
    configs: Optional[list[str]] = None,
    *,
    kb_entries: Optional[list[dict]] = None,
) -> dict:
    """Run NCPR-v2 against the holdout under each ablation config.

    Args:
        holdout: List of paper dicts. Empty list returns an empty
            ``{}`` (no-op), letting callers chain this on filtered
            subsets without special-casing.
        configs: Ablation configs to run (default: all of
            :data:`DEFAULT_CONFIGS`). Unknown configs raise
            ``ValueError`` so a typo never silently degrades to a
            "full" run.
        kb_entries: Optional peer-review-kb ``entries`` list. When
            omitted, the harness reads from
            ``references/case-studies/peer-review-kb.json`` if
            present; otherwise treats every paper as having no
            reviewer concerns (-> ``paper_excluded=True``).

    Returns:
        ``{config: {weighted_f1, recall, precision, category_coverage,
        n_papers}}``. The headline interface (weighted_f1 / recall /
        precision / category_coverage) matches the task spec; the
        extra ``n_papers`` is included so the report can footnote how
        many papers were actually scored per config (e.g. zero if
        every paper was excluded by an empty KB).
    """
    if not isinstance(holdout, list):
        raise TypeError(
            f"holdout must be list, got {type(holdout).__name__}"
        )
    if not holdout:
        return {}

    chosen = configs if configs is not None else list(DEFAULT_CONFIGS)
    # Validate up-front so a partial run does not produce a half-table.
    for c in chosen:
        if c not in DEFAULT_CONFIGS:
            raise ValueError(
                f"unknown ablation config: {c!r} "
                f"(known: {DEFAULT_CONFIGS})"
            )

    if kb_entries is None:
        kb_path = (
            REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"
        )
        if kb_path.exists():
            try:
                data = json.loads(kb_path.read_text())
                if isinstance(data, dict) and "entries" in data:
                    kb_entries = list(data["entries"])
                elif isinstance(data, list):
                    kb_entries = data
                else:
                    kb_entries = []
            except (OSError, ValueError):
                kb_entries = []
        else:
            kb_entries = []

    kb_index = _build_kb_index(kb_entries)

    results: dict[str, dict] = {}
    for c in chosen:
        results[c] = _evaluate_one_config(
            config=c, holdout=holdout, kb_index=kb_index
        )
    return results


def write_ablation_report(results: dict, out_path: Path) -> None:
    """Render the ablation results as a markdown table with deltas vs baseline.

    Empty ``results`` writes a one-line "no configs scored" file (still
    a valid markdown document) rather than raising, so a CI pipeline
    that drives this from an empty holdout produces a real artifact
    instead of a stack trace.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not results:
        out_path.write_text(
            "# NCPR v2 component ablation (W23-C4)\n\n"
            "_No configs scored. Holdout was empty._\n",
            encoding="utf-8",
        )
        return

    baseline = results.get("full") or next(iter(results.values()))

    def _fmt(x: float) -> str:
        try:
            return f"{float(x):.4f}"
        except (TypeError, ValueError):
            return "n/a"

    def _delta(metric: str, row: dict) -> str:
        try:
            return f"{float(row[metric]) - float(baseline[metric]):+.4f}"
        except (KeyError, TypeError, ValueError):
            return "n/a"

    lines: list[str] = []
    lines.append("# NCPR v2 component ablation (W23-C4)")
    lines.append("")
    lines.append(
        f"Baseline: `full` (n_papers={baseline.get('n_papers', 0)}). "
        f"Deltas below are `config - full` for each metric."
    )
    if _STUBBED:
        lines.append("")
        lines.append(
            f"WARNING: stubbed siblings exercised — {sorted(set(_STUBBED))}. "
            f"Numbers below are NOT publication-grade."
        )
    lines.append("")
    lines.append(
        "| config | n_papers | weighted_f1 | recall | precision | "
        "category_coverage | dF1 | dRecall | dPrecision | dCov |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for cfg, row in results.items():
        lines.append(
            f"| {cfg} | {row.get('n_papers', 0)} | "
            f"{_fmt(row.get('weighted_f1', 0.0))} | "
            f"{_fmt(row.get('recall', 0.0))} | "
            f"{_fmt(row.get('precision', 0.0))} | "
            f"{_fmt(row.get('category_coverage', 0.0))} | "
            f"{_delta('weighted_f1', row)} | "
            f"{_delta('recall', row)} | "
            f"{_delta('precision', row)} | "
            f"{_delta('category_coverage', row)} |"
        )

    lines.append("")
    lines.append("## Reading the table")
    lines.append("")
    lines.append(
        "- `dF1 > 0` means the ablation OUTPERFORMS the full pipeline on "
        "macro weighted F1 — that component is a *dilutor* of headline "
        "score (rare; usually means a knob is mistuned)."
    )
    lines.append(
        "- `dRecall < 0` on `no_semantic_match` quantifies how much "
        "recall is owed to semantic matching (the contribution of the "
        "matcher's fuzzy path)."
    )
    lines.append(
        "- `retrieval_only - full` isolates the cost of stripping the "
        "MLGG flag-synthesis layer: when the dF1 is near zero, the "
        "pipeline is mostly a retrieval wrapper."
    )
    lines.append(
        "- `top_k_*` deltas trace the recall-vs-precision frontier; "
        "expect recall monotonic in top_k, precision usually decreasing."
    )
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "NCPR v2 component ablation harness (W23-C4). Runs the "
            "NCPR pipeline against a holdout under several ablation "
            "configs and writes a markdown delta table."
        )
    )
    p.add_argument(
        "--holdout",
        type=Path,
        default=REPO_ROOT / "references" / "benchmark" / "ncpr_v1_holdout.json",
        help="Holdout JSON (default references/benchmark/ncpr_v1_holdout.json).",
    )
    p.add_argument(
        "--configs",
        nargs="+",
        default=None,
        help=f"Configs to run (default: {' '.join(DEFAULT_CONFIGS)}).",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/W23_C4_ncpr_ablation.md"),
        help="Markdown report output (default /tmp/W23_C4_ncpr_ablation.md).",
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=Path("/tmp/W23_C4_ncpr_ablation.json"),
        help="JSON sidecar output.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    if not args.holdout.exists():
        print(f"ERROR: holdout file not found: {args.holdout}", file=sys.stderr)
        return 2
    data = json.loads(args.holdout.read_text())
    if isinstance(data, list):
        holdout = data
    elif isinstance(data, dict):
        for k in ("papers", "holdout", "entries"):
            if isinstance(data.get(k), list):
                holdout = data[k]
                break
        else:
            print(
                f"ERROR: unrecognized holdout shape in {args.holdout}",
                file=sys.stderr,
            )
            return 2
    else:
        print(
            f"ERROR: unrecognized holdout shape in {args.holdout}",
            file=sys.stderr,
        )
        return 2

    try:
        results = run_ablation(holdout, configs=args.configs)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    write_ablation_report(results, args.report)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(
            {"stubbed": sorted(set(_STUBBED)), "results": results},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[ablation] wrote {args.report}", file=sys.stderr)
    print(f"[ablation] wrote {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
