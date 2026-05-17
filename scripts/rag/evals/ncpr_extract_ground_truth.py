"""NCPR v1 ground-truth extractor (W22-X8).

Given a paper_id, return the reviewer concerns + methods text that the
matcher (``ncpr_matcher.match_all``) needs as ground-truth inputs.

Two responsibilities, kept narrow on purpose:

1. ``extract_reviewer_concerns(paper_id, kb_path)`` -- read the peer-review
   KB and return the ``reviewer_concerns`` list for ``paper_id``, projected
   down to the five fields the matcher consumes
   (``concern_id``, ``concern_text``, ``severity``, ``category``,
   ``mlgg_gates``).  Only concerns whose ``status`` field is the literal
   string ``"curated"`` are returned; concerns *without* a ``status`` field
   are treated as curated (the current KB convention -- every concern in
   ``peer-review-kb.json`` is curated by virtue of being there, see
   ``references/case-studies/peer-review-kb-audit-2026-04.md``).
2. ``extract_methods_text(paper_id, case_studies_root)`` -- find the methods
   section text for ``paper_id`` using a fixed search order: KB record
   first, filesystem fallback second.

``extract_for_holdout`` is the obvious batched wrapper; it never aborts on
a single missing paper because the NCPR run loop needs to keep going so we
get partial numbers when references go stale.

``paper_id`` is the KB-level ``id`` field (``"PR-001"``, ``"PR-104"``, ...).
DOI is *not* accepted as an alias in v1 -- the matcher spec already keys
on ``id`` and adding DOI lookup here would double the surface area for
zero benefit.

This module is import-cheap on purpose (stdlib only).  It is exercised
both by the offline NCPR test suite and by the live NCPR runner, so
pulling in numpy / pandas here would be a regression.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

__all__ = [
    "PaperNotFound",
    "MethodsTextNotFound",
    "extract_reviewer_concerns",
    "extract_methods_text",
    "extract_for_holdout",
]

logger = logging.getLogger(__name__)

# Fields projected from raw KB concern records into matcher-ready dicts.
# Kept as a module constant so ``extract_for_holdout`` produces the same
# shape as single-paper calls and so the test suite has one place to
# pin the contract.
_CONCERN_FIELDS: tuple[str, ...] = (
    "concern_id",
    "concern_text",
    "severity",
    "category",
    "mlgg_gates",
)

# Methods-text file basenames probed inside
# ``<case_studies_root>/<journal_slug>/<paper_id>/`` (in this order).
_METHODS_FILENAMES: tuple[str, ...] = (
    "methods.txt",
    "methods.md",
)


class PaperNotFound(KeyError):
    """Raised when ``paper_id`` is not in the peer-review KB."""


class MethodsTextNotFound(FileNotFoundError):
    """Raised when no methods text can be located for ``paper_id``."""


# ────────────────────────────────────────────────────────────────────────
# KB loading
# ────────────────────────────────────────────────────────────────────────


def _load_kb(kb_path: Path) -> dict:
    with open(kb_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_entry(kb: dict, paper_id: str) -> dict:
    for entry in kb.get("entries", []):
        if entry.get("id") == paper_id:
            return entry
    raise PaperNotFound(
        f"paper_id={paper_id!r} not found in peer-review KB "
        f"(searched {len(kb.get('entries', []))} entries)"
    )


def _is_curated(concern: dict) -> bool:
    """Concern is curated unless its ``status`` field explicitly says otherwise.

    The KB schema (``peer_review_kb.v1.4``) does not require a ``status``
    field; every concern currently shipped *is* curated.  When a future
    schema adds a status enum (``draft``, ``curated``, ``retracted`` ...)
    this predicate becomes the gate without callers needing to change.
    """
    status = concern.get("status")
    if status is None:
        return True
    return status == "curated"


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def extract_reviewer_concerns(paper_id: str, kb_path: Path) -> list[dict]:
    """Return curated reviewer concerns for ``paper_id`` from ``kb_path``.

    Each returned dict has exactly the keys in ``_CONCERN_FIELDS``.
    Order matches the KB file order (stable for reproducible benchmarks).
    """
    kb = _load_kb(kb_path)
    entry = _find_entry(kb, paper_id)

    out: list[dict] = []
    for concern in entry.get("reviewer_concerns", []):
        if not _is_curated(concern):
            continue
        out.append({field: concern.get(field) for field in _CONCERN_FIELDS})
    return out


def _journal_slug_candidates(journal: str | None) -> list[str]:
    """Map a KB ``journal`` field to plausible ``case-studies/<slug>`` dirs.

    KB has display strings like ``"Nature Communications"``; the
    case-studies tree uses snake_case (``nature_communications``).
    We yield candidates rather than a single hard-coded mapping so the
    filesystem fallback degrades gracefully when new journals are added.
    """
    if not journal:
        return []
    raw = journal.strip()
    snake = raw.lower().replace(" ", "_").replace("-", "_")
    candidates = [snake, raw]
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _methods_text_from_field(entry: dict) -> str | None:
    for key in ("methods_text", "methods_extract"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _methods_text_from_fs(
    paper_id: str,
    entry: dict,
    case_studies_root: Path,
) -> tuple[str | None, list[Path]]:
    """Try filesystem candidates; return (text_or_None, paths_tried)."""
    tried: list[Path] = []
    for slug in _journal_slug_candidates(entry.get("journal")):
        paper_dir = case_studies_root / slug / paper_id
        if not paper_dir.exists():
            tried.append(paper_dir)
            continue
        for fname in _METHODS_FILENAMES:
            for candidate in (paper_dir / fname,
                              paper_dir / f"{paper_id}_{fname}"):
                tried.append(candidate)
                if candidate.is_file():
                    text = candidate.read_text(encoding="utf-8")
                    if text.strip():
                        return text, tried
    return None, tried


def extract_methods_text(paper_id: str, case_studies_root: Path) -> str:
    """Locate methods text for ``paper_id`` under ``case_studies_root``.

    The KB itself lives one level above ``case_studies_root`` by
    convention (``references/case-studies/peer-review-kb.json``); we look
    for it there so callers do not need to thread a second path argument
    just for the field-based fast path.

    Search order (per spec):
      1. KB entry's ``methods_text`` or ``methods_extract`` string field.
      2. ``<root>/<journal_slug>/<paper_id>/methods.{txt,md}``
      3. ``<root>/<journal_slug>/<paper_id>/<paper_id>_methods.{txt,md}``
    """
    kb_path = Path(case_studies_root) / "peer-review-kb.json"
    if not kb_path.exists():
        raise MethodsTextNotFound(
            f"cannot resolve methods text for {paper_id!r}: "
            f"KB not found at {kb_path}"
        )
    kb = _load_kb(kb_path)
    entry = _find_entry(kb, paper_id)  # raises PaperNotFound (subclass of KeyError)

    field_text = _methods_text_from_field(entry)
    if field_text is not None:
        return field_text

    fs_text, tried = _methods_text_from_fs(paper_id, entry, Path(case_studies_root))
    if fs_text is not None:
        return fs_text

    tried_str = "\n  ".join(str(p) for p in tried) or "(no journal dirs probed)"
    raise MethodsTextNotFound(
        f"methods text for paper_id={paper_id!r} not found.\n"
        f"  KB field 'methods_text'/'methods_extract': absent or empty.\n"
        f"  Filesystem candidates tried:\n  {tried_str}"
    )


def extract_for_holdout(
    holdout_paper_ids: Iterable[str],
    kb_path: Path,
) -> dict:
    """Batch wrapper. Per-paper failures logged + skipped; raises only if 0 succeed.

    ``case_studies_root`` for the methods lookup is inferred as
    ``kb_path.parent`` -- this matches the canonical repo layout where
    ``peer-review-kb.json`` sits next to the per-journal case-study
    directories.  Callers that need a non-canonical layout can fall back
    to calling ``extract_reviewer_concerns`` + ``extract_methods_text``
    directly.
    """
    case_studies_root = Path(kb_path).parent
    results: dict[str, dict] = {}
    failures: list[tuple[str, str]] = []

    for paper_id in holdout_paper_ids:
        try:
            concerns = extract_reviewer_concerns(paper_id, kb_path)
        except PaperNotFound as e:
            logger.warning("extract_for_holdout: %s skipped (concerns): %s",
                           paper_id, e)
            failures.append((paper_id, f"concerns: {e}"))
            continue
        try:
            methods = extract_methods_text(paper_id, case_studies_root)
        except (PaperNotFound, MethodsTextNotFound) as e:
            logger.warning("extract_for_holdout: %s skipped (methods): %s",
                           paper_id, e)
            failures.append((paper_id, f"methods: {e}"))
            continue
        results[paper_id] = {"concerns": concerns, "methods_text": methods}
        logger.info("extract_for_holdout: %s OK (%d concerns, %d chars methods)",
                    paper_id, len(concerns), len(methods))

    if not results:
        raise RuntimeError(
            "extract_for_holdout: 0 / %d papers extracted successfully. "
            "First failures: %s" % (
                len(failures),
                failures[:5],
            )
        )
    if failures:
        logger.warning("extract_for_holdout: %d / %d papers failed extraction",
                       len(failures), len(failures) + len(results))
    return results
