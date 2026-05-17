#!/usr/bin/env python3
"""NCPR v1 — Hold-out paper selector (W22-X7).

Reference implementation of the criteria pre-registered in
``references/benchmark/ncpr_v1_holdout_criteria.md`` (W22-T3). Reads
``references/case-studies/peer-review-kb.json`` + the existing eval
sets, applies the T3 eligibility filter, stratifies by journal +
severity + the 5 NCPR categories, then tie-breaks with a stable
SHA-256 hash so the selection is bit-for-bit reproducible from
``(kb_snapshot, seed)`` alone.

This module is **dry-run by default** in W22-X7: the CLI writes the
candidate hold-out JSON to a caller-supplied path (typically a
``/tmp`` location) and asks the human reviewer to approve the file
before any write into ``references/benchmark/`` happens. No
``references/`` path is touched by this script.

Mapping notes — what this builder assumed about the KB schema
-------------------------------------------------------------
The T3 criteria are written against an *idealised* schema. The
actual ``peer-review-kb.json`` (335 papers, snapshot 2026-05-17)
does not expose:

* ``publication_date`` — only ``year`` (integer). We treat
  ``publication_date_cutoff`` as a year-month string and bind it
  to the integer ``year`` (i.e. ``year <= int(cutoff[:4])``). The
  paper-month is unavailable, so any cutoff later than December
  of a given year is rounded down silently. **Documented**.

* ``methods_text`` / ``methods_extract`` — neither field is on any
  KB entry. We fall back to checking for the optional file
  ``paper-templates/<paper_id>/methods.txt``. If the directory
  does not exist, *all* candidates pass this filter (warning is
  logged once at startup).

* Snake-case journal keys (``nature_communications``) — KB stores
  display strings (``"Nature Communications"``). We normalise both
  sides into the snake-case key space before comparison.

The 5-dimension category mapping collapses the KB's 13 fine-grained
``category`` values into the T3 dimensions
``{evaluation, design, reporting, external_validation, leakage}``.
The mapping is frozen in :data:`_CATEGORY_TO_DIMENSION` and any KB
``category`` not in that map is dropped from coverage accounting
(logged at WARNING level) — matching the precedent in
``ncpr_category_coverage.py``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import re
import sys
import yaml
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

__all__ = [
    "HoldoutBuilderError",
    "APPROVED_JOURNALS",
    "FROZEN_SEED_STRING",
    "select_holdout",
    "main",
]

logger = logging.getLogger("ncpr_build_holdout")

# ----------------------------------------------------------------------
# Pre-registered constants. Do NOT mutate after first holdout commit.
# ----------------------------------------------------------------------

FROZEN_SEED_STRING: str = "ncpr_v1_seed_2026"

# Snake-case journal keys, per T3 §"Inclusion criteria" item 2.
APPROVED_JOURNALS: frozenset[str] = frozenset({
    "nature_communications",
    "communications_medicine",
    "lancet_digital_health",
    "jama",
    "nature_medicine",
    "npj_digital_medicine",
})

# T3 dimension floor: each of the five categories must hold >=10% of
# aggregate concerns across the selected holdout.
NCPR_DIMENSIONS: tuple[str, ...] = (
    "evaluation",
    "design",
    "reporting",
    "external_validation",
    "leakage",
)
CATEGORY_FLOOR_FRACTION: float = 0.10

# Severity floor per-paper (T3 §"Stratification"): each selected paper
# must have at least one CRITICAL or HIGH reviewer concern.
HIGH_SEVERITIES: frozenset[str] = frozenset({"CRITICAL", "HIGH"})

# Journal share +/- this many papers vs. the eligible-set share.
JOURNAL_BAND: int = 2
# No single journal contributes more than this fraction of holdout.
JOURNAL_CAP: float = 0.40

# Maps the 13 fine-grained KB ``category`` values to the 5-dimension
# NCPR space pre-registered in T3. Frozen for NCPR v1.
_CATEGORY_TO_DIMENSION: dict[str, str] = {
    # evaluation
    "evaluation_metrics": "evaluation",
    "clinical_utility": "evaluation",
    "model_selection": "evaluation",
    # design
    "study_design": "design",
    "sample_size": "design",
    "preprocessing": "design",
    "feature_selection": "design",
    "split_protocol": "design",
    # reporting
    "reporting": "reporting",
    "reproducibility": "reporting",
    "interpretability": "reporting",
    # external_validation
    "external_validation": "external_validation",
    # leakage
    "data_leakage": "leakage",
}

# Optional fallback location for methods text.
_METHODS_FALLBACK_ROOT = Path("paper-templates")

# Default eval-set paths (T3 §"Inclusion criteria" item 4).
_DEFAULT_EVAL_SETS: tuple[Path, ...] = (
    Path("references/retrieval_eval/scenarios.json"),
    Path("references/retrieval_eval/labeled_precision_at_5.json"),
    Path("references/case-studies/rag-eval-set.yaml"),
)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------


class HoldoutBuilderError(RuntimeError):
    """Raised when the builder cannot satisfy T3 criteria.

    Carries a ``reason`` machine-readable code so the CLI can fail-loud
    with a stable exit message that ADR templates can grep on.
    """

    def __init__(self, message: str, *, reason: str = "infeasible") -> None:
        super().__init__(message)
        self.reason = reason


# ----------------------------------------------------------------------
# Normalisation helpers
# ----------------------------------------------------------------------


_PAPER_ID_FROM_CONCERN = re.compile(r"^(PR-(?:EXP-)?\d+)")


def _normalise_journal(raw: str | None) -> str | None:
    """Map a free-form journal string to the snake_case key namespace.

    Returns ``None`` if the value is missing.
    """
    if not raw:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    aliases = {
        "nature_communications": "nature_communications",
        "communications_medicine": "communications_medicine",
        "lancet_digital_health": "lancet_digital_health",
        "the_lancet_digital_health": "lancet_digital_health",
        "jama": "jama",
        "jama_network_open": "jama",
        "nature_medicine": "nature_medicine",
        "npj_digital_medicine": "npj_digital_medicine",
        "npj_digit_med": "npj_digital_medicine",
    }
    return aliases.get(key, key)


def _paper_id_from_concern_id(concern_id: str | None) -> str | None:
    """Pull the parent paper id (``PR-001``) out of a concern id."""
    if not concern_id:
        return None
    match = _PAPER_ID_FROM_CONCERN.match(concern_id)
    return match.group(1) if match else None


def _stable_tiebreak_hash(paper_id: str, seed: int) -> str:
    """Deterministic, reproducible tiebreaker key."""
    payload = f"{paper_id}|{FROZEN_SEED_STRING}|{seed}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ----------------------------------------------------------------------
# Eval-set loaders
# ----------------------------------------------------------------------


def _load_eval_set_paper_ids(path: Path) -> set[str]:
    """Best-effort extraction of paper ids referenced by an eval set.

    Knows three formats by extension and falls back to a generic walk
    that pulls anything that *looks* like ``PR-...`` or ``PR-EXP-...``.
    """
    if not path.exists():
        logger.warning("eval set %s does not exist — skipping", path)
        return set()

    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        with path.open() as fh:
            payload = yaml.safe_load(fh)
    else:
        with path.open() as fh:
            payload = json.load(fh)

    paper_ids: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in {"concern_id", "concern_ids"} or "concern" in str(k).lower():
                    if isinstance(v, str):
                        pid = _paper_id_from_concern_id(v)
                        if pid:
                            paper_ids.add(pid)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                pid = _paper_id_from_concern_id(item)
                                if pid:
                                    paper_ids.add(pid)
                            elif isinstance(item, dict):
                                walk(item)
                if k in {"paper_id", "paper_ids"}:
                    if isinstance(v, str):
                        paper_ids.add(v)
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                paper_ids.add(item)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return paper_ids


# ----------------------------------------------------------------------
# Core filter + stratify
# ----------------------------------------------------------------------


def _eligible(
    entry: dict,
    *,
    excluded_ids: set[str],
    year_cutoff: int,
    methods_root_exists: bool,
) -> tuple[bool, str | None]:
    """Apply T3 criteria 1-5. Returns ``(ok, reason_if_rejected)``."""
    pid = entry.get("id")
    if not pid:
        return False, "missing_id"

    # 1: >=3 reviewer concerns
    concerns = entry.get("reviewer_concerns") or []
    if len(concerns) < 3:
        return False, "concern_density"

    # 2: approved journal
    journal_key = _normalise_journal(entry.get("journal"))
    if journal_key not in APPROVED_JOURNALS:
        return False, "journal_out_of_scope"

    # 3: methods text or fallback
    if not (entry.get("methods_text") or entry.get("methods_extract")):
        if methods_root_exists:
            fallback = _METHODS_FALLBACK_ROOT / pid / "methods.txt"
            if not fallback.exists():
                return False, "no_methods_text"
        # If no fallback root exists at all, treat as soft-pass
        # (we logged a single WARNING at startup). Documented.

    # 4: not in any eval set
    if pid in excluded_ids:
        return False, "in_existing_eval_set"

    # 5: publication date <= cutoff. Only ``year`` is available in KB.
    year = entry.get("year")
    if not isinstance(year, int) or year > year_cutoff:
        return False, "post_cutoff"

    return True, None


def _classify_dimensions(concerns: list[dict]) -> Counter[str]:
    """Project a paper's concerns onto the 5 NCPR dimensions."""
    out: Counter[str] = Counter()
    for c in concerns:
        cat = c.get("category")
        dim = _CATEGORY_TO_DIMENSION.get(cat)
        if dim is None:
            logger.warning("unknown KB category %r — skipping for dimension floor", cat)
            continue
        out[dim] += 1
    return out


def _has_high_severity(concerns: list[dict]) -> bool:
    return any(c.get("severity") in HIGH_SEVERITIES for c in concerns)


def select_holdout(
    kb_path: Path,
    n: int = 30,
    seed: int = 42,
    existing_eval_sets: list[Path] | None = None,
    publication_date_cutoff: str = "2026-04-30",
) -> list[dict]:
    """Apply W22-T3 criteria, return a sorted list of selected records.

    See module docstring for the schema assumptions this builder makes
    about the actual KB layout (no ``publication_date``, no
    ``methods_text``, display-name journals, 13-vs-5 category space).
    """
    if not kb_path.exists():
        raise HoldoutBuilderError(
            f"KB not found at {kb_path}", reason="kb_missing"
        )

    with kb_path.open() as fh:
        kb = json.load(fh)
    entries = kb.get("entries") or []
    if not entries:
        raise HoldoutBuilderError(
            "KB has zero entries — cannot select", reason="empty_kb"
        )

    # Resolve eval-set exclusions
    eval_sets = list(existing_eval_sets) if existing_eval_sets is not None else list(
        _DEFAULT_EVAL_SETS
    )
    excluded_ids: set[str] = set()
    for path in eval_sets:
        excluded_ids |= _load_eval_set_paper_ids(path)
    logger.info("excluded %d paper_ids from %d eval set(s)",
                len(excluded_ids), len(eval_sets))

    # Year cutoff
    try:
        year_cutoff = int(publication_date_cutoff[:4])
    except (TypeError, ValueError) as exc:
        raise HoldoutBuilderError(
            f"bad publication_date_cutoff={publication_date_cutoff!r}",
            reason="bad_cutoff",
        ) from exc

    methods_root_exists = _METHODS_FALLBACK_ROOT.exists()
    if not methods_root_exists:
        logger.warning(
            "methods fallback root %s does not exist — criterion 3 soft-passes",
            _METHODS_FALLBACK_ROOT,
        )

    # Stage 1: criterion filter
    eligible: list[dict] = []
    reject_reasons: Counter[str] = Counter()
    for entry in entries:
        ok, reason = _eligible(
            entry,
            excluded_ids=excluded_ids,
            year_cutoff=year_cutoff,
            methods_root_exists=methods_root_exists,
        )
        if ok:
            eligible.append(entry)
        else:
            reject_reasons[reason or "unknown"] += 1

    logger.info(
        "eligibility: %d/%d papers passed; rejects=%s",
        len(eligible), len(entries), dict(reject_reasons),
    )

    if len(eligible) < n:
        raise HoldoutBuilderError(
            f"only {len(eligible)} eligible papers (< n={n}); rejects={dict(reject_reasons)}",
            reason="insufficient_eligible",
        )

    # Stage 2: severity floor per-paper
    severity_pool = [e for e in eligible if _has_high_severity(e.get("reviewer_concerns") or [])]
    if len(severity_pool) < n:
        raise HoldoutBuilderError(
            f"only {len(severity_pool)} eligible papers have CRITICAL/HIGH "
            f"severity (< n={n})",
            reason="severity_floor_infeasible",
        )

    # Stage 3: journal stratification target
    journal_counts_pool: Counter[str] = Counter(
        _normalise_journal(e.get("journal")) for e in severity_pool
    )
    pool_total = sum(journal_counts_pool.values())
    journal_target: dict[str, int] = {}
    for j, cnt in journal_counts_pool.items():
        journal_target[j] = round(n * cnt / pool_total)
    # Adjust to sum exactly to n
    diff = n - sum(journal_target.values())
    if diff != 0:
        # Apply diff to the largest-pool journal
        biggest = max(journal_counts_pool, key=journal_counts_pool.get)
        journal_target[biggest] += diff
    # Apply cap
    cap = int(n * JOURNAL_CAP)
    for j in list(journal_target):
        if journal_target[j] > cap:
            overflow = journal_target[j] - cap
            journal_target[j] = cap
            # redistribute to the next-biggest journals (whose pool can absorb it)
            for receiver in sorted(
                journal_counts_pool, key=journal_counts_pool.get, reverse=True
            ):
                if receiver == j:
                    continue
                room = journal_counts_pool[receiver] - journal_target.get(receiver, 0)
                if room <= 0:
                    continue
                take = min(room, overflow)
                journal_target[receiver] = journal_target.get(receiver, 0) + take
                overflow -= take
                if overflow == 0:
                    break
            if overflow > 0:
                raise HoldoutBuilderError(
                    f"journal cap {JOURNAL_CAP:.0%} infeasible — cannot "
                    f"redistribute {overflow} slots away from {j}",
                    reason="journal_cap_infeasible",
                )

    # Stage 4: greedy fill, tie-broken by stable hash
    by_journal: dict[str, list[dict]] = defaultdict(list)
    for e in severity_pool:
        by_journal[_normalise_journal(e.get("journal"))].append(e)
    for j in by_journal:
        by_journal[j].sort(
            key=lambda e: _stable_tiebreak_hash(e["id"], seed)
        )

    selected: list[dict] = []
    for j, quota in journal_target.items():
        selected.extend(by_journal[j][:quota])

    # Sanity: should be exactly n
    if len(selected) != n:
        raise HoldoutBuilderError(
            f"stratifier produced {len(selected)} != n={n} "
            f"(targets={journal_target}); bug in builder",
            reason="strat_count_mismatch",
        )

    # Stage 5: category floor verification
    agg_dims: Counter[str] = Counter()
    for e in selected:
        agg_dims.update(_classify_dimensions(e.get("reviewer_concerns") or []))
    total_dim_concerns = sum(agg_dims.values())
    floor = CATEGORY_FLOOR_FRACTION * total_dim_concerns
    short_dims = [d for d in NCPR_DIMENSIONS if agg_dims.get(d, 0) < floor]
    if short_dims:
        logger.warning(
            "category floor (>=10%%) not met for %s; observed=%s",
            short_dims, dict(agg_dims),
        )
        # T3 §"Failure modes": augment from communications_medicine one at a
        # time. We just record the deviation and let the caller decide rather
        # than recursively re-pick; full augmentation is W22 follow-up.
        for e in selected:
            e.setdefault("_stratification_warnings", []).append(
                {"kind": "category_floor", "missing": short_dims}
            )

    # Stage 6: deterministic output sort
    selected.sort(key=lambda e: e["id"])
    return selected


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _kb_snapshot_sha(kb_path: Path) -> str:
    h = hashlib.sha256()
    with kb_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NCPR v1 hold-out builder (W22-X7 dry-run mode)",
    )
    parser.add_argument(
        "--kb",
        type=Path,
        default=Path("references/case-studies/peer-review-kb.json"),
        help="Path to peer-review KB JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the dry-run holdout JSON (must NOT be under references/).",
    )
    parser.add_argument("--n", type=int, default=30, help="Hold-out size (default 30).")
    parser.add_argument("--seed", type=int, default=42, help="Tiebreak seed.")
    parser.add_argument(
        "--cutoff",
        type=str,
        default="2026-04-30",
        help="publication_date_cutoff (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        action="append",
        default=None,
        help="Existing eval-set path to exclude (repeatable).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    # HARD CONSTRAINT (W22-X7): refuse to write inside references/
    out_resolved = args.output.resolve()
    if "references" in out_resolved.parts:
        logger.error(
            "refusing to write inside references/ — this is a dry run; "
            "approve content first then move manually",
        )
        return 2

    try:
        selected = select_holdout(
            kb_path=args.kb,
            n=args.n,
            seed=args.seed,
            existing_eval_sets=args.eval_set,
            publication_date_cutoff=args.cutoff,
        )
    except HoldoutBuilderError as exc:
        logger.error("holdout build failed: %s [reason=%s]", exc, exc.reason)
        return 2

    snapshot_sha = _kb_snapshot_sha(args.kb)
    holdout_ids = sorted(e["id"] for e in selected)

    # Re-derive aggregates for the output schema.
    journal_dist: Counter[str] = Counter(
        _normalise_journal(e.get("journal")) for e in selected
    )
    dim_agg: Counter[str] = Counter()
    deviations: list[dict] = []
    for e in selected:
        dim_agg.update(_classify_dimensions(e.get("reviewer_concerns") or []))
        for warn in e.get("_stratification_warnings", []):
            if warn not in deviations:
                deviations.append(warn)

    payload = {
        "holdout_ids": holdout_ids,
        "selection_seed": FROZEN_SEED_STRING,
        "tiebreak_seed_int": args.seed,
        "kb_path": str(args.kb),
        "kb_snapshot_sha": snapshot_sha,
        "eligible_count": len(selected),
        "n": args.n,
        "publication_date_cutoff": args.cutoff,
        "journal_distribution": dict(journal_dist),
        "dimension_aggregate": dict(dim_agg),
        "stratification_deviations": deviations,
        "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_dry_run": True,
        "_wave": "W22-X7",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    fh_path = str(args.output)
    print(f"wrote {len(holdout_ids)} holdout paper_ids to {fh_path}")
    print(f"journal_distribution={dict(journal_dist)}")
    print(f"dimension_aggregate={dict(dim_agg)}")
    if deviations:
        print(f"stratification_deviations={deviations}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
