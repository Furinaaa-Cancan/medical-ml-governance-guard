"""NCPR v1 results aggregator + report writer (W22-X5).

Consumes the per-paper score records produced by the NCPR runner and
emits two artifacts:

1. ``write_results_json`` — machine-readable
   ``{"summary": ..., "per_paper": [...]}`` JSON, written atomically
   (tmp file in same directory + ``os.replace``) so a crashed run can
   never leave a half-written results file that downstream CI would
   then read as ground truth.
2. ``write_report_md`` — human-readable markdown report with summary
   table, per-severity recall, per-category recall, percentile bands,
   and the worst failure cases (papers with weighted F1 < 0.30).

Aggregation methodology
-----------------------
* ``macro_weighted_*`` — unweighted mean across papers of each paper's
  *severity-weighted* precision / recall / F1. This is a macro average
  (each paper counts equally regardless of concern count), which keeps
  one outlier paper with 30 concerns from dominating the headline
  score. Severity weighting happens inside the per-paper score (see
  ``ncpr_v1_severity_rationale.md``); we do not re-weight here.
* ``macro_category_coverage`` — mean of per-paper
  ``category_coverage`` (diagnostic-only signal per matcher spec §3.4).
* ``per_severity_recall`` / ``per_category_recall`` — pooled
  (micro-style) recall across all papers. We sum matched and total
  concerns by bucket, then divide. Macro-averaging here would give
  ``nan`` for any paper with zero concerns in a bucket and bias the
  result toward papers that happen to have only one concern in a rare
  bucket.
* ``failure_case_count`` — papers with ``weighted_f1 < 0.30``.
  Threshold pre-registered in the NCPR v1 spec; do not tune here.
* ``percentiles`` — p25 / p50 / p75 of per-paper ``weighted_f1`` via
  linear interpolation (``numpy.percentile`` default). Useful for
  spotting bimodality the mean hides.

Hard rules honored:
* No package installs.
* No new files outside ``scripts/rag/evals/ncpr_aggregator.py`` and
  ``tests/test_ncpr_aggregator.py``.
* Atomic write only (no partial overwrites of the results JSON).
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "FAILURE_F1_THRESHOLD",
    "aggregate",
    "write_results_json",
    "write_report_md",
]


# Pre-registered failure threshold (NCPR v1 spec). Do NOT tune.
FAILURE_F1_THRESHOLD: float = 0.30


# ────────────────────────────────────────────────────────────────────────
# Small numeric helpers
# ────────────────────────────────────────────────────────────────────────


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce ``value`` to a finite float, falling back to ``default``.

    Per project rule (``to_float()`` must include ``math.isfinite``
    guard): rejects ``inf`` and ``nan`` so they cannot poison
    downstream means.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _pooled_recall(
    per_paper: list[dict], bucket_key: str
) -> dict[str, float]:
    """Pool per-bucket matched / total across papers, then divide.

    Each per-paper record is expected to provide
    ``per_<bucket>_matched`` and ``per_<bucket>_total`` dicts keyed by
    bucket name (e.g. severity or category). Missing keys default to 0
    so a paper without any concerns in a rare bucket does not contribute
    nan; it simply contributes nothing.
    """
    matched_total: dict[str, int] = {}
    total_total: dict[str, int] = {}
    # The producers (ncpr_severity_score.per_paper_score etc.) emit a real
    # ``per_<bucket>`` dict keyed by bucket name with {matched, missed,
    # extra_flags} sub-counts — NOT the flat ``per_<bucket>_matched`` /
    # ``per_<bucket>_total`` form this used to read, so severity/category recall
    # was silently always empty. Read the real schema (recall denominator =
    # matched + missed; extra_flags are false positives, excluded), keeping the
    # legacy flat form as a fallback.
    real_field = f"per_{bucket_key}"
    matched_field = f"per_{bucket_key}_matched"
    total_field = f"per_{bucket_key}_total"
    for paper in per_paper:
        real = paper.get(real_field)
        if isinstance(real, dict) and real:
            for k, sub in real.items():
                if not isinstance(sub, dict):
                    continue
                m = int(sub.get("matched", 0) or 0)
                miss = int(sub.get("missed", 0) or 0)
                matched_total[k] = matched_total.get(k, 0) + m
                total_total[k] = total_total.get(k, 0) + m + miss
            continue
        # Legacy flat form (kept for back-compat with older snapshots/fixtures).
        matched = paper.get(matched_field) or {}
        total = paper.get(total_field) or {}
        for k, v in matched.items():
            matched_total[k] = matched_total.get(k, 0) + int(v or 0)
        for k, v in total.items():
            total_total[k] = total_total.get(k, 0) + int(v or 0)
            # Ensure key exists in matched_total even if 0 hits.
            matched_total.setdefault(k, 0)

    out: dict[str, float] = {}
    for k, total in total_total.items():
        if total <= 0:
            out[k] = 0.0
        else:
            out[k] = matched_total.get(k, 0) / total
    return out


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def aggregate(per_paper_scores: list[dict]) -> dict:
    """Aggregate per-paper NCPR scores into a single summary dict.

    Returns the schema documented in the task spec. All numeric values
    are plain ``float`` / ``int`` (JSON-serialisable, no numpy
    scalars), and empty input returns zeros rather than nans so the
    output is always safe to serialise and diff in CI.
    """
    n = len(per_paper_scores)
    if n == 0:
        return {
            "n_papers": 0,
            "macro_weighted_f1": 0.0,
            "macro_weighted_precision": 0.0,
            "macro_weighted_recall": 0.0,
            "macro_category_coverage": 0.0,
            "per_severity_recall": {},
            "per_category_recall": {},
            "failure_case_count": 0,
            "percentiles": {"p25": 0.0, "p50": 0.0, "p75": 0.0},
        }

    f1s = [_safe_float(p.get("weighted_f1")) for p in per_paper_scores]
    precisions = [
        _safe_float(p.get("weighted_precision")) for p in per_paper_scores
    ]
    recalls = [
        _safe_float(p.get("weighted_recall")) for p in per_paper_scores
    ]
    cat_cov = [
        _safe_float(p.get("category_coverage")) for p in per_paper_scores
    ]

    failure_case_count = sum(1 for f in f1s if f < FAILURE_F1_THRESHOLD)

    arr = np.asarray(f1s, dtype=float)
    percentiles = {
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
    }

    return {
        "n_papers": n,
        "macro_weighted_f1": _mean(f1s),
        "macro_weighted_precision": _mean(precisions),
        "macro_weighted_recall": _mean(recalls),
        "macro_category_coverage": _mean(cat_cov),
        "per_severity_recall": _pooled_recall(per_paper_scores, "severity"),
        "per_category_recall": _pooled_recall(per_paper_scores, "category"),
        "failure_case_count": failure_case_count,
        "percentiles": percentiles,
    }


def write_results_json(
    results: list[dict], summary: dict, out_path: Path
) -> None:
    """Atomically write ``{"summary": ..., "per_paper": [...]}`` JSON.

    ``out_path`` is created if its parent exists; the parent is *not*
    auto-created so an obvious typo (``./reslts/foo.json``) fails loud
    instead of silently writing to a hidden directory.

    Atomicity: writes to a sibling tempfile in the same directory, then
    ``os.replace``s it onto the target. Same-directory replace is
    atomic on POSIX and on Windows (NTFS), which guarantees readers
    never see a partially written file.
    """
    out_path = Path(out_path)
    parent = out_path.parent
    if not parent.exists():
        raise FileNotFoundError(
            f"Parent directory does not exist: {parent}. "
            "Create it explicitly before calling write_results_json."
        )

    payload = {"summary": summary, "per_paper": results}

    fd, tmp_name = tempfile.mkstemp(
        prefix=out_path.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, out_path)
    except Exception:
        # Best-effort cleanup; do not mask the original error.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ────────────────────────────────────────────────────────────────────────
# Markdown report
# ────────────────────────────────────────────────────────────────────────


def _fmt_pct(x: float) -> str:
    return f"{x:.3f}"


def _render_kv_table(title: str, mapping: dict[str, float]) -> list[str]:
    lines = [f"### {title}", "", "| Bucket | Recall |", "| --- | --- |"]
    if not mapping:
        lines.append("| _(none)_ | _n/a_ |")
    else:
        for k in sorted(mapping):
            lines.append(f"| {k} | {_fmt_pct(mapping[k])} |")
    lines.append("")
    return lines


def write_report_md(
    results: list[dict], summary: dict, out_path: Path
) -> None:
    """Render a human-readable markdown report for the NCPR run.

    The report deliberately includes the headline summary table, per-
    severity and per-category recall, percentile bands, and the top
    failure cases (papers with the lowest weighted F1). Reviewers care
    about all four; collapsing any of them loses signal.
    """
    out_path = Path(out_path)
    parent = out_path.parent
    if not parent.exists():
        raise FileNotFoundError(
            f"Parent directory does not exist: {parent}. "
            "Create it explicitly before calling write_report_md."
        )

    lines: list[str] = []
    lines.append("# NCPR v1 Benchmark Report")
    lines.append("")
    lines.append(f"_Papers scored:_ **{summary.get('n_papers', 0)}**")
    lines.append("")

    # ── Headline summary ───────────────────────────────────────────
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(
        f"| macro_weighted_f1 | {_fmt_pct(summary.get('macro_weighted_f1', 0.0))} |"
    )
    lines.append(
        f"| macro_weighted_precision | {_fmt_pct(summary.get('macro_weighted_precision', 0.0))} |"
    )
    lines.append(
        f"| macro_weighted_recall | {_fmt_pct(summary.get('macro_weighted_recall', 0.0))} |"
    )
    lines.append(
        f"| macro_category_coverage | {_fmt_pct(summary.get('macro_category_coverage', 0.0))} |"
    )
    lines.append(
        f"| failure_case_count (F1 < {FAILURE_F1_THRESHOLD:.2f}) | "
        f"{summary.get('failure_case_count', 0)} |"
    )
    lines.append("")

    # ── Percentiles ────────────────────────────────────────────────
    pct = summary.get("percentiles") or {}
    lines.append("## Percentile bands (per-paper weighted F1)")
    lines.append("")
    lines.append("| Percentile | F1 |")
    lines.append("| --- | --- |")
    for label in ("p25", "p50", "p75"):
        lines.append(f"| {label} | {_fmt_pct(_safe_float(pct.get(label)))} |")
    lines.append("")

    # ── Per-severity / per-category ────────────────────────────────
    lines.append("## Recall by severity")
    lines.append("")
    lines.extend(
        _render_kv_table("Severity recall", summary.get("per_severity_recall") or {})
    )
    lines.append("## Recall by category")
    lines.append("")
    lines.extend(
        _render_kv_table("Category recall", summary.get("per_category_recall") or {})
    )

    # ── Failure cases ──────────────────────────────────────────────
    lines.append("## Top failure cases")
    lines.append("")
    lines.append(
        f"Papers ranked by ascending weighted F1; cutoff = "
        f"{FAILURE_F1_THRESHOLD:.2f}."
    )
    lines.append("")
    failures = sorted(
        (
            (p, _safe_float(p.get("weighted_f1")))
            for p in results
        ),
        key=lambda t: t[1],
    )
    failures = [(p, f) for (p, f) in failures if f < FAILURE_F1_THRESHOLD]
    if not failures:
        lines.append("_No papers below failure threshold._")
        lines.append("")
    else:
        lines.append("| Paper ID | F1 | Precision | Recall |")
        lines.append("| --- | --- | --- | --- |")
        for paper, f1 in failures[:20]:
            pid = paper.get("paper_id") or paper.get("id") or "?"
            prec = _safe_float(paper.get("weighted_precision"))
            rec = _safe_float(paper.get("weighted_recall"))
            lines.append(
                f"| {pid} | {_fmt_pct(f1)} | {_fmt_pct(prec)} | {_fmt_pct(rec)} |"
            )
        lines.append("")

    # Atomic write — same pattern as JSON writer.
    text = "\n".join(lines)
    fd, tmp_name = tempfile.mkstemp(
        prefix=out_path.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
