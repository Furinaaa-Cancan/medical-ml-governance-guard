"""NCPR-Bench v1 top-level orchestrator.

End-to-end driver that ties together the W22-X1..X5 sibling modules:

  X1  ``ncpr_matcher.match_all``                   — flag <-> concern matching
  X2  ``ncpr_severity_score.per_paper_score``      — severity-weighted F1
  X3  ``ncpr_category_coverage.category_coverage`` — 5-cat coverage
  X4  ``ncpr_paper_runner.synthesize_flags_from_rag`` — SUT invocation
  X5  ``ncpr_aggregator.aggregate``                — macro-averaged summary

Per-paper flow (spec §5..§7, ``references/benchmark/ncpr_v1_spec.md``):

  1. Load reviewer concerns for the paper from peer-review-kb.json.
  2. Invoke the SUT (RAG-only or full pipeline) to get MLGG flags.
  3. Score severity-weighted F1 and recall@K / precision@K (X2 — which
     itself calls X1 internally).
  4. Compute the diagnostic category-coverage metric (X3).

Per-run aggregation:

  5. Flatten per-paper records into the schema X5 expects.
  6. Macro-average via X5.
  7. Emit JSON sidecar + Markdown report.

Stub-fallback contract
----------------------
Sibling modules may not be committed yet (wave-22 parallelism). Every
sibling import is guarded by ``try/except ImportError`` and falls back
to a deterministic stub. ``_STUBBED`` records the stub names and is
surfaced in JSON output so a CI run that accidentally exercises a stub
is loudly visible (the stubs are NOT silent no-ops). When the real
sibling lands, the ``except`` branch becomes dead code at import time.

CLI
---
::

    python3 scripts/rag/evals/run_ncpr_benchmark.py \\
        --holdout references/benchmark/ncpr_v1_holdout.json \\
        --output /tmp/ncpr_results.json \\
        --report /tmp/ncpr_report.md \\
        [--max-papers N] [--rag-only] [--top-k 20] [--kb PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_KB = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"
DEFAULT_HOLDOUT = REPO_ROOT / "references" / "benchmark" / "ncpr_v1_holdout.json"

# ── Sibling-module imports with stub fallbacks ───────────────────────────────
#
# Each ``try / except ImportError`` either binds the real sibling
# implementation or a documented stub. ``_STUBBED`` accumulates the
# stub names so the JSON report can flag any run that exercises one.

_STUBBED: list[str] = []

try:
    from scripts.rag.evals.ncpr_matcher import match_all as _match_all  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - exercised only when X1 missing
    _STUBBED.append("ncpr_matcher")

    def _match_all(flags, concerns, embed_fn=None):  # type: ignore[no-redef]
        """Stub: pretend nothing matched. Conservative — drives recall to 0."""
        return {
            "matched_pairs": [],
            "unmatched_flags": list(range(len(flags))),
            "unmatched_concerns": list(range(len(concerns))),
            "matcher": "stub",
        }


try:
    from scripts.rag.evals.ncpr_severity_score import (  # type: ignore
        per_paper_score as _per_paper_score,
    )
except ImportError:
    _STUBBED.append("ncpr_severity_score")

    def _per_paper_score(paper_id, flags, concerns, embed_fn=None):  # type: ignore[no-redef]
        """Stub: cardinal precision / recall / F1 with uniform severity=1.

        Honest minimum — it actually computes P/R/F1 from a fresh match
        so the orchestrator's wiring can be tested end-to-end. It does
        NOT apply severity weights; that lands with the real X2.
        """
        m = _match_all(flags, concerns)
        n_matched = len(m.get("matched_pairs", []))
        n_concerns = len(concerns)
        n_flags = len(flags)
        recall = n_matched / n_concerns if n_concerns else 0.0
        precision = n_matched / n_flags if n_flags else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return {
            "paper_id": paper_id,
            "n_flags": n_flags,
            "n_concerns": n_concerns,
            "matcher": m.get("matcher", "stub"),
            "totals": {
                "wTP": float(n_matched),
                "wFN": float(n_concerns - n_matched),
                "wFP": float(n_flags - n_matched),
                "wPrecision": precision,
                "wRecall": recall,
                "weighted_f1": f1,
            },
            "per_severity": {},
            "paper_excluded": n_concerns == 0,
        }


try:
    from scripts.rag.evals.ncpr_category_coverage import (  # type: ignore
        category_coverage as _category_coverage,
    )
except ImportError:
    _STUBBED.append("ncpr_category_coverage")

    _CATEGORIES = ("evaluation", "design", "reporting", "external_val", "leakage")

    def _category_coverage(flags, concerns):  # type: ignore[no-redef]
        """Stub: fraction of 5 spec categories where both sides have items."""
        flag_cats = {(f.get("category") or "").strip() for f in flags}
        # Real X3 uses ``dimension``; stub accepts either to stay safe.
        concern_cats = {
            (c.get("dimension") or c.get("category") or "").strip()
            for c in concerns
        }
        cov = {c: (c in flag_cats and c in concern_cats) for c in _CATEGORIES}
        return {
            "coverage_per_category": cov,
            "coverage_rate": sum(cov.values()) / len(_CATEGORIES),
            "missed_categories": sorted(
                c for c in _CATEGORIES
                if c in concern_cats and c not in flag_cats
            ),
            "concerns_per_category_reviewer": {
                c: sum(1 for k in concern_cats if k == c) for c in _CATEGORIES
            },
            "flags_per_category_mlgg": {
                c: sum(1 for k in flag_cats if k == c) for c in _CATEGORIES
            },
        }


try:
    from scripts.rag.evals.ncpr_paper_runner import (  # type: ignore
        synthesize_flags_from_rag as _synthesize_flags_from_rag,
    )
except ImportError:
    _STUBBED.append("ncpr_paper_runner")

    def _synthesize_flags_from_rag(query: str, top_k: int = 20) -> list[dict]:  # type: ignore[no-redef]
        """Stub: emit zero flags. Real X4 invokes the RAG retriever + LLM."""
        return []


try:
    from scripts.rag.evals.ncpr_aggregator import aggregate as _aggregate  # type: ignore
except ImportError:
    _STUBBED.append("ncpr_aggregator")

    def _aggregate(per_paper_scores: list[dict]) -> dict:  # type: ignore[no-redef]
        """Stub: macro-average per-paper weighted_f1 / precision / recall /
        category_coverage. Real X5 adds percentiles + per-severity pooling.
        """
        n = len(per_paper_scores)
        if n == 0:
            return {
                "n_papers": 0,
                "macro_weighted_f1": 0.0,
                "macro_weighted_precision": 0.0,
                "macro_weighted_recall": 0.0,
                "macro_category_coverage": 0.0,
            }

        def _mean(key: str) -> float:
            vals = [
                float(p.get(key, 0.0)) for p in per_paper_scores
                if isinstance(p.get(key), (int, float))
            ]
            return sum(vals) / len(vals) if vals else 0.0

        return {
            "n_papers": n,
            "macro_weighted_f1": _mean("weighted_f1"),
            "macro_weighted_precision": _mean("weighted_precision"),
            "macro_weighted_recall": _mean("weighted_recall"),
            "macro_category_coverage": _mean("category_coverage"),
        }


# ── Holdout + KB loading ─────────────────────────────────────────────────────


def load_holdout(holdout_path: Path) -> list[dict]:
    """Return a list of paper records from the holdout file.

    Accepts either a bare list, ``{"papers": [...]}``, ``{"holdout": [...]}``,
    or ``{"entries": [...]}`` so this orchestrator does not need to be
    rev-locked to T3's exact JSON shape.
    """
    data = json.loads(Path(holdout_path).read_text())
    if isinstance(data, list):
        return data
    for key in ("papers", "holdout", "entries"):
        if isinstance(data, dict) and key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError(f"unrecognized holdout shape in {holdout_path}")


def load_concerns_for_paper(paper: dict, kb_entries: list[dict]) -> list[dict]:
    """Pull reviewer-concern rows for a paper from peer-review-kb entries.

    Match by ``paper_doi`` first, then ``paper_id``, then ``id``. Returns
    an empty list when the paper isn't in the KB — X2's per-paper scorer
    has an ``paper_excluded`` flag that handles the zero-concern case
    per spec §5.
    """
    paper_doi = paper.get("paper_doi") or paper.get("doi")
    paper_id = paper.get("paper_id") or paper.get("id")

    for entry in kb_entries:
        if paper_doi and entry.get("paper_doi") == paper_doi:
            return list(entry.get("reviewer_concerns", []) or [])
        if paper_id and (
            entry.get("paper_id") == paper_id or entry.get("id") == paper_id
        ):
            return list(entry.get("reviewer_concerns", []) or [])
    return []


def _load_kb_entries(kb_path: Path) -> list[dict]:
    """Read peer-review-kb.json and return its ``entries`` list.

    Returns ``[]`` if the file is absent — tests with mocked holdouts
    don't have to ship a fake KB to exercise the orchestrator.
    """
    if not Path(kb_path).exists():
        return []
    data = json.loads(Path(kb_path).read_text())
    if isinstance(data, dict) and "entries" in data:
        return list(data["entries"])
    if isinstance(data, list):
        return data
    return []


# ── Per-paper pipeline ───────────────────────────────────────────────────────


def _paper_query_text(paper: dict) -> str:
    """Pull the text the SUT should query on.

    Spec §4 makes ``methods_text`` mandatory; fall back to abstract /
    title concatenation so a holdout entry that omitted the field still
    produces *some* signal rather than crashing.
    """
    for key in ("methods_text", "abstract", "summary"):
        v = paper.get(key)
        if isinstance(v, str) and v.strip():
            return v
    parts = [str(paper.get(k, "")) for k in ("title", "paper_title", "paper_id")]
    return " ".join(p for p in parts if p).strip()


def _flatten_per_paper(
    score: dict, coverage: dict, *, paper_id: str
) -> dict:
    """Flatten X2 + X3 per-paper outputs into the schema X5 consumes.

    X2 nests its weighted_f1 / wPrecision / wRecall inside ``totals``;
    X3 puts the diagnostic rate in ``coverage_rate``; X5 expects
    ``weighted_f1`` / ``weighted_precision`` / ``weighted_recall`` /
    ``category_coverage`` at the top level. This adapter is the seam.
    """
    totals = score.get("totals", {}) or {}
    return {
        "paper_id": paper_id,
        "n_flags": score.get("n_flags", 0),
        "n_concerns": score.get("n_concerns", 0),
        "matcher": score.get("matcher", "unknown"),
        "weighted_f1": float(totals.get("weighted_f1", 0.0)),
        "weighted_precision": float(totals.get("wPrecision", 0.0)),
        "weighted_recall": float(totals.get("wRecall", 0.0)),
        "category_coverage": float(coverage.get("coverage_rate", 0.0)),
        "paper_excluded": bool(score.get("paper_excluded", False)),
        "per_severity": score.get("per_severity", {}),
        "missed_categories": coverage.get("missed_categories", []),
        # full nested originals retained for downstream diagnostics
        "_score": score,
        "_coverage": coverage,
    }


def evaluate_paper(
    paper: dict,
    kb_entries: list[dict],
    *,
    top_k: int = 20,
    rag_only: bool = True,
    synth_fn: Callable[..., list[dict]] | None = None,
) -> dict:
    """Run the per-paper NCPR pipeline (spec §5–§7).

    Args:
        paper: holdout entry (at minimum a ``paper_id`` / ``paper_doi``).
        kb_entries: pre-loaded peer-review-kb ``entries`` list.
        top_k: top-K flags to retain from the SUT.
        rag_only: forward intent to the SUT. Currently informational —
            the real X4 honours it; the stub ignores it.
        synth_fn: testing seam — replaces the SUT call with a fixed
            ``paper -> [flags]`` mapping.
    """
    paper_id = (
        paper.get("paper_id")
        or paper.get("id")
        or paper.get("paper_doi")
        or "<unknown>"
    )

    concerns = load_concerns_for_paper(paper, kb_entries)

    if synth_fn is not None:
        flags = synth_fn(paper, top_k=top_k, rag_only=rag_only)
    else:
        # Real X4 signature: synthesize_flags_from_rag(query: str, top_k: int)
        flags = _synthesize_flags_from_rag(_paper_query_text(paper), top_k=top_k)

    # X2 calls X1 internally — we don't pre-match here.
    score = _per_paper_score(paper_id, flags, concerns)
    coverage = _category_coverage(flags, concerns)

    flat = _flatten_per_paper(score, coverage, paper_id=str(paper_id))
    flat["rag_only"] = rag_only
    flat["top_k"] = top_k
    return flat


# ── Top-level entry ──────────────────────────────────────────────────────────


def run_benchmark(
    holdout_path: Path,
    max_papers: int | None = None,
    rag_only: bool = True,
    top_k: int = 20,
    kb_path: Path | None = None,
    synth_fn: Callable[..., list[dict]] | None = None,
) -> dict:
    """Top-level NCPR-Bench run.

    Args:
        holdout_path: JSON file enumerating the holdout papers (T3).
        max_papers: cap on papers to evaluate. ``None`` = all; ``0`` is
            a valid smoke value — returns an empty result with the
            stub-flag inventory intact so harnesses can sanity-check the
            wiring without touching the SUT.
        rag_only: forward to X4. RAG-only mode skips static lint + gates.
        top_k: max MLGG flags per paper (spec §7 sets K=N and K=2N as
            the reported variants; this is the absolute cap to the SUT).
        kb_path: peer-review-kb.json path. Defaults to repo standard.
        synth_fn: testing seam — replaces the SUT invocation entirely.

    Returns:
        Dict with ``schema_version``, ``generated_at``, ``config``,
        ``stubbed_modules``, ``n_papers_evaluated``, ``per_paper``,
        ``summary``.
    """
    holdout_path = Path(holdout_path)
    kb_path = Path(kb_path) if kb_path is not None else DEFAULT_KB

    papers = load_holdout(holdout_path)
    if max_papers is not None:
        papers = papers[:max_papers]

    kb_entries = _load_kb_entries(kb_path)

    per_paper: list[dict] = []
    for paper in papers:
        per_paper.append(
            evaluate_paper(
                paper,
                kb_entries,
                top_k=top_k,
                rag_only=rag_only,
                synth_fn=synth_fn,
            )
        )

    summary = _aggregate(per_paper)

    return {
        "schema_version": "ncpr-bench-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "holdout_path": str(holdout_path),
            "kb_path": str(kb_path),
            "max_papers": max_papers,
            "rag_only": rag_only,
            "top_k": top_k,
        },
        "stubbed_modules": list(_STUBBED),
        "n_papers_evaluated": len(per_paper),
        "per_paper": per_paper,
        "summary": summary,
    }


# ── Report rendering ─────────────────────────────────────────────────────────


def render_report(result: dict) -> str:
    """Render a minimal Markdown report. Real X5's write_report_md may
    supersede this when wired in; this is the orchestrator's local
    fallback so the CLI always produces a viewable artifact."""
    cfg = result.get("config", {})
    summary = result.get("summary", {})
    stubs = result.get("stubbed_modules", [])

    lines: list[str] = []
    lines.append("# NCPR-Bench v1 — Run Report")
    lines.append("")
    lines.append(f"- Generated: `{result.get('generated_at', '')}`")
    lines.append(f"- Holdout: `{cfg.get('holdout_path', '')}`")
    lines.append(f"- Papers evaluated: **{result.get('n_papers_evaluated', 0)}**")
    lines.append(f"- top_k: {cfg.get('top_k')}  rag_only: {cfg.get('rag_only')}")
    if stubs:
        lines.append("")
        lines.append(
            "> **WARNING — stubbed siblings active**: "
            + ", ".join(f"`{m}`" for m in stubs)
            + ". Numbers below are NOT spec-compliant; see W22-X6 stub contract."
        )
    lines.append("")
    lines.append("## Macro-averaged metrics (spec §7)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| macro_weighted_f1 | {summary.get('macro_weighted_f1', 0.0):.4f} |")
    lines.append(f"| macro_weighted_precision | {summary.get('macro_weighted_precision', 0.0):.4f} |")
    lines.append(f"| macro_weighted_recall | {summary.get('macro_weighted_recall', 0.0):.4f} |")
    lines.append(f"| macro_category_coverage | {summary.get('macro_category_coverage', 0.0):.4f} |")
    lines.append("")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run NCPR-Bench v1 end-to-end against a holdout set.",
    )
    p.add_argument(
        "--holdout",
        type=Path,
        default=DEFAULT_HOLDOUT,
        help=f"Holdout JSON file (default: {DEFAULT_HOLDOUT}).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/ncpr_results.json"),
        help="JSON sidecar path (default: /tmp/ncpr_results.json).",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/ncpr_report.md"),
        help="Markdown report path (default: /tmp/ncpr_report.md).",
    )
    p.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="Cap on papers evaluated. 0 = smoke (no SUT calls).",
    )
    p.add_argument(
        "--rag-only",
        action="store_true",
        help="Skip static lint + gates; RAG retrieval + LLM synth only.",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Max MLGG flags retained per paper (default: 20).",
    )
    p.add_argument(
        "--kb",
        type=Path,
        default=DEFAULT_KB,
        help=f"peer-review-kb.json path (default: {DEFAULT_KB}).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    result = run_benchmark(
        holdout_path=args.holdout,
        max_papers=args.max_papers,
        rag_only=args.rag_only,
        top_k=args.top_k,
        kb_path=args.kb,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(result))

    s = result.get("summary", {})
    print(
        f"NCPR-Bench v1: n_papers={result['n_papers_evaluated']} "
        f"sw-F1={s.get('macro_weighted_f1', 0.0):.3f} "
        f"wP={s.get('macro_weighted_precision', 0.0):.3f} "
        f"wR={s.get('macro_weighted_recall', 0.0):.3f} "
        f"cat-cov={s.get('macro_category_coverage', 0.0):.3f}"
    )
    if result.get("stubbed_modules"):
        print(
            "WARNING: stubbed siblings active: "
            + ", ".join(result["stubbed_modules"]),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
