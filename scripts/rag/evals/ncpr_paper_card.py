#!/usr/bin/env python3
"""NCPR v2 — Per-paper human-readable score card (W23-C5).

Failure-mode debugging tool. When the benchmark fails on a given paper
(weighted_f1 below threshold, or some category dropped to zero), the
numeric aggregates in ``ncpr_severity_score.macro_average`` tell us
*that* something is wrong but not *what*. This module turns one
paper's matcher + scorer output into a markdown report a reviewer can
read in <30 s and decide:

  - Is MLGG missing the right concerns? (recall failure mode)
  - Is MLGG over-flagging unrelated issues? (precision failure mode)
  - Are the misses concentrated in one category? (gate-coverage gap)
  - Are the matches dominated by weak ``category`` hits? (label drift)

Design constraints
------------------
- READ-ONLY w.r.t. the matcher / scorer — consumes their output, does
  not re-run any matching logic. Reproducibility wedge: the markdown
  must be a pure function of inputs so two runs on the same inputs
  produce byte-identical reports.
- No embeddings, no network, no PDF parsing. Card generation is a
  formatting step, not an inference step.
- Diagnostic, NOT a benchmark KPI. The failure-mode hypothesis line
  is heuristic; reviewers are expected to verify it by reading the
  excerpts above.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "make_paper_card",
    "write_card_set",
]


# ---------------------------------------------------------------------------
# Text helpers — defensive against missing fields / odd types.
# ---------------------------------------------------------------------------
def _safe_text(value: Any, max_chars: int = 240) -> str:
    """Stringify + truncate one field for inline display.

    Markdown report excerpts are *quoted* free text from reviewers or
    MLGG evidence. Long blocks bury the signal, so cap at ~3 lines worth.
    """
    if value is None:
        return "(none)"
    s = str(value).strip()
    if not s:
        return "(empty)"
    s = " ".join(s.split())  # collapse internal whitespace
    if len(s) > max_chars:
        s = s[: max_chars - 1].rstrip() + "..."
    return s


def _sev_token(sev: Any) -> str:
    """Normalize severity for display; preserve unknown labels verbatim."""
    if sev is None:
        return "?"
    s = str(sev).strip()
    return s.upper() if s else "?"


def _fmt_float(value: Any, ndigits: int = 2) -> str:
    """Format numbers safely; non-numeric → '?'."""
    try:
        return f"{float(value):.{ndigits}f}"
    except (TypeError, ValueError):
        return "?"


def _slugify(paper_id: str) -> str:
    """Filesystem-safe filename stem. ASCII only, drop unsafe chars."""
    if not paper_id:
        return "unknown"
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(paper_id))
    return s.strip("._") or "unknown"


# ---------------------------------------------------------------------------
# Failure-mode heuristic.
# ---------------------------------------------------------------------------
def _failure_hypothesis(
    n_flags: int,
    n_concerns: int,
    n_matched: int,
    n_missed_critical: int,
    n_missed_high: int,
    n_over_flag: int,
    weighted_f1: float,
) -> str:
    """Return a one-line hypothesis. Heuristic, not authoritative.

    Branches in order of severity for review triage:

      1. No flags at all → MLGG silent (gate-firing bug).
      2. CRITICAL miss   → recall gap on top-severity concerns.
      3. Recall miss     → general recall gap.
      4. Over-flag       → precision gap (noisy gates).
      5. None of above + low F1 → degenerate matcher / label drift.
      6. None of above + good F1 → no obvious failure mode.
    """
    if n_concerns == 0:
        return (
            "no reviewer concerns recorded; nothing to evaluate "
            "(paper excluded from macro average)."
        )
    if n_flags == 0:
        return (
            "MLGG returned no flags despite "
            f"{n_concerns} reviewer concern(s); "
            "likely gate-firing or runner failure."
        )
    if n_missed_critical > 0:
        return (
            f"recall gap on CRITICAL concerns ({n_missed_critical} missed); "
            "investigate whether the relevant gates fired but were filtered, "
            "or whether the concern category is uncovered by MLGG."
        )
    miss_total = n_concerns - n_matched
    if miss_total > 0 and miss_total >= n_matched:
        return (
            f"general recall gap: {miss_total}/{n_concerns} concerns missed; "
            "compare reviewer concern categories with MLGG gate inventory."
        )
    if n_over_flag > 0 and n_over_flag >= max(1, n_matched):
        return (
            f"precision gap: {n_over_flag} MLGG flag(s) unmatched; "
            "check for noisy gates emitting on weak evidence."
        )
    if weighted_f1 < 0.5:
        return (
            "low F1 without dominant miss/over-flag pattern; "
            "likely match-type drift (category-only matches) — "
            "inspect cosine scores below."
        )
    return "no obvious failure mode; weighted F1 in expected range."


# ---------------------------------------------------------------------------
# Markdown assembly.
# ---------------------------------------------------------------------------
def _section_concerns(
    paper_entry: dict,
    mlgg_flags: list,
    matched_pairs: list,
) -> tuple[list[str], int, int, int]:
    """Render the reviewer-concerns block; return lines + tallies."""
    concerns = paper_entry.get("concerns") or paper_entry.get("reviewer_concerns") or []

    # concern_idx → match details (use the best pair if multiple — though
    # the matcher already dedupes concern-side, defensive coding).
    by_concern: dict[int, dict] = {}
    for p in matched_pairs or []:
        if not isinstance(p, dict):
            continue
        c_idx = p.get("concern_idx")
        if c_idx is None:
            continue
        prev = by_concern.get(c_idx)
        if prev is None or (p.get("score") or 0) > (prev.get("score") or 0):
            by_concern[c_idx] = p

    lines: list[str] = [f"## Real reviewer concerns ({len(concerns)})", ""]
    if not concerns:
        lines.append("_No reviewer concerns recorded for this paper._")
        lines.append("")
        return lines, 0, 0, 0

    n_matched = 0
    n_missed_critical = 0
    n_missed_high = 0

    for i, concern in enumerate(concerns):
        sev = _sev_token(concern.get("severity"))
        text = _safe_text(concern.get("concern_text"))
        pair = by_concern.get(i)
        if pair is None:
            mark = "MISSED"
            check = "MISS"
            if sev == "CRITICAL":
                n_missed_critical += 1
            elif sev == "HIGH":
                n_missed_high += 1
            lines.append(f"- [{sev}] {text} -> {mark}  [{check}]")
        else:
            n_matched += 1
            flag_idx = pair.get("flag_idx")
            mtype = pair.get("type") or "?"
            score = _fmt_float(pair.get("score"))
            try:
                flag = (mlgg_flags or [])[flag_idx] if flag_idx is not None else None
            except (IndexError, TypeError):
                flag = None
            code = (flag or {}).get("code", "?") if isinstance(flag, dict) else "?"
            lines.append(
                f"- [{sev}] {text} -> MATCHED by MLGG flag: "
                f"`{code}` (type={mtype}, score={score})  [OK]"
            )
    lines.append("")
    return lines, n_matched, n_missed_critical, n_missed_high


def _section_over_flag(
    mlgg_flags: list,
    matched_pairs: list,
) -> tuple[list[str], int]:
    """Render the over-flagging block; return lines + count."""
    matched_flag_ids = {
        p.get("flag_idx")
        for p in (matched_pairs or [])
        if isinstance(p, dict) and p.get("flag_idx") is not None
    }
    extras = [
        (j, f)
        for j, f in enumerate(mlgg_flags or [])
        if j not in matched_flag_ids
    ]
    lines = [
        f"## MLGG over-flagging ({len(extras)} flags didn't match any concern)",
        "",
    ]
    if not extras:
        lines.append("_All MLGG flags matched at least one reviewer concern._")
        lines.append("")
        return lines, 0

    for _, flag in extras:
        if not isinstance(flag, dict):
            lines.append(f"- (malformed flag entry: {type(flag).__name__})")
            continue
        code = flag.get("code", "?")
        sev = _sev_token(flag.get("severity"))
        ev = _safe_text(flag.get("evidence_text") or flag.get("evidence"))
        lines.append(f"- `{code}` (severity {sev}) -- evidence: {ev}")
    lines.append("")
    return lines, len(extras)


def _section_header(paper_id: str, paper_entry: dict, score_breakdown: dict) -> list[str]:
    """Header + headline scores."""
    title = _safe_text(paper_entry.get("title") or paper_entry.get("paper_title") or "(no title)", max_chars=180)
    totals = (score_breakdown or {}).get("totals") or {}
    wf1 = _fmt_float(totals.get("weighted_f1"))
    wp = _fmt_float(totals.get("wPrecision"))
    wr = _fmt_float(totals.get("wRecall"))
    cov = score_breakdown.get("category_coverage")
    cov_str: str
    if isinstance(cov, dict):
        covered = cov.get("covered")
        total = cov.get("total")
        cov_str = f"{covered}/{total}" if covered is not None and total is not None else "n/a"
    elif isinstance(cov, (int, float)):
        cov_str = f"{cov}/5"
    else:
        cov_str = "n/a"
    return [
        f"# Paper {paper_id}: {title}",
        "",
        f"Score: weighted_f1={wf1}, precision={wp}, recall={wr}, category_coverage={cov_str}",
        "",
    ]


def make_paper_card(
    paper_id: str,
    paper_entry: dict,
    mlgg_flags: list,
    matched: list,
    score_breakdown: dict,
) -> str:
    """Render one paper's debugging card as a markdown string.

    Args:
        paper_id: Stable identifier for the paper (used in title + filename).
        paper_entry: The reviewer-side dict (title + concerns list).
            Concerns expected under ``concerns`` or ``reviewer_concerns``,
            each with ``severity`` and ``concern_text``.
        mlgg_flags: The MLGG flag list passed to the matcher (in the
            same order). Each flag dict has ``code`` / ``severity`` /
            ``evidence_text``.
        matched: ``matched_pairs`` from ``match_all`` output (list of
            dicts with ``flag_idx`` / ``concern_idx`` / ``type`` / ``score``).
        score_breakdown: ``per_paper_score`` output (provides ``totals``
            and optionally ``category_coverage``).

    Returns:
        Markdown report string (trailing newline included).
    """
    paper_entry = paper_entry or {}
    mlgg_flags = mlgg_flags or []
    matched = matched or []
    score_breakdown = score_breakdown or {}

    header = _section_header(paper_id, paper_entry, score_breakdown)
    concerns_lines, n_matched, n_miss_crit, n_miss_high = _section_concerns(
        paper_entry, mlgg_flags, matched
    )
    over_lines, n_over = _section_over_flag(mlgg_flags, matched)

    totals = (score_breakdown.get("totals") or {})
    try:
        wf1 = float(totals.get("weighted_f1", 0.0))
    except (TypeError, ValueError):
        wf1 = 0.0
    n_concerns = len(paper_entry.get("concerns") or paper_entry.get("reviewer_concerns") or [])

    hypothesis = _failure_hypothesis(
        n_flags=len(mlgg_flags),
        n_concerns=n_concerns,
        n_matched=n_matched,
        n_missed_critical=n_miss_crit,
        n_missed_high=n_miss_high,
        n_over_flag=n_over,
        weighted_f1=wf1,
    )

    footer = [
        "## Failure mode hypothesis",
        "",
        hypothesis,
        "",
    ]

    return "\n".join(header + concerns_lines + over_lines + footer)


# ---------------------------------------------------------------------------
# Card-set writer
# ---------------------------------------------------------------------------
def write_card_set(per_paper_cards: dict, out_dir: Path) -> None:
    """Write one card file per paper into ``out_dir``.

    Args:
        per_paper_cards: ``{paper_id: markdown_str}``. Use
            ``make_paper_card`` to produce the values.
        out_dir: Target directory. Created if missing. Existing files
            with the same slug are OVERWRITTEN — this is a debugging
            output, not a content store.

    Raises:
        TypeError: if ``per_paper_cards`` is not a dict.
        OSError: filesystem errors propagate (callers running in CI
            should treat this as a benchmark-runner failure, not a
            recoverable condition).
    """
    if not isinstance(per_paper_cards, dict):
        raise TypeError(
            f"per_paper_cards must be dict[paper_id, str], "
            f"got {type(per_paper_cards).__name__}"
        )
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for paper_id, md in per_paper_cards.items():
        if not isinstance(md, str):
            # Non-string value would silently get repr'd; fail loud
            # because the typical cause is forgetting to call
            # make_paper_card on a raw breakdown dict.
            raise TypeError(
                f"card for paper {paper_id!r} must be str, "
                f"got {type(md).__name__}"
            )
        fname = f"card_{_slugify(str(paper_id))}.md"
        (out_path / fname).write_text(md, encoding="utf-8")
