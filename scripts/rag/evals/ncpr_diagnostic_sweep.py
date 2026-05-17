"""NCPR v2 diagnostic cosine-threshold sweep (W23-C1, B4 Phase 2).

Replaces v1's pre-registered guess of ``SEMANTIC_THRESHOLD = 0.70`` with
empirical evidence: for each candidate threshold ``τ`` in a user-supplied
grid, this tool re-runs the W22-X1 matcher (``match_all``) and reports
precision, recall, F1, and the number of matched pairs. The result is a
precision-recall sweep that lets the NCPR v2 spec pick a threshold *from
data* rather than from intuition.

Diagnostic only — this module deliberately does NOT mutate the v1
matcher's frozen threshold. It uses a scoped monkey-patch (via a context
manager) that restores the original value on exit so v1 benchmarks
continue to reproduce bit-for-bit.

Stubbing
--------
If the real ``rag.evals.ncpr_matcher`` is unavailable (e.g. when running
this script outside the project tree), a minimal pure-Python stub is
substituted that supports the same interface: it filters semantic matches
by the active threshold and falls back to exact-code matching otherwise.
This keeps unit tests offline and the module importable in isolation.

Caller contract
---------------
``embed_fn`` is injected by the caller. Tests use a deterministic mock
that returns fixed cosines for known phrases. Production callers pass a
BGE-small (or other) embedder. The sweep does no I/O of its own beyond
``write_sweep_report``.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "sweep_thresholds",
    "write_sweep_report",
    "DEFAULT_THRESHOLDS",
]


DEFAULT_THRESHOLDS: tuple[float, ...] = (
    0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90,
)


# ────────────────────────────────────────────────────────────────────────
# Matcher import — try real W22-X1, fall back to a faithful stub.
# ────────────────────────────────────────────────────────────────────────

try:  # pragma: no cover — exercised by both branches in tests
    from rag.evals import ncpr_matcher as _matcher_mod  # type: ignore
    _HAS_REAL_MATCHER = True
except Exception:  # ImportError, plus any transitive failure
    _matcher_mod = None  # type: ignore[assignment]
    _HAS_REAL_MATCHER = False


def _stub_match_all(
    flags: list,
    concerns: list,
    embed_fn: Optional[Callable[[str], Any]] = None,
    *,
    threshold: float = 0.70,
) -> dict:
    """Minimal stand-in for ``rag.evals.ncpr_matcher.match_all``.

    Implements the two rules the sweep actually depends on: exact-code
    match (precedence 1) and cosine-semantic match (precedence 3). Pure
    Python; no numpy dependency so the module imports under the same
    constraints as the real matcher's test harness.

    De-dup mirrors v1: each flag picks at most one concern and each
    concern keeps at most one flag (the best score wins).
    """
    def _cosine(u: Iterable[float], v: Iterable[float]) -> float:
        ul = [float(x) for x in u]
        vl = [float(x) for x in v]
        if not ul or not vl or len(ul) != len(vl):
            return 0.0
        dot = sum(a * b for a, b in zip(ul, vl))
        nu = sum(a * a for a in ul) ** 0.5
        nv = sum(b * b for b in vl) ** 0.5
        if nu == 0.0 or nv == 0.0:
            return 0.0
        return dot / (nu * nv)

    # Step 1: each flag picks its best concern (highest score wins;
    # exact_code always scores 1.0 so it dominates semantic ties).
    best_for_flag: dict[int, tuple[int, str, float]] = {}
    for i, flag in enumerate(flags):
        f_code = (flag.get("code") or "").strip().lower()
        f_text = (flag.get("evidence_text") or "").strip().lower()
        best: tuple[int, str, float] | None = None
        for j, concern in enumerate(concerns):
            gates = [
                (g or "").strip().lower()
                for g in (concern.get("mlgg_gates") or [])
            ]
            cand: tuple[int, str, float] | None = None
            # Exact code match (precedence 1).
            if f_code and f_code in gates:
                cand = (j, "exact_code", 1.0)
            elif embed_fn is not None and f_text:
                # Semantic (precedence 3).
                c_text = (concern.get("concern_text") or "").strip().lower()
                if c_text:
                    sim = _cosine(embed_fn(f_text), embed_fn(c_text))
                    if sim >= threshold:
                        cand = (j, "semantic", sim)
            if cand is None:
                continue
            if best is None or cand[2] > best[2]:
                best = cand
        if best is not None:
            best_for_flag[i] = best

    # Step 2: each concern keeps only its best flag (highest score wins).
    chosen: dict[int, tuple[int, str, float]] = {}
    for i, (j, t, s) in best_for_flag.items():
        existing = chosen.get(j)
        if existing is None or s > existing[2]:
            chosen[j] = (i, t, s)

    matched_pairs = [
        {"flag_idx": i, "concern_idx": j, "type": t, "score": s}
        for j, (i, t, s) in sorted(chosen.items())
    ]
    winning_flags = {i for (i, _t, _s) in chosen.values()}
    unmatched_flags = [i for i in range(len(flags)) if i not in winning_flags]
    unmatched_concerns = [
        j for j in range(len(concerns)) if j not in chosen
    ]
    return {
        "matched_pairs": matched_pairs,
        "unmatched_flags": unmatched_flags,
        "unmatched_concerns": unmatched_concerns,
    }


@contextlib.contextmanager
def _scoped_threshold(threshold: float):
    """Temporarily override the real matcher's frozen threshold.

    Restores the original on exit so v1 benchmarks remain reproducible.
    No-op when the real matcher isn't importable.
    """
    if not _HAS_REAL_MATCHER or _matcher_mod is None:
        yield None
        return
    original = getattr(_matcher_mod, "SEMANTIC_THRESHOLD", 0.70)
    setattr(_matcher_mod, "SEMANTIC_THRESHOLD", float(threshold))
    try:
        yield original
    finally:
        setattr(_matcher_mod, "SEMANTIC_THRESHOLD", original)


def _run_match_all(
    flags: list,
    concerns: list,
    embed_fn: Optional[Callable[[str], Any]],
    threshold: float,
) -> dict:
    """Run match_all at ``threshold`` — real matcher if available, else stub."""
    if _HAS_REAL_MATCHER and _matcher_mod is not None:
        with _scoped_threshold(threshold):
            return _matcher_mod.match_all(flags, concerns, embed_fn=embed_fn)
    return _stub_match_all(flags, concerns, embed_fn=embed_fn, threshold=threshold)


# ────────────────────────────────────────────────────────────────────────
# Scoring
# ────────────────────────────────────────────────────────────────────────


def _prf(n_pairs: int, n_flags: int, n_concerns: int) -> tuple[float, float, float]:
    """Plain precision / recall / F1 over flag-concern pair counts.

    Mirrors the conservative definition used by the v1 per-paper score:
    ``P = matched / flags``, ``R = matched / concerns``,
    ``F1 = 2PR / (P + R)``. Returns zeros for empty inputs (no crash).
    """
    p = (n_pairs / n_flags) if n_flags > 0 else 0.0
    r = (n_pairs / n_concerns) if n_concerns > 0 else 0.0
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return p, r, f1


def sweep_thresholds(
    flags: list,
    concerns: list,
    embed_fn: Callable[[str], Any],
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
) -> dict:
    """Run ``match_all`` once per ``τ`` and return a P/R/F1 table.

    Returns a dict keyed by threshold (rounded to 4 dp for stable keys)::

        {
            0.50: {"precision": ..., "recall": ..., "f1": ...,
                   "matched_pairs": n},
            ...
        }

    Matched-pair count is monotonically non-increasing in τ: a higher
    threshold strictly shrinks the set of semantic matches without
    affecting exact-code matches. Recall therefore also monotonically
    non-increases. (See ``tests/test_ncpr_diagnostic_sweep.py``.)
    """
    n_flags = len(flags)
    n_concerns = len(concerns)
    results: dict[float, dict] = {}
    # Sort thresholds for stable, ordered output without depending on dict-
    # insertion semantics from the caller.
    for tau in sorted(float(t) for t in thresholds):
        out = _run_match_all(flags, concerns, embed_fn, tau)
        pairs = out.get("matched_pairs") or []
        n_pairs = len(pairs)
        p, r, f1 = _prf(n_pairs, n_flags, n_concerns)
        results[round(tau, 4)] = {
            "precision": p,
            "recall": r,
            "f1": f1,
            "matched_pairs": n_pairs,
        }
    return results


# ────────────────────────────────────────────────────────────────────────
# Reporting
# ────────────────────────────────────────────────────────────────────────


def _ascii_curve(results: dict, width: int = 40) -> list[str]:
    """Render precision (P) and recall (R) as side-by-side ASCII bars."""
    lines = ["", "ASCII precision/recall curve (P=#, R=*):", ""]
    if not results:
        lines.append("(no data)")
        return lines
    taus = sorted(results.keys())
    for tau in taus:
        row = results[tau]
        p_bar = "#" * int(round(float(row["precision"]) * width))
        r_bar = "*" * int(round(float(row["recall"]) * width))
        lines.append(
            f"  τ={tau:0.2f}  P|{p_bar:<{width}}|  R|{r_bar:<{width}}|"
        )
    return lines


def write_sweep_report(results: dict, out_path: Path) -> None:
    """Write a markdown report with a P/R/F1 table and an ASCII curve.

    Empty ``results`` still produces a valid (if sparse) markdown file —
    callers can rely on the file existing for downstream pipeline steps.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# NCPR v2 diagnostic cosine-threshold sweep",
        "",
        "Generated by `scripts/rag/evals/ncpr_diagnostic_sweep.py` "
        "(W23-C1, B4 Phase 2). Replaces v1's pre-registered guess of "
        "`SEMANTIC_THRESHOLD = 0.70` with empirical P/R evidence.",
        "",
        "| τ (cosine) | precision | recall | F1 | matched pairs |",
        "|------------|-----------|--------|-----|---------------|",
    ]
    if results:
        for tau in sorted(results.keys()):
            row = results[tau]
            lines.append(
                f"| {tau:0.2f} | {row['precision']:0.3f} | "
                f"{row['recall']:0.3f} | {row['f1']:0.3f} | "
                f"{row['matched_pairs']} |"
            )
    else:
        lines.append("| — | — | — | — | — |")

    lines.extend(_ascii_curve(results))
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
